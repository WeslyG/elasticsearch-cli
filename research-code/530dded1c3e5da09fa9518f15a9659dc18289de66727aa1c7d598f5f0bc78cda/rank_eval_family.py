"""First rank_eval release: judged real hits and exact legacy response fields."""

import json

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"6.2.4"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
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
    case("count-after", "count", "GET", "/{index}/_count", ("count",), purpose="effect-check")
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    case("absent", "indices.exists", "HEAD", "/{index}", ("cleanup",), (404,), "effect-check")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Rank evaluation fixture is not prepared for this exact release")
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
            "mappings": {"fixture": {"properties": {"n": {"type": "integer"}}}},
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
                                lambda data: data["quality_level"],
                                quality,
                            ),
                            (
                                "actual legacy per-query quality",
                                lambda data: data["details"]["judged"]["quality_level"],
                                quality,
                            ),
                            ("no failed evaluation queries", lambda data: data["failures"], {}),
                            (
                                "all hits have known ratings",
                                lambda data: data["details"]["judged"]["unknown_docs"],
                                [],
                            ),
                        ],
                        semantic=True,
                    )
        call(
            "count-after",
            assertions=[("ranking does not mutate documents", lambda data: data["count"], 2)],
            semantic=True,
        )
    finally:
        call("cleanup")
        call("absent", verifies=["cleanup"])
