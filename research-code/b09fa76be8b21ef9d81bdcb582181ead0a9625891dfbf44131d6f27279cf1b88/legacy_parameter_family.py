"""Exact ES6 search wire semantics on twenty real custom-type documents."""

from urllib.parse import urlencode

from evidence_runner import OMITTED
from legacy_release_selection import PREPARED_LEGACY_RELEASES as PREPARED_VERSIONS


def search_checks(version=None):
    def numbers(data):
        return [hit["_source"]["n"] for hit in data["hits"]["hits"]]

    def total(data):
        return data["hits"]["total"]

    def hits(data):
        return data["hits"]["hits"]

    def error(data):
        return isinstance(data.get("error", {}).get("type"), str)

    def fields(data):
        return [sorted(hit["_source"]) for hit in hits(data)]

    baseline = {"query": {"match_all": {}}, "sort": [{"n": "asc"}]}
    specs = []

    def add(name, query="", body=None, checks=(), status=200, unsupported=()):
        specs.append((name, query, baseline if body is None else body, checks, status, unsupported))

    add(
        "default",
        checks=[
            ("legacy total is exact integer", total, 20),
            ("default window", numbers, list(range(10))),
        ],
    )
    add("total-true", "?track_total_hits=true", checks=[("explicit true legacy total", total, 20)])
    add(
        "total-false",
        "?track_total_hits=false",
        checks=[("disabled tracking uses negative sentinel", total, -1)],
    )
    add(
        "total-integer-rejected",
        "?track_total_hits=10",
        checks=[("numeric threshold is not ES6 boolean", error, True)],
        status=400,
    )
    add(
        "total-zero-rejected",
        "?track_total_hits=0",
        checks=[("zero is not false boolean", error, True)],
        status=400,
    )
    if version == "6.6.2":
        for value in ["true", "false", "garbage"]:
            add(
                "rest-integer-" + value,
                "?rest_total_hits_as_int=" + value,
                checks=[
                    ("legacy total stays integer20 even with formatting flag", total, 20),
                    ("real result window preserved", numbers, list(range(10))),
                ],
            )
    else:
        add(
            "rest-integer-unsupported",
            "?rest_total_hits_as_int=true",
            checks=[("modern formatting flag unrecognized", error, True)],
            status=400,
            unsupported=("rest_total_hits_as_int",),
        )
    add(
        "seq-unsupported",
        "?seq_no_primary_term=true",
        checks=[("modern metadata flag unrecognized", error, True)],
        status=400,
        unsupported=("seq_no_primary_term",),
    )
    add("window", "?from=5&size=3", checks=[("actual window", numbers, [5, 6, 7])])
    add("size-zero", "?size=0", checks=[("empty window", hits, []), ("total preserved", total, 20)])
    for name, query in [("size-sentinel", "?size=-1"), ("from-sentinel", "?from=-1")]:
        add(name, query, checks=[("minus-one preserves default", numbers, list(range(10)))])
        add(
            name + "-body",
            query,
            {**baseline, "from": 5, "size": 3},
            [("minus-one preserves body window", numbers, [5, 6, 7])],
        )
    add(
        "url-overrides-body",
        "?from=1&size=2",
        {**baseline, "from": 5, "size": 3},
        [("positive URL window takes precedence", numbers, [1, 2])],
    )
    add("bad-from", "?from=-2", checks=[("negative from rejected", error, True)], status=400)
    add("bad-size", "?size=-2", checks=[("negative size rejected", error, True)], status=400)
    add(
        "source-false",
        "?_source=false",
        checks=[
            (
                "no source on any actual hit",
                lambda d: len(hits(d)) == 10 and all("_source" not in hit for hit in hits(d)),
                True,
            )
        ],
    )
    add(
        "source-true",
        "?_source=true",
        checks=[("source explicitly enabled", fields, [["category", "n", "stored"]] * 10)],
    )
    add(
        "source-includes",
        "?_source_include=n,category",
        checks=[("actual included fields", fields, [["category", "n"]] * 10)],
    )
    add(
        "source-interaction",
        "?_source_include=n,category&_source_exclude=category",
        checks=[("excludes apply to included set", fields, [["n"]] * 10)],
    )
    if version == "6.6.2":
        add(
            "source-plural",
            "?_source_includes=n,category&_source_excludes=category",
            checks=[("plural filters return only n", fields, [["n"]] * 10)],
        )
        add(
            "source-include-alias-precedence",
            "?_source_includes=category&_source_include=n",
            checks=[("legacy include alias overrides plural", fields, [["n"]] * 10)],
        )
        add(
            "source-exclude-alias-precedence",
            "?_source_excludes=n&_source_exclude=category",
            checks=[("legacy exclude alias overrides plural", fields, [["n", "stored"]] * 10)],
        )
    add(
        "stored-only",
        "?stored_fields=stored",
        checks=[
            (
                "stored fields omit source",
                lambda d: (
                    len(hits(d)) == 10
                    and all(
                        "_source" not in hit and hit["fields"]["stored"] == ["value-" + hit["_id"]]
                        for hit in hits(d)
                    )
                ),
                True,
            )
        ],
    )
    add(
        "stored-source",
        "?stored_fields=stored&_source=true",
        checks=[
            (
                "stored/source values agree",
                lambda d: (
                    len(hits(d)) == 10
                    and all(
                        hit["fields"]["stored"] == [hit["_source"]["stored"]] for hit in hits(d)
                    )
                ),
                True,
            )
        ],
    )
    add(
        "version-true",
        "?version=true",
        checks=[("real first versions", lambda d: [hit["_version"] for hit in hits(d)], [1] * 10)],
    )
    add(
        "version-false",
        "?version=false",
        checks=[
            (
                "version omitted",
                lambda d: len(hits(d)) == 10 and all("_version" not in hit for hit in hits(d)),
                True,
            )
        ],
    )
    aggregation = {**baseline, "size": 0, "aggs": {"total_n": {"sum": {"field": "n"}}}}
    for flag in [True, False]:
        key = "sum#total_n" if flag else "total_n"
        add(
            "typed-" + str(flag).lower(),
            "?typed_keys=" + str(flag).lower(),
            aggregation,
            [
                ("actual aggregation key", lambda d: sorted(d["aggregations"]), [key]),
                (
                    "actual sum of twenty values",
                    lambda d, key=key: d["aggregations"][key]["value"],
                    190.0,
                ),
            ],
        )
    add(
        "terminate-one",
        "?terminate_after=1&size=20",
        checks=[
            (
                "one actual hit and early stop",
                lambda d: len(hits(d)) == 1 and d["terminated_early"] is True,
                True,
            )
        ],
    )
    add(
        "terminate-zero",
        "?terminate_after=0&size=20",
        checks=[("zero leaves all results", numbers, list(range(20)))],
    )
    add(
        "query-string",
        "?" + urlencode({"q": "n:[5 TO 7]"}),
        checks=[("query string overrides match-all", numbers, [5, 6, 7])],
    )
    add(
        "profile-true",
        body={**baseline, "profile": True},
        checks=[
            (
                "actual shard query profile",
                lambda d: (
                    len(d["profile"]["shards"]) == 1 and bool(d["profile"]["shards"][0]["searches"])
                ),
                True,
            )
        ],
    )
    add(
        "profile-false",
        body={**baseline, "profile": False},
        checks=[("profile absent", lambda d: "profile" not in d, True)],
    )
    return specs


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(
        name, api, method, path, deps=(), expected=(200,), unsupported=(), purpose="api-contract"
    ):
        identifier = "legacy-parameter." + name
        add(
            identifier,
            api,
            method,
            path,
            expected=expected,
            unsupported=unsupported,
            purpose=purpose,
        )
        graph[identifier] = tuple("legacy-parameter." + item for item in deps)

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
    for name, query, _, _, status, unsupported in search_checks(version):
        case(name, "search", "POST", "/{index}/_search" + query, ("count",), (status,), unsupported)
    case("count-after", "count", "GET", "/{index}/_count", ("count",), purpose="effect-check")
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    case(
        "absent", "indices.exists", "HEAD", "/{index}", ("cleanup",), (404,), purpose="effect-check"
    )
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Legacy parameter fixture is not prepared for this exact release")
    import json

    values = {"index": prefix + "-legacy-parameters"}

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        case = catalog.cases["legacy-parameter." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["legacy-parameter." + item for item in verifies],
            semantic=semantic,
            content_type=content_type,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "fixture": {
                    "properties": {
                        "n": {"type": "integer"},
                        "category": {"type": "keyword"},
                        "stored": {"type": "keyword", "store": True},
                    }
                }
            },
        },
        assertions=[("index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        lines = []
        for number in range(20):
            lines.extend(
                [
                    json.dumps({"index": {"_id": str(number)}}),
                    json.dumps(
                        {
                            "n": number,
                            "category": "even" if number % 2 == 0 else "odd",
                            "stored": "value-" + str(number),
                        }
                    ),
                ]
            )
        call(
            "seed",
            ("\n".join(lines) + "\n").encode(),
            content_type="application/x-ndjson",
            assertions=[
                (
                    "all twenty typed items succeed",
                    lambda data: data["errors"] is False and len(data["items"]) == 20,
                    True,
                )
            ],
        )
        call(
            "count",
            assertions=[("twenty real documents", lambda data: data["count"], 20)],
            verifies=["seed"],
            semantic=True,
        )
        for name, _, body, checks, status, _ in search_checks(catalog.version):
            call(name, body, assertions=checks, semantic=status == 200)
        call(
            "count-after",
            assertions=[("reads preserve all twenty documents", lambda data: data["count"], 20)],
            semantic=True,
        )
    finally:
        call("cleanup")
        call("absent", verifies=["cleanup"])
