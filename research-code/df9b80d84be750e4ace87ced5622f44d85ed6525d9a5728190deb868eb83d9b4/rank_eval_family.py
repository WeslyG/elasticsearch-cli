"""First rank_eval release: judged real hits and exact legacy response fields."""

import json

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES

RESPONSE_FIELDS = {
    "6.2.4": ("quality_level", "unknown_docs"),
    "6.3.2": ("quality_level", "unknown_docs"),
    "6.4.3": ("metric_score", "unrated_docs"),
    "6.5.4": ("metric_score", "unrated_docs"),
    "6.6.2": ("metric_score", "unrated_docs"),
    "6.7.2": ("metric_score", "unrated_docs"),
    "6.8.23": ("metric_score", "unrated_docs"),
    "7.0.1": ("metric_score", "unrated_docs"),
    "7.1.1": ("metric_score", "unrated_docs"),
    "7.2.1": ("metric_score", "unrated_docs"),
    "7.3.2": ("metric_score", "unrated_docs"),
    "7.4.2": ("metric_score", "unrated_docs"),
    "7.5.2": ("metric_score", "unrated_docs"),
    "7.6.2": ("metric_score", "unrated_docs"),
    "7.7.1": ("metric_score", "unrated_docs"),
    "7.8.1": ("metric_score", "unrated_docs"),
    "7.9.3": ("metric_score", "unrated_docs"),
    "7.10.2": ("metric_score", "unrated_docs"),
    "7.11.2": ("metric_score", "unrated_docs"),
    "7.12.1": ("metric_score", "unrated_docs"),
    "7.13.4": ("metric_score", "unrated_docs"),
    "7.14.2": ("metric_score", "unrated_docs"),
}
PREPARED_VERSIONS = set(RESPONSE_FIELDS)


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if version in EARLY_SEVEN_RELEASES:
            path = path.replace("/fixture/", "/_doc/")
        identifier = "rank-eval." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("rank-eval." + item for item in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed",
        "bulk",
        "POST",
        "/{index}/fixture/_bulk?refresh=true",
        ("create",),
        purpose="fixture-setup",
    )
    case("count", "count", "GET", "/{index}/_count", ("seed",), purpose="fixture-precondition")
    for meaning in ["relevant", "irrelevant"]:
        case(
            "search-" + meaning,
            "search",
            "POST",
            "/{index}/_search",
            ("count",),
            purpose="fixture-precondition",
        )
        for method in ["GET", "POST"]:
            for scope, path in [("global", "/_rank_eval"), ("index", "/{index}/_rank_eval")]:
                case(
                    meaning + "-" + method.lower() + "-" + scope,
                    "rank_eval",
                    method,
                    path,
                    ("search-" + meaning,),
                )
    if version in {"7.6.2", "7.7.1", "7.8.1", "7.9.3"}:
        for name in ["query_then_fetch", "dfs_query_then_fetch", "es_cli_unknown"]:
            case(
                "search-type." + name,
                "rank_eval",
                "POST",
                "/{index}/_rank_eval?search_type=" + name,
                ("search-irrelevant",),
                (400,) if name == "es_cli_unknown" else (200,),
            )
    case("count-after", "count", "GET", "/{index}/_count", ("count",), purpose="effect-check")
    if version == "6.2.4":
        case(
            "typed-route",
            "rank_eval",
            "POST",
            "/{index}/fixture/_rank_eval",
            ("count-after",),
            (201,),
            "route-discrepancy",
        )
        case(
            "typed-read",
            "get",
            "GET",
            "/{index}/fixture/_rank_eval",
            ("typed-route",),
            purpose="discrepancy-check",
        )
        case(
            "typed-refresh",
            "indices.refresh",
            "POST",
            "/{index}/_refresh",
            ("typed-read",),
            purpose="discrepancy-check",
        )
        case(
            "typed-count",
            "count",
            "GET",
            "/{index}/_count",
            ("typed-refresh",),
            purpose="discrepancy-check",
        )
        case(
            "typed-delete",
            "delete",
            "DELETE",
            "/{index}/fixture/_rank_eval?refresh=true",
            ("typed-count",),
            purpose="cleanup",
        )
        case(
            "typed-restored-count",
            "count",
            "GET",
            "/{index}/_count",
            ("typed-delete",),
            purpose="discrepancy-check",
        )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    case("absent", "indices.exists", "HEAD", "/{index}", ("cleanup",), (404,), "effect-check")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Rank evaluation fixture is not prepared for this exact release")
    metric_field, unrated_field = RESPONSE_FIELDS[catalog.version]
    values = {"index": prefix + "-rank"}

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        case = catalog.cases["rank-eval." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["rank-eval." + item for item in verifies],
            semantic=semantic,
            content_type=content_type,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": (
                {"properties": {"n": {"type": "integer"}}}
                if catalog.version in EARLY_SEVEN_RELEASES
                else {"fixture": {"properties": {"n": {"type": "integer"}}}}
            ),
        },
        assertions=[("index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        lines = []
        for name, n in [("relevant", 1), ("irrelevant", 2)]:
            lines.extend([{"index": {"_id": name}}, {"n": n}])
        call(
            "seed",
            ("\n".join(json.dumps(line) for line in lines) + "\n").encode(),
            content_type="application/x-ndjson",
            assertions=[
                (
                    "two actual documents indexed",
                    lambda data: data["errors"] is False and len(data["items"]) == 2,
                    True,
                )
            ],
        )
        call(
            "count",
            assertions=[("independent two-doc count", lambda data: data["count"], 2)],
            verifies=["seed"],
            semantic=True,
        )
        for meaning, n, quality in [("relevant", 1, 1.0), ("irrelevant", 2, 0.0)]:
            request = {
                "query": {
                    "bool": {"filter": [{"term": {"_index": values["index"]}}, {"term": {"n": n}}]}
                },
                "size": 1,
            }
            call(
                "search-" + meaning,
                request,
                assertions=[
                    (
                        "independent actual judged hit",
                        lambda data: [hit["_id"] for hit in data["hits"]["hits"]],
                        [meaning],
                    )
                ],
                semantic=True,
            )
            body = {
                "requests": [
                    {
                        "id": "judged",
                        "request": request,
                        "ratings": [
                            {"_index": values["index"], "_id": "relevant", "rating": 1},
                            {"_index": values["index"], "_id": "irrelevant", "rating": 0},
                        ],
                    }
                ],
                "metric": {
                    "precision": {"k": 1, "relevant_rating_threshold": 1, "ignore_unlabeled": False}
                },
            }
            for method in ["get", "post"]:
                for scope in ["global", "index"]:
                    call(
                        meaning + "-" + method + "-" + scope,
                        body,
                        assertions=[
                            (
                                "actual legacy overall quality",
                                lambda data: data[metric_field],
                                quality,
                            ),
                            (
                                "actual legacy per-query quality",
                                lambda data: data["details"]["judged"][metric_field],
                                quality,
                            ),
                            ("no failed evaluation queries", lambda data: data["failures"], {}),
                            (
                                "all hits have known ratings",
                                lambda data: data["details"]["judged"][unrated_field],
                                [],
                            ),
                        ],
                        semantic=True,
                    )
        if catalog.version in {"7.6.2", "7.7.1", "7.8.1", "7.9.3"}:
            for name in ["query_then_fetch", "dfs_query_then_fetch", "es_cli_unknown"]:
                call(
                    "search-type." + name,
                    body,
                    assertions=[
                        (
                            "unknown search type refused",
                            lambda d: "es_cli_unknown" in str(d["error"]),
                            True,
                        )
                    ]
                    if name == "es_cli_unknown"
                    else [
                        (
                            "actual judged quality with selected search type",
                            lambda d: d[metric_field],
                            0.0,
                        ),
                        ("no failed evaluation queries", lambda d: d["failures"], {}),
                    ],
                    semantic=name != "es_cli_unknown",
                )
        call(
            "count-after",
            assertions=[("ranking does not mutate documents", lambda data: data["count"], 2)],
            semantic=True,
        )
        if catalog.version == "6.2.4":
            call(
                "typed-route",
                body,
                assertions=[
                    (
                        "typed rank URI actually invokes document indexing",
                        lambda data: [data["_id"], data["_type"], data["result"]],
                        ["_rank_eval", "fixture", "created"],
                    ),
                    ("this is not a rank result", lambda data: "quality_level" not in data, True),
                ],
            )
            call(
                "typed-read",
                assertions=[
                    (
                        "rank payload was really stored as a document",
                        lambda data: data["_source"],
                        body,
                    ),
                    ("stored rank-named document exists", lambda data: data["found"], True),
                ],
                verifies=["typed-route"],
            )
            call(
                "typed-refresh",
                assertions=[
                    (
                        "visibility barrier has no failed shards",
                        lambda data: data["_shards"]["failed"],
                        0,
                    )
                ],
            )
            call(
                "typed-count",
                assertions=[
                    (
                        "misrouted request really added a third document",
                        lambda data: data["count"],
                        3,
                    )
                ],
                verifies=["typed-route"],
            )
            call(
                "typed-delete",
                assertions=[
                    ("only unexpected document deleted", lambda data: data["result"], "deleted")
                ],
            )
            call(
                "typed-restored-count",
                assertions=[
                    ("fixture restored to two original docs", lambda data: data["count"], 2)
                ],
                verifies=["typed-delete"],
            )
    finally:
        call("cleanup")
        call("absent", verifies=["cleanup"])
