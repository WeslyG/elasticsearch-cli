"""Search, NDJSON multi-search and lifecycle evidence for scroll/PIT contexts."""

import json

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_PILOTS

# Exact root PIT route/query recipes reviewed from pinned server sources.
ROOT_PIT_PROBE_RELEASES = frozenset(
    {
        "7.13.4",
        "7.14.2",
        "7.15.2",
        "7.16.3",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
    }
)


def declare(add, version="9.5.6"):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if (
            version in EARLY_SEVEN_PILOTS
            and version not in ROOT_PIT_PROBE_RELEASES
            and name.startswith("pit.")
        ):
            return
        add("query." + name, api, method, path, expected=expected, purpose=purpose)
        graph["query." + name] = tuple("query." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed", "bulk", "POST", "/{index}/_bulk?refresh=true", ("create",), purpose="fixture-setup"
    )
    case("seed-count", "count", "GET", "/{index}/_count", ("seed",), purpose="fixture-precondition")
    for method in ["GET", "POST"]:
        for scope, base in [("global", ""), ("index", "/{index}")]:
            name = method.lower() + "." + scope
            case("search." + name, "search", method, base + "/_search", ("seed-count",))
            case("msearch." + name, "msearch", method, base + "/_msearch", ("seed-count",))
            case("count." + name, "count", method, base + "/_count", ("seed-count",))
            case(
                "validate." + name,
                "indices.validate_query",
                method,
                base + "/_validate/query?explain=true&rewrite=true&all_shards=true",
                ("seed-count",),
            )
            case(
                "shards." + name, "search_shards", method, base + "/_search_shards", ("seed-count",)
            )
        case("explain." + method.lower(), "explain", method, "/{index}/_explain/2", ("seed-count",))
    case("invalid-query", "search", "POST", "/{index}/_search", ("seed-count",), (400,))
    case("msearch-partial", "msearch", "POST", "/{index}/_msearch", ("seed-count",))
    case("msearch-invalid-dsl", "msearch", "POST", "/{index}/_msearch", ("seed-count",), (400,))
    for variant, endpoint, method in [
        ("get-body", "/_search/scroll", "GET"),
        ("post-body", "/_search/scroll", "POST"),
        ("get-path", "/_search/scroll/{scroll_id}", "GET"),
        ("post-path", "/_search/scroll/{scroll_id}", "POST"),
    ]:
        stem = "scroll." + variant
        case(stem + ".start", "search", "POST", "/{index}/_search?scroll=1m", ("seed-count",))
        for page in range(1, 6):
            prior = stem + (".start" if page == 1 else ".page." + str(page - 1))
            case(
                stem + ".page." + str(page),
                "scroll",
                method,
                endpoint,
                (prior,),
                purpose="effect-check",
            )
        clearpath = "/_search/scroll/{scroll_id}" if variant.endswith("path") else "/_search/scroll"
        case(stem + ".clear", "clear_scroll", "DELETE", clearpath, (stem + ".page.5",))
        case(
            stem + ".expired",
            "scroll",
            "POST",
            "/_search/scroll",
            (stem + ".clear",),
            (404,),
            purpose="effect-check",
        )
    case(
        "pit.open",
        "open_point_in_time",
        "POST",
        "/{index}/_pit?keep_alive=1m"
        + ("&max_concurrent_shard_requests=1" if version == "8.8.2" else ""),
        ("seed-count",),
    )
    case(
        "pit.add-document",
        "index",
        "PUT",
        "/{index}/_doc/later?refresh=true",
        ("pit.open",),
        (201,),
        purpose="fixture-setup",
    )
    case(
        "pit.live-count",
        "count",
        "GET",
        "/{index}/_count",
        ("pit.add-document",),
        purpose="fixture-precondition",
    )
    for page in range(3):
        deps = ("pit.live-count",) if page == 0 else ("pit.page." + str(page - 1),)
        case("pit.page." + str(page), "search", "POST", "/_search", deps, purpose="effect-check")
    case("pit.close", "close_point_in_time", "DELETE", "/_pit", ("pit.page.2",))
    case("pit.closed", "search", "POST", "/_search", ("pit.close",), (404,), purpose="effect-check")
    if version in ROOT_PIT_PROBE_RELEASES:
        case(
            "pit.root-no-index",
            "open_point_in_time",
            "POST",
            "/_pit?keep_alive=1m",
            ("pit.closed",),
            (400,),
        )
        case(
            "pit.no-keep-alive",
            "open_point_in_time",
            "POST",
            "/{index}/_pit",
            ("pit.closed",),
            (
                (500,)
                if version in {"7.14.2", "7.15.2", "7.16.3", "8.0.1", "8.1.3", "8.2.3"}
                else (400,)
            ),
        )
        case(
            "pit.root-open",
            "open_point_in_time",
            "POST",
            "/_pit?index={index}&keep_alive=1m",
            ("pit.closed",),
        )
        case(
            "pit.root-search",
            "search",
            "GET",
            "/_search",
            ("pit.root-open",),
            purpose="effect-check",
        )
        case("pit.root-close", "close_point_in_time", "DELETE", "/_pit", ("pit.root-search",))
    if version in {"8.3.3", "8.4.3", "8.5.3", "8.6.2", "8.7.1", "8.8.2"}:
        for param, value in [
            ("suggest_text", "elastc"),
            ("suggest_size", "1"),
            ("suggest_mode", "always"),
        ]:
            case(
                "suggest.missing." + param,
                "search",
                "GET",
                "/{index}/_search?" + param + "=" + value,
                ("seed-count",),
                (400,),
            )
        for method in ["GET", "POST"]:
            case(
                "suggest.query." + method.lower(),
                "search",
                method,
                "/{index}/_search?suggest_field=word&suggest_text=elastc&suggest_size=1&suggest_mode=always",
                ("seed-count",),
                purpose="effect-check",
            )
        case(
            "suggest.body",
            "search",
            "POST",
            "/{index}/_search",
            ("seed-count",),
            purpose="effect-check",
        )
        case(
            "suggest.count-preserved",
            "count",
            "GET",
            "/{index}/_count",
            (
                "suggest.query.get",
                "suggest.query.post",
                "suggest.body",
                "suggest.missing.suggest_text",
                "suggest.missing.suggest_size",
                "suggest.missing.suggest_mode",
            ),
            purpose="effect-check",
        )
    if version in {"8.6.2", "8.7.1", "8.8.2"}:
        case(
            "usage.before",
            "cluster.stats",
            "GET",
            "/_cluster/stats?filter_path=indices.search",
            ("seed-count",),
            purpose="fixture-precondition",
        )
        case(
            "usage.filtered",
            "search",
            "POST",
            "/{index}/_search",
            ("usage.before",),
            purpose="effect-check",
        )
        case(
            "usage.after",
            "cluster.stats",
            "GET",
            "/_cluster/stats?filter_path=indices.search",
            ("usage.filtered",),
            purpose="effect-check",
        )
        case("depth.at-limit", "search", "POST", "/{index}/_search", ("seed-count",))
        case("depth.over-limit", "search", "POST", "/{index}/_search", ("seed-count",), (400,))
        case(
            "depth.preserved-count",
            "count",
            "GET",
            "/{index}/_count",
            ("usage.after", "depth.at-limit", "depth.over-limit"),
            purpose="effect-check",
        )
    if version == "8.8.2":
        case(
            "pit.concurrent-zero",
            "open_point_in_time",
            "POST",
            "/{index}/_pit?keep_alive=1m&max_concurrent_shard_requests=0",
            ("seed-count",),
            (400,),
        )
        case("named.default", "search", "POST", "/{index}/_search", ("seed-count",))
        for method in ["GET", "POST"]:
            case(
                "named.score-" + method.lower(),
                "search",
                method,
                "/{index}/_search?include_named_queries_score=true",
                ("seed-count",),
            )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {"index": prefix + "-query", "scroll_id": "unavailable"}
    index = values["index"]

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
        case = catalog.cases["query." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["query." + n for n in verifies],
            semantic=semantic,
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def lines(parts):
        return ("\n".join(json.dumps(p) for p in parts) + "\n").encode()

    def ids(data):
        return [h["_id"] for h in data["hits"]["hits"]]

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "n": {"type": "integer"},
                    **(
                        {"word": {"type": "text"}}
                        if catalog.version in {"8.3.3", "8.4.3", "8.5.3", "8.6.2", "8.7.1", "8.8.2"}
                        else {}
                    ),
                }
            },
        },
        [("created", lambda d: d["acknowledged"], True)],
    )
    try:
        parts = []
        for n in range(5):
            parts.extend(
                [
                    {"index": {"_id": str(n)}},
                    {
                        "n": n,
                        **(
                            {"word": "elastic"}
                            if catalog.version
                            in {"8.3.3", "8.4.3", "8.5.3", "8.6.2", "8.7.1", "8.8.2"}
                            else {}
                        ),
                    },
                ]
            )
        call("seed", lines(parts), [("bulk no errors", lambda d: d["errors"], False)], ndjson=True)
        call("seed-count", assertions=[("five documents", lambda d: d["count"], 5)])
        if catalog.version in {"8.3.3", "8.4.3", "8.5.3", "8.6.2", "8.7.1", "8.8.2"}:
            for param in ["suggest_text", "suggest_size", "suggest_mode"]:
                call(
                    "suggest.missing." + param,
                    assertions=[
                        (
                            "missing suggest_field diagnosed",
                            lambda d: "missing 'suggest_field' parameter" in d["error"]["reason"],
                            True,
                        ),
                        (
                            "specific parameter dependency error",
                            lambda d: d["error"]["type"],
                            "illegal_argument_exception",
                        ),
                    ],
                )
            for method in ["get", "post"]:
                call(
                    "suggest.query." + method,
                    assertions=[
                        (
                            "real indexed word suggested",
                            lambda d: [x["text"] for x in d["suggest"]["word"][0]["options"]],
                            ["elastic"],
                        )
                    ],
                    verifies=["seed"],
                    semantic=True,
                )
            call(
                "suggest.body",
                {
                    "size": 0,
                    "suggest": {
                        "spell": {
                            "text": "elastc",
                            "term": {"field": "word", "size": 1, "suggest_mode": "always"},
                        }
                    },
                },
                assertions=[
                    (
                        "body DSL suggests same indexed word",
                        lambda d: [x["text"] for x in d["suggest"]["spell"][0]["options"]],
                        ["elastic"],
                    )
                ],
                verifies=["seed"],
                semantic=True,
            )
            call(
                "suggest.count-preserved",
                assertions=[("all five original docs preserved", lambda d: d["count"], 5)],
                verifies=["suggest.query.get", "suggest.query.post", "suggest.body"],
                semantic=True,
            )
        if catalog.version in {"8.6.2", "8.7.1", "8.8.2"}:
            before = call(
                "usage.before",
                assertions=[
                    (
                        "local search counter available",
                        lambda d: isinstance(d["indices"]["search"]["total"], int),
                        True,
                    )
                ],
            )
            baseline = before.data.get("indices", {}).get("search", {})
            call(
                "usage.filtered",
                {
                    "query": {
                        "bool": {"filter": [{"term": {"n": 2}}, {"term": {"word": "elastic"}}]}
                    },
                    "_source": {"includes": ["n"], "excludes": ["word"]},
                },
                assertions=[
                    ("two term predicates select real doc", ids, ["2"]),
                    (
                        "source filter retains only n",
                        lambda d: d["hits"]["hits"][0]["_source"],
                        {"n": 2},
                    ),
                ],
                verifies=["seed"],
                semantic=True,
            )
            call(
                "usage.after",
                assertions=[
                    (
                        "one parsed REST search counted",
                        lambda d: d["indices"]["search"]["total"] - baseline.get("total", -999),
                        1,
                    ),
                    *[
                        (
                            ("distinct " + name + " query counted once"),
                            lambda d, name=name: (
                                d["indices"]["search"]["queries"].get(name, 0)
                                - baseline.get("queries", {}).get(name, 0)
                            ),
                            1,
                        )
                        for name in ["bool", "term"]
                    ],
                    *[
                        (
                            ("section " + name + " counted once"),
                            lambda d, name=name: (
                                d["indices"]["search"]["sections"].get(name, 0)
                                - baseline.get("sections", {}).get(name, 0)
                            ),
                            1,
                        )
                        for name in ["query", "_source"]
                    ],
                ],
                verifies=["usage.filtered"],
                semantic=True,
            )
            for name, bool_depth in [("depth.at-limit", 29), ("depth.over-limit", 30)]:
                nested = {"match_all": {}}
                for _ in range(bool_depth):
                    nested = {"bool": {"filter": [nested]}}
                checks = (
                    [("depth30 query reads five docs", ids, ["0", "1", "2", "3", "4"])]
                    if name == "depth.at-limit"
                    else [
                        (
                            "depth31 rejected with exact setting",
                            lambda d: "indices.query.bool.max_nested_depth" in str(d["error"]),
                            True,
                        )
                    ]
                )
                call(name, {"query": nested, "sort": [{"n": "asc"}]}, assertions=checks)
            call(
                "depth.preserved-count",
                assertions=[
                    ("all five docs preserved after parser boundaries", lambda d: d["count"], 5)
                ],
                verifies=["usage.filtered", "depth.at-limit", "depth.over-limit"],
                semantic=True,
            )
        if catalog.version == "8.8.2":
            call(
                "pit.concurrent-zero",
                assertions=[
                    (
                        "zero shard concurrency rejected",
                        lambda d: "maxConcurrentShardRequests must be >= 1" in str(d["error"]),
                        True,
                    )
                ],
            )
            named = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"n": {"value": 2, "_name": "number"}}},
                            {"term": {"word": {"value": "elastic", "_name": "word"}}},
                        ]
                    }
                }
            }
            call(
                "named.default",
                named,
                [
                    ("named query actual document", ids, ["2"]),
                    (
                        "default named matches have list type",
                        lambda d: isinstance(d["hits"]["hits"][0]["matched_queries"], list),
                        True,
                    ),
                    (
                        "default matched query names are a list",
                        lambda d: sorted(d["hits"]["hits"][0]["matched_queries"]),
                        ["number", "word"],
                    ),
                ],
                semantic=True,
            )
            for method in ["get", "post"]:
                call(
                    "named.score-" + method,
                    named,
                    [
                        ("same actual match with score output", ids, ["2"]),
                        (
                            "matched query scores keyed by exact names",
                            lambda d: sorted(d["hits"]["hits"][0]["matched_queries"].keys()),
                            ["number", "word"],
                        ),
                        (
                            "both actual matched scores positive numbers",
                            lambda d: all(
                                isinstance(v, (int, float)) and v > 0
                                for v in d["hits"]["hits"][0]["matched_queries"].values()
                            ),
                            True,
                        ),
                    ],
                    verifies=["named.default"],
                    semantic=True,
                )
        query = {"query": {"range": {"n": {"gte": 2}}}, "sort": [{"n": "asc"}]}
        for method in ["get", "post"]:
            for scope in ["global", "index"]:
                stem = method + "." + scope
                scoped = {**query}
                if scope == "global":
                    scoped["query"] = {
                        "bool": {
                            "filter": [{"term": {"_index": index}}, {"range": {"n": {"gte": 2}}}]
                        }
                    }
                call(
                    "search." + stem,
                    scoped,
                    [("ordered matching IDs", ids, ["2", "3", "4"])],
                    semantic=True,
                )
                call(
                    "msearch." + stem,
                    lines(
                        [
                            {"index": index},
                            {"query": {"range": {"n": {"gte": 2}}}, "sort": [{"n": "asc"}]},
                            {"index": index},
                            {"query": {"term": {"n": 0}}},
                        ]
                    ),
                    [
                        ("first response IDs", lambda d: ids(d["responses"][0]), ["2", "3", "4"]),
                        ("second response IDs", lambda d: ids(d["responses"][1]), ["0"]),
                    ],
                    semantic=True,
                    ndjson=True,
                )
                call(
                    "count." + stem,
                    {"query": scoped["query"]},
                    [("matching count", lambda d: d["count"], 3)],
                    semantic=True,
                )
                call(
                    "validate." + stem,
                    {"query": {"range": {"n": {"gte": 2}}}},
                    [
                        ("valid query", lambda d: d["valid"], True),
                        ("rewritten explanations", lambda d: len(d["explanations"]) > 0, True),
                    ],
                )
                call(
                    "shards." + stem,
                    assertions=[
                        (
                            "fixture shard present",
                            lambda d: any(
                                shard["index"] == index for group in d["shards"] for shard in group
                            ),
                            True,
                        )
                    ],
                )
            call(
                "explain." + method,
                {"query": {"term": {"n": 2}}},
                [
                    ("document matched", lambda d: d["matched"], True),
                    ("explanation returned", lambda d: "description" in d["explanation"], True),
                ],
                semantic=True,
            )
        call(
            "invalid-query",
            {"query": {"this_query_does_not_exist": {}}},
            [("invalid DSL rejected", lambda d: d["error"]["type"], "parsing_exception")],
        )
        call(
            "msearch-invalid-dsl",
            lines(
                [
                    {},
                    {"query": {"term": {"n": 2}}},
                    {},
                    {"query": {"this_query_does_not_exist": {}}},
                ]
            ),
            [("whole request parse error", lambda d: d["error"]["type"], "parsing_exception")],
            ndjson=True,
        )
        call(
            "msearch-partial",
            lines(
                [
                    {},
                    {"query": {"term": {"n": 2}}},
                    {"index": index + "-missing"},
                    {"query": {"match_all": {}}},
                ]
            ),
            [
                ("first response succeeds", lambda d: ids(d["responses"][0]), ["2"]),
                ("second response missing index", lambda d: d["responses"][1]["status"], 404),
                (
                    "per-item error type",
                    lambda d: d["responses"][1]["error"]["type"],
                    "index_not_found_exception",
                ),
            ],
            semantic=True,
            ndjson=True,
        )
        for variant in ["get-body", "post-body", "get-path", "post-path"]:
            stem = "scroll." + variant
            response = call(
                stem + ".start", {"size": 1, "sort": [{"n": "asc"}]}, [("first page", ids, ["0"])]
            )
            values["scroll_id"] = (response.data or {}).get("_scroll_id", "unavailable")
            for page in range(1, 6):
                body = {"scroll": "1m"}
                if variant.endswith("body"):
                    body["scroll_id"] = values["scroll_id"]
                response = call(
                    stem + ".page." + str(page),
                    body,
                    [("next page", ids, [str(page)] if page < 5 else [])],
                    semantic=True,
                )
                values["scroll_id"] = (response.data or {}).get("_scroll_id", values["scroll_id"])
            body = OMITTED if variant.endswith("path") else {"scroll_id": [values["scroll_id"]]}
            call(stem + ".clear", body, [("freed one scroll", lambda d: d["num_freed"], 1)])
            call(
                stem + ".expired",
                {"scroll_id": values["scroll_id"], "scroll": "1m"},
                [
                    (
                        "missing context",
                        lambda d: "search_context_missing_exception" in json.dumps(d["error"]),
                        True,
                    )
                ],
                verifies=[stem + ".clear"],
            )
        if catalog.version not in EARLY_SEVEN_PILOTS or catalog.version in ROOT_PIT_PROBE_RELEASES:
            response = call(
                "pit.open", assertions=[("PIT ID returned", lambda d: bool(d["id"]), True)]
            )
            pit_id = (response.data or {}).get("id", "unavailable")
            call("pit.add-document", {"n": 5})
            call(
                "pit.live-count",
                assertions=[("live index now has six documents", lambda d: d["count"], 6)],
            )
            after = None
            for page in range(3):
                body = {
                    "size": 2,
                    "pit": {"id": pit_id, "keep_alive": "1m"},
                    "sort": [{"n": "asc"}],
                    "track_total_hits": True,
                }
                if after is not None:
                    body["search_after"] = after
                response = call(
                    "pit.page." + str(page),
                    body,
                    [
                        (
                            "stable original snapshot count",
                            lambda d: d["hits"]["total"]["value"],
                            5,
                        ),
                        (
                            "snapshot page IDs",
                            ids,
                            [str(n) for n in range(page * 2, min(page * 2 + 2, 5))],
                        ),
                    ],
                    verifies=["pit.open"],
                    semantic=True,
                )
                data = response.data or {}
                pit_id = data.get("pit_id", pit_id)
                hits = data.get("hits", {}).get("hits", [])
                after = hits[-1]["sort"] if hits else after
            call(
                "pit.close",
                {"id": pit_id},
                [
                    ("PIT closed", lambda d: d["succeeded"], True),
                    ("one PIT freed", lambda d: d["num_freed"], 1),
                ],
            )
            call(
                "pit.closed",
                {"pit": {"id": pit_id}, "query": {"match_all": {}}},
                [
                    (
                        "closed PIT unavailable",
                        lambda d: "search_context_missing_exception" in json.dumps(d["error"]),
                        True,
                    )
                ],
                verifies=["pit.close"],
            )
            if catalog.version in ROOT_PIT_PROBE_RELEASES:
                for name, message in [
                    ("pit.root-no-index", "[index] is not specified"),
                    (
                        "pit.no-keep-alive",
                        "[keep_alive] parameter must be non null"
                        if catalog.version
                        in {"7.14.2", "7.15.2", "7.16.3", "8.0.1", "8.1.3", "8.2.3"}
                        else "[keep_alive] is not specified",
                    ),
                ]:
                    call(
                        name,
                        assertions=[
                            (
                                "required parameter rejected",
                                lambda d, message=message: message in json.dumps(d["error"]),
                                True,
                            )
                        ],
                    )
                response = call(
                    "pit.root-open",
                    assertions=[("root route returns PIT", lambda d: bool(d["id"]), True)],
                )
                root_id = (response.data or {}).get("id", "unavailable")
                response = call(
                    "pit.root-search",
                    {
                        "size": 10,
                        "pit": {"id": root_id, "keep_alive": "1m"},
                        "sort": [{"n": "asc"}],
                        "track_total_hits": True,
                    },
                    [
                        (
                            "new snapshot includes later document",
                            lambda d: d["hits"]["total"]["value"],
                            6,
                        ),
                        ("six distinct IDs", lambda d: len(set(ids(d))), 6),
                    ],
                    verifies=["pit.root-open"],
                    semantic=True,
                )
                root_id = (response.data or {}).get("pit_id", root_id)
                call(
                    "pit.root-close",
                    {"id": root_id},
                    [
                        ("PIT closed", lambda d: d["succeeded"], True),
                        ("one context freed", lambda d: d["num_freed"], 1),
                    ],
                )
    finally:
        call("cleanup")
