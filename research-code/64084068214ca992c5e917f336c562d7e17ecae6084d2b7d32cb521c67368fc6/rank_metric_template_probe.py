"""Exact 8.19.24 graded rank metrics and inline templates on a disposable owned index."""

import copy
import json
import math
import sys
from pathlib import Path

from error_shape_probe import request


def run(config):
    if config["release"] != "8.19.24":
        raise ValueError("Only exact source-reviewed 8.19.24 is admitted")
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=False)
    index = config["index"]
    if not index.startswith("es-cli-rank-metric-"):
        raise ValueError("Owned index prefix required")
    rows = []

    def ask(case, method, path, body, status):
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        row = {"case": case, "request_body": body, "expected_status": status,
               **request(config["base"], method, path, "application/json", raw)}
        rows.append(row)
        (out / "observations.json").write_text(json.dumps(rows, indent=2) + "\n")
        assert row["body_complete"] and row["excerpt_complete"], row
        assert row["status"] == status, row
        headers = {key.lower(): value for key, value in row["headers"].items()}
        assert headers.get("x-elastic-product") == ["Elasticsearch"], row
        print(case, row["status"], flush=True)
        return json.loads(row["body_excerpt"]) if row["body_excerpt"] else None

    ask("create", "PUT", "/" + index, {"mappings": {"properties": {
        "rank": {"type": "integer"}, "group": {"type": "keyword"},
        "title": {"type": "keyword"}, "hidden": {"type": "keyword"},
    }}}, 200)
    for rank, doc in enumerate(["a", "b", "c"]):
        ask("insert-" + doc, "PUT", "/" + index + "/_doc/" + doc,
            {"rank": rank, "group": "g", "title": "title-" + doc, "hidden": "hidden-" + doc}, 201)
    ask("refresh", "POST", "/" + index + "/_refresh", None, 200)
    assert ask("count-before", "GET", "/" + index + "/_count", None, 200)["count"] == 3
    ratings = [{"_index": index, "_id": doc, "rating": grade}
               for doc, grade in [("a", 0), ("b", 3), ("c", 2), ("missing", 1)]]
    query = {"query": {"match_all": {}}, "sort": [{"rank": "asc"}], "size": 1}

    def payload(metric, options=None, rated=None):
        return {"requests": [{"id": "q", "request": copy.deepcopy(query),
                              "ratings": copy.deepcopy(ratings if rated is None else rated)}],
                "metric": {metric: options or {"k": 3}}}

    def evaluate(case, metric, body, expected, hits=3):
        value = ask(case, "POST", "/" + index + "/_rank_eval", body, 200)
        assert not value["failures"], value
        detail = value["details"]["q"]
        assert math.isclose(value["metric_score"], expected, rel_tol=1e-10, abs_tol=1e-12), value
        assert math.isclose(detail["metric_score"], expected, rel_tol=1e-10, abs_tol=1e-12), value
        assert [x["hit"]["_id"] for x in detail["hits"]] == ["a", "b", "c"][:hits], value
        assert all("_source" not in x["hit"] for x in detail["hits"]), value
        return detail["metric_details"][metric], detail

    evaluate("precision", "precision", payload("precision"), 2 / 3)
    detail, _ = evaluate("recall-absent-rated", "recall", payload("recall"), 2 / 3)
    assert detail == {"relevant_docs_retrieved": 2, "relevant_docs": 3}, detail
    detail, _ = evaluate("reciprocal-rank", "reciprocal_rank", payload("reciprocal_rank"), 0.5)
    assert detail == {"first_relevant": 2}, detail
    dcg = 7 / math.log2(3) + 3 / math.log2(4)
    ideal = 7 + 3 / math.log2(3) + 1 / math.log2(4)
    detail, _ = evaluate("dcg", "dcg", payload("dcg"), dcg)
    assert math.isclose(detail["dcg"], dcg) and "ideal_dcg" not in detail, detail
    detail, _ = evaluate("normalized-dcg", "dcg", payload("dcg", {"k": 3, "normalize": True}), dcg / ideal)
    assert math.isclose(detail["ideal_dcg"], ideal), detail
    evaluate("expected-reciprocal-rank", "expected_reciprocal_rank",
             payload("expected_reciprocal_rank", {"k": 3, "maximum_relevance": 3}), 0.453125)
    evaluate("metric-k-overrides-size", "recall", payload("recall", {"k": 2}), 1 / 3, hits=2)
    detail, _ = evaluate("no-relevant-mrr", "reciprocal_rank",
                         payload("reciprocal_rank", {"k": 3, "relevant_rating_threshold": 4}), 0)
    assert detail["first_relevant"] == -1, detail
    detail, _ = evaluate("no-relevant-recall", "recall",
                         payload("recall", {"k": 3, "relevant_rating_threshold": 4}), 0)
    assert detail["relevant_docs"] == 0, detail
    unrated = [x for x in ratings if x["_id"] != "c"]
    for unknown in [None, 1]:
        options = {"k": 3}
        if unknown is not None:
            options["unknown_doc_rating"] = unknown
        detail, result = evaluate("dcg-unrated-" + str(unknown), "dcg",
                                  payload("dcg", options, unrated),
                                  7 / math.log2(3) + (0 if unknown is None else 0.5))
        assert detail["unrated_docs"] == 1 and result["hits"][2]["rating"] is None, result
        options = {**options, "maximum_relevance": 3}
        detail, _ = evaluate("err-unrated-" + str(unknown), "expected_reciprocal_rank",
                             payload("expected_reciprocal_rank", options, unrated),
                             0.4375 + (0 if unknown is None else 1 / 192))
        assert detail["unrated_docs"] == 1, detail

    template_source = json.dumps({"query": {"term": {"group": "{{group}}" }}, "sort": [{"rank": "asc"}]})
    template = {"id": "t", "template": {"lang": "mustache", "source": template_source}}
    body = {"requests": [{"id": "q", "template_id": "t", "params": {"group": "g"}, "ratings": ratings}],
            "templates": [template], "metric": {"precision": {"k": 3}}}
    evaluate("inline-template", "precision", body, 2 / 3)
    summary = copy.deepcopy(body)
    summary["requests"][0]["summary_fields"] = ["title"]
    value = ask("summary-fields", "POST", "/" + index + "/_rank_eval", summary, 200)
    assert math.isclose(value["metric_score"], 2 / 3), value
    hits = value["details"]["q"]["hits"]
    assert [x["hit"]["_source"] for x in hits] == [{"title": "title-" + x} for x in ["a", "b", "c"]], value
    duplicate = copy.deepcopy(body)
    duplicate["templates"].insert(0, {"id": "t", "template": {
        "source": '{"query":{"match_none":{}}}', "lang": "mustache"}})
    evaluate("duplicate-template-last-wins", "precision", duplicate, 2 / 3)
    for case, update in [
        ("query-plus-params", {"request": query}),
        ("params-without-template-id", {"template_id": None}),
        ("template-id-without-params", {"params": {}}),
    ]:
        invalid = copy.deepcopy(body)
        invalid["requests"][0].update(update)
        if update.get("template_id", True) is None:
            invalid["requests"][0].pop("template_id")
        ask(case, "POST", "/" + index + "/_rank_eval", invalid, 400)
    partial = payload("precision")
    partial["requests"].append({"id": "broken", "template_id": "bad", "params": {"x": "y"}, "ratings": ratings})
    partial["templates"] = [{"id": "bad", "template": {"lang": "mustache", "source": "{"}}]
    value = ask("malformed-template-output-aborts", "POST", "/" + index + "/_rank_eval", partial, 400)
    assert isinstance(value["error"], dict) and "metric_score" not in value, value
    assert ask("count-after", "GET", "/" + index + "/_count", None, 200)["count"] == 3
    assert ask("cleanup", "DELETE", "/" + index, None, 200)["acknowledged"]
    ask("absent", "HEAD", "/" + index, None, 404)
    (out / "summary.json").write_text(json.dumps({
        "release": config["release"], "status": "selected-assertions-passed",
        "actual_http_responses": len(rows), "owned_index_removed": True,
        "limitations": ["Finite graded corpus and inline templates only; no whole API, stored script, distributed or consumer claim."],
    }, indent=2) + "\n")


if __name__ == "__main__":
    run(json.load(sys.stdin))
