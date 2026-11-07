"""Selected exact stored-script and search-template lifecycle effects."""

import hashlib
import json
import sys
from pathlib import Path

from error_shape_probe import request


def run(config):
    if config["release"] not in {
        "6.0.0",
        "6.0.1",
        "6.1.4",
        "6.2.4",
        "6.3.2",
        "6.4.3",
        "6.5.4",
        "6.6.2",
        "6.7.2",
        "6.8.23",
        "7.0.1",
        "7.1.1",
        "7.2.1",
        "7.3.2",
        "7.4.2",
        "7.5.2",
        "7.6.2",
        "7.7.1",
        "7.8.1",
        "7.9.3",
        "7.10.2",
        "7.11.2",
        "7.12.1",
        "7.13.4",
        "7.14.2",
        "7.15.2",
        "9.5.6",
    }:
        raise ValueError("Only exact source-reviewed stored-template releases are admitted")
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=False)
    index = config["index"]
    script = config["script"]
    if not index.startswith("es-cli-template-index-") or not script.startswith(
        "es-cli-template-script-"
    ):
        raise ValueError("Owned index and stored-script prefixes required")
    rows = []
    profile = config.get("wire_profile", {})
    json_media = "application/json"
    response_media = profile.get("response_media", json_media)
    product_header = ["Elasticsearch"] if profile.get("product_header", True) else None
    document_type = profile.get("document_type", "_doc")
    ndjson_media = "application/x-ndjson"
    index_path = "/" + index
    script_path = "/_scripts/" + script
    render_path = "/_render/template/" + script
    search_path = index_path + "/_search/template"
    msearch_path = index_path + "/_msearch/template"

    def ask(case, api, method, path, body, status, media=json_media):
        if isinstance(body, str):
            raw = body.encode()
        elif body is not None:
            raw = json.dumps(body, separators=(",", ":")).encode()
        else:
            raw = None
        row = {
            "case": case,
            "api_id": api,
            "request_body": body,
            "expected_status": status,
            "request_body_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
            "requested_accept": json_media,
            **request(config["base"], method, path, media, raw, accept=json_media),
        }
        rows.append(row)
        (out / "observations.json").write_text(json.dumps(rows, indent=2) + "\n")
        assert row["body_complete"] and row["excerpt_complete"] and row["status"] == status, row
        headers = {key.lower(): value for key, value in row["headers"].items()}
        assert headers.get("x-elastic-product") == product_header, row
        assert headers.get("content-type") == [response_media], row
        print(case, row["status"], flush=True)
        return json.loads(row["body_excerpt"]) if row["body_excerpt"] else None

    def render(case, body):
        value = ask(case, "render_search_template", "POST", render_path, body, 200)
        return value["template_output"]

    def search(case, params):
        value = ask(
            case, "search_template", "POST", search_path, {"id": script, "params": params}, 200
        )
        return [hit["_id"] for hit in value["hits"]["hits"]]

    absent = ask("script-absent-before", "get_script", "GET", script_path, None, 404)
    assert absent == {"_id": script, "found": False}, absent
    mapping = {"properties": {"tag": {"type": "keyword"}}}
    if profile.get("typed_mapping"):
        mapping = {document_type: mapping}
    assert ask(
        "index-create",
        "indices.create",
        "PUT",
        index_path,
        {"mappings": mapping},
        200,
    )["acknowledged"]
    quote = 'b"quoted'
    for doc, tag in [("a", "a"), ("b", quote)]:
        ask(
            "insert-" + doc,
            "index",
            "PUT",
            index_path + "/" + document_type + "/" + doc,
            {"tag": tag},
            201,
        )
    ask("refresh", "indices.refresh", "POST", index_path + "/_refresh", None, 200)
    assert ask("count-before", "count", "GET", index_path + "/_count", None, 200)["count"] == 2

    initial = '{"query":{"term":{"tag":"{{tag}}"}}}'
    assert ask(
        "put-script",
        "put_script",
        "PUT",
        script_path,
        {"script": {"lang": "mustache", "source": initial}},
        200,
    )["acknowledged"]
    value = ask("get-script-initial", "get_script", "GET", script_path, None, 200)
    assert (
        value["found"]
        and value["script"]["lang"] == "mustache"
        and value["script"]["source"] == initial
    ), value
    assert render("render-path-id-wins", {"id": script + "-missing", "params": {"tag": "a"}}) == {
        "query": {"term": {"tag": "a"}}
    }
    assert render("render-quote-escaped", {"params": {"tag": quote}}) == {
        "query": {"term": {"tag": quote}}
    }
    assert search("search-quote-hit", {"tag": quote}) == ["b"]
    assert render("render-missing-param-empty", {"params": {}}) == {"query": {"term": {"tag": ""}}}
    assert search("search-missing-param-zero", {}) == []

    lines = [
        {"index": index},
        {"id": script, "params": {"tag": "a"}},
        {"index": index},
        {"id": script + "-missing", "params": {"tag": "a"}},
    ]
    ndjson = "\n".join(json.dumps(line, separators=(",", ":")) for line in lines) + "\n"
    value = ask(
        "msearch-mixed-item-status",
        "msearch_template",
        "POST",
        msearch_path + "?max_concurrent_searches=1",
        ndjson,
        200,
        ndjson_media,
    )
    first, second = value["responses"]
    assert [hit["_id"] for hit in first["hits"]["hits"]] == ["a"], value
    assert second["error"]["type"] == "resource_not_found_exception", value
    if profile.get("item_status_fields", True):
        assert first["status"] == 200 and second["status"] == 404, value
    else:
        assert "status" not in first and "status" not in second, value
    if config["release"] == "7.4.2":
        for case, media, status in (
            ("msearch-json-media", json_media, 200),
            ("msearch-plain-media", "text/plain", 406),
        ):
            control = ask(
                case,
                "msearch_template",
                "POST",
                msearch_path + "?max_concurrent_searches=1",
                ndjson,
                status,
                media,
            )
            if status == 200:
                hit, missing = control["responses"]
                assert [doc["_id"] for doc in hit["hits"]["hits"]] == ["a"], control
                assert missing["error"]["type"] == "resource_not_found_exception", control
    if config["release"] == "7.11.2":
        for case, media in (
            ("msearch-vendor-json", "application/vnd.elasticsearch+json;compatible-with=7"),
            ("msearch-vendor-ndjson", "application/vnd.elasticsearch+x-ndjson;compatible-with=7"),
        ):
            control = ask(
                case,
                "msearch_template",
                "POST",
                msearch_path + "?max_concurrent_searches=1",
                ndjson,
                200,
                media,
            )
            hit, missing = control["responses"]
            assert [doc["_id"] for doc in hit["hits"]["hits"]] == ["a"], control
            assert missing["error"]["type"] == "resource_not_found_exception", control
    if config["release"] in {"7.1.1", "7.2.1"}:
        value = ask(
            "msearch-leading-lf",
            "msearch_template",
            "POST",
            msearch_path,
            "\n" + "\n".join(ndjson.splitlines()[:2]) + "\n",
            200,
            ndjson_media,
        )
        (item,) = value["responses"]
        assert [hit["_id"] for hit in item["hits"]["hits"]] == ["a"], value
    value = ask(
        "msearch-zero-concurrency",
        "msearch_template",
        "POST",
        msearch_path + "?max_concurrent_searches=0",
        ndjson,
        400,
        ndjson_media,
    )
    assert value["error"]["reason"] == "maxConcurrentSearchRequests must be positive", value
    value = ask(
        "msearch-missing-final-lf",
        "msearch_template",
        "POST",
        msearch_path,
        ndjson[:-1],
        400,
        ndjson_media,
    )
    assert value["error"]["reason"] == "The msearch request must be terminated by a newline [\n]", (
        value
    )

    updated = '{"query":{"match_none":{}}}'
    assert ask(
        "post-replace-script",
        "put_script",
        "POST",
        script_path,
        {"script": {"lang": "mustache", "source": updated}},
        200,
    )["acknowledged"]
    value = ask("get-script-replaced", "get_script", "GET", script_path, None, 200)
    assert value["found"] and value["script"]["source"] == updated and updated != initial, value
    assert render("render-replaced-script", {"params": {"tag": "a"}}) == {
        "query": {"match_none": {}}
    }
    assert search("search-replaced-zero", {"tag": "a"}) == []
    assert ask("count-after", "count", "GET", index_path + "/_count", None, 200)["count"] == 2

    assert ask("delete-script", "delete_script", "DELETE", script_path, None, 200)["acknowledged"]
    absent = ask("script-absent-after", "get_script", "GET", script_path, None, 404)
    assert absent == {"_id": script, "found": False}, absent
    value = ask(
        "render-deleted-script",
        "render_search_template",
        "POST",
        render_path,
        {"params": {"tag": "a"}},
        404,
    )
    assert (
        value["error"]["type"] == "resource_not_found_exception"
        and script in value["error"]["reason"]
    ), value
    value = ask("delete-missing-script", "delete_script", "DELETE", script_path, None, 404)
    assert (
        value["error"]["type"] == "resource_not_found_exception"
        and script in value["error"]["reason"]
    ), value
    assert ask("delete-index", "indices.delete", "DELETE", index_path, None, 200)["acknowledged"]
    ask("index-absent", "indices.exists", "HEAD", index_path, None, 404)
    (out / "summary.json").write_text(
        json.dumps(
            {
                "release": config["release"],
                "status": "selected-assertions-passed",
                "actual_http_responses": len(rows),
                "owned_index_removed": True,
                "owned_script_removed": True,
                "limitations": [
                    "Finite exact stored-template fixture only. No full API, cross-project, pressure, cancellation, auth/TLS or consumer claim."
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    run(json.load(sys.stdin))
