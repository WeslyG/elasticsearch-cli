"""Typed search, per-item msearch failures and scroll lifecycle on ES 6."""

import json

from evidence_runner import OMITTED
from legacy_release_selection import LEGACY_INVALID_INPUT_500_RELEASES


def declare(add, version="6.0.0"):
    graph = {}

    def case(name, api, method, path, expected=(200,), deps=(), purpose="api-contract"):
        add("legacy-query." + name, api, method, path, expected=expected, purpose=purpose)
        graph["legacy-query." + name] = tuple("legacy-query." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed",
        "bulk",
        "POST",
        "/{index}/_bulk?refresh=true",
        deps=("create",),
        purpose="fixture-setup",
    )
    for method in ["GET", "POST"]:
        for scope, base in [
            ("global", ""),
            ("index", "/{index}"),
            ("typed", "/{index}/{doc_type}"),
        ]:
            case(
                "search-" + method.lower() + "-" + scope,
                "search",
                method,
                base + "/_search",
                deps=("seed",),
            )
            case(
                "count-" + method.lower() + "-" + scope,
                "count",
                method,
                base + "/_count",
                deps=("seed",),
            )
            case(
                "validate-" + method.lower() + "-" + scope,
                "indices.validate_query",
                method,
                base + "/_validate/query?explain=true",
                deps=("seed",),
            )
            case(
                "msearch-" + method.lower() + "-" + scope,
                "msearch",
                method,
                base + "/_msearch",
                deps=("seed",),
            )
            case(
                "msearch-newline-" + method.lower() + "-" + scope,
                "msearch",
                method,
                base + "/_msearch",
                (400,),
                ("seed",),
            )
        for scope, base in [("global", ""), ("index", "/{index}")]:
            case(
                "shards-" + method.lower() + "-" + scope,
                "search_shards",
                method,
                base + "/_search_shards?routing=fixture",
                deps=("seed",),
            )
    case(
        "malformed-json",
        "search",
        "POST",
        "/{index}/_search",
        (500,) if version in LEGACY_INVALID_INPUT_500_RELEASES else (400,),
        ("seed",),
    )
    for method in ["GET", "POST"]:
        for variant in ["body", "path"]:
            stem = "scroll-" + method.lower() + "-" + variant
            continuation = "/_search/scroll" + ("/{scroll_id}" if variant == "path" else "")
            clear = "/_search/scroll" + ("/{scroll_id}" if variant == "path" else "")
            case(
                stem + "-init",
                "search",
                "POST",
                "/{index}/_search?scroll=1m",
                deps=("seed",),
                purpose="fixture-setup",
            )
            previous = stem + "-init"
            for page in [1, 2, 3]:
                name = stem + "-page-" + str(page)
                case(name, "scroll", method, continuation, deps=(previous,))
                previous = name
            case(
                stem + "-clear-empty",
                "clear_scroll",
                "DELETE",
                clear,
                deps=(previous,),
                purpose="cleanup",
            )
            case(
                stem + "-expired-empty",
                "scroll",
                method,
                continuation,
                (404,),
                (stem + "-clear-empty",),
            )
            case(
                stem + "-live-init",
                "search",
                "POST",
                "/{index}/_search?scroll=1m",
                deps=("seed",),
                purpose="fixture-setup",
            )
            case(stem + "-clear-live", "clear_scroll", "DELETE", clear, deps=(stem + "-live-init",))
            case(
                stem + "-expired-live",
                "scroll",
                method,
                continuation,
                (404,),
                (stem + "-clear-live",),
                "effect-check",
            )
    case("cleanup", "indices.delete", "DELETE", "/{index}", (200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    if not catalog.version.startswith("6."):
        raise ValueError("Typed search fixture requires Elasticsearch 6")
    values = {"index": prefix + "-legacy-query", "doc_type": "fixture", "scroll_id": "not-created"}

    def call(name, body=OMITTED, assertions=(), verifies=(), ndjson=False):
        spec = catalog.cases["legacy-query." + name]
        result = catalog.execute(
            run,
            spec.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=spec.dependency_plan,
            verifies=["legacy-query." + n for n in verifies],
            semantic=bool(verifies),
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(spec.id, result.state, result.status, flush=True)
        return result

    def ids(data):
        return [hit["_id"] for hit in data["hits"]["hits"]]

    def context_missing(data):
        return "search_context_missing_exception" in json.dumps(data.get("error"))

    owner_query = {
        "bool": {"filter": [{"term": {"_index": values["index"]}}, {"range": {"n": {"gte": 2}}}]}
    }
    search_body = {"query": owner_query, "sort": [{"n": "asc"}], "_source": ["n"]}
    init_body = {"query": {"match_all": {}}, "size": 2, "sort": [{"n": "asc"}]}
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"fixture": {"properties": {"n": {"type": "integer"}}}},
        },
        [("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        parts = []
        for n in range(5):
            parts.extend([{"index": {"_type": "fixture", "_id": str(n)}}, {"n": n}])
        call(
            "seed",
            ("\n".join(json.dumps(d) for d in parts) + "\n").encode(),
            [("seed no errors", lambda d: d["errors"], False)],
            ndjson=True,
        )
        for method in ["get", "post"]:
            for scope in ["global", "index", "typed"]:
                call(
                    "search-" + method + "-" + scope,
                    search_body,
                    [
                        ("integer hits total", lambda d: d["hits"]["total"], 3),
                        ("exact sorted IDs", ids, ["2", "3", "4"]),
                        (
                            "source filtering",
                            lambda d: [sorted(h["_source"]) for h in d["hits"]["hits"]],
                            [["n"], ["n"], ["n"]],
                        ),
                    ],
                )
                call(
                    "count-" + method + "-" + scope,
                    {"query": owner_query},
                    [("filtered count", lambda d: d["count"], 3)],
                )
                call(
                    "validate-" + method + "-" + scope,
                    {"query": owner_query},
                    [
                        ("query is valid", lambda d: d["valid"], True),
                        (
                            "own index explanation",
                            lambda d: any(
                                e["index"] == values["index"] and e["valid"]
                                for e in d["explanations"]
                            ),
                            True,
                        ),
                    ],
                )
                header = {"index": values["index"], "type": "fixture"}
                missing = {"index": values["index"] + "-absent", "type": "fixture"}
                request = (
                    "\n".join(
                        json.dumps(d)
                        for d in [
                            header,
                            {"query": {"term": {"n": 1}}},
                            missing,
                            {"query": {"match_all": {}}},
                        ]
                    )
                    + "\n"
                )
                call(
                    "msearch-" + method + "-" + scope,
                    request.encode(),
                    [
                        (
                            "successful neighbor retained",
                            lambda d: d["responses"][0]["hits"]["hits"][0]["_source"]["n"],
                            1,
                        ),
                        (
                            "missing index per-item status",
                            lambda d: d["responses"][1]["status"],
                            404,
                        ),
                        (
                            "missing index per-item error",
                            lambda d: d["responses"][1]["error"]["type"],
                            "index_not_found_exception",
                        ),
                    ],
                    ndjson=True,
                )
                one = "\n".join(json.dumps(d) for d in [header, {"query": {"match_all": {}}}])
                call(
                    "msearch-newline-" + method + "-" + scope,
                    one.encode(),
                    [("structured framing rejection", lambda d: bool(d.get("error")), True)],
                    ndjson=True,
                )
            for scope in ["global", "index"]:
                call(
                    "shards-" + method + "-" + scope,
                    assertions=[
                        (
                            "own active primary represented",
                            lambda d: any(
                                s["index"] == values["index"]
                                and s["primary"]
                                and s["state"] == "STARTED"
                                for group in d["shards"]
                                for s in group
                            ),
                            True,
                        )
                    ],
                )
        malformed_checks = [("structured JSON rejection", lambda d: bool(d.get("error")), True)]
        if catalog.version in LEGACY_INVALID_INPUT_500_RELEASES:
            malformed_checks.extend(
                [
                    (
                        "original server EOF error type",
                        lambda d: d["error"]["type"],
                        "json_e_o_f_exception",
                    ),
                    (
                        "EOF cause preserved",
                        lambda d: "Unexpected end-of-input" in d["error"]["reason"],
                        True,
                    ),
                ]
            )
        call("malformed-json", b'{"query":', malformed_checks)
        for method in ["get", "post"]:
            for variant in ["body", "path"]:
                stem = "scroll-" + method + "-" + variant

                def scroll_body():
                    return {
                        "scroll": "1m",
                        **({"scroll_id": values["scroll_id"]} if variant == "body" else {}),
                    }

                def clear_body():
                    return {"scroll_id": [values["scroll_id"]]} if variant == "body" else OMITTED

                response = call(
                    stem + "-init",
                    init_body,
                    [
                        ("first two IDs", ids, ["0", "1"]),
                        (
                            "cursor present",
                            lambda d: (
                                isinstance(d.get("_scroll_id"), str) and bool(d["_scroll_id"])
                            ),
                            True,
                        ),
                    ],
                )
                if response.passed:
                    values["scroll_id"] = response.data["_scroll_id"]
                for page, expected in [(1, ["2", "3"]), (2, ["4"]), (3, [])]:
                    response = call(
                        stem + "-page-" + str(page),
                        scroll_body(),
                        [("exact page IDs", ids, expected)],
                    )
                    if response.passed:
                        values["scroll_id"] = response.data.get("_scroll_id", values["scroll_id"])
                call(
                    stem + "-clear-empty",
                    clear_body(),
                    [
                        ("clear accepted", lambda d: d["succeeded"], True),
                        (
                            "nonnegative freed count",
                            lambda d: isinstance(d["num_freed"], int) and d["num_freed"] >= 0,
                            True,
                        ),
                    ],
                )
                call(
                    stem + "-expired-empty",
                    scroll_body(),
                    [("missing context", context_missing, True)],
                )
                response = call(
                    stem + "-live-init",
                    init_body,
                    [
                        ("live cursor still has remaining documents", ids, ["0", "1"]),
                        (
                            "cursor present",
                            lambda d: (
                                isinstance(d.get("_scroll_id"), str) and bool(d["_scroll_id"])
                            ),
                            True,
                        ),
                    ],
                )
                if response.passed:
                    values["scroll_id"] = response.data["_scroll_id"]
                call(
                    stem + "-clear-live",
                    clear_body(),
                    [
                        ("clear accepted", lambda d: d["succeeded"], True),
                        ("one live context freed", lambda d: d["num_freed"], 1),
                    ],
                )
                call(
                    stem + "-expired-live",
                    scroll_body(),
                    [("live context now missing", context_missing, True)],
                    verifies=[stem + "-clear-live"],
                )
    finally:
        call("cleanup")
