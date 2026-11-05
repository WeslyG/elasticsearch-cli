"""ES6 missing typed/global methods with real owned documents and cache effects."""

import json

from evidence_runner import OMITTED
from legacy_type_family import HOT_PATHS

PREPARED_VERSIONS = {"6.0.1"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "legacy-route." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("legacy-route." + item for item in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case("exists", "indices.exists", "HEAD", "/{index}", ("create",))
    for method in ["POST", "PUT"]:
        name = method.lower()
        case("bulk-" + name, "bulk", method, "/{index}/{doc_type}/_bulk?refresh=true", ("create",))
        case(
            "read-" + name,
            "get",
            "GET",
            "/{index}/{doc_type}/" + name,
            ("bulk-" + name,),
            purpose="effect-check",
        )
    for method in ["GET", "POST"]:
        case(
            "caps-" + method.lower(),
            "field_caps",
            method,
            "/_field_caps?fields=n",
            ("read-post", "read-put"),
        )
        case(
            "synced-" + method.lower(),
            "indices.flush_synced",
            method,
            "/_flush/synced",
            ("read-post", "read-put"),
        )
    for scope, path in [("global", "/_cache/clear"), ("index", "/{index}/_cache/clear")]:
        case(
            "prime-" + scope,
            "search",
            "POST",
            "/{index}/_search?request_cache=true",
            ("read-post", "read-put"),
            purpose="fixture-setup",
        )
        case(
            "before-" + scope,
            "indices.stats",
            "GET",
            "/{index}/_stats/request_cache",
            ("prime-" + scope,),
            purpose="fixture-precondition",
        )
        case(
            "clear-" + scope,
            "indices.clear_cache",
            "GET",
            path + "?request=true&query=false&fielddata=false",
            ("before-" + scope,),
        )
        case(
            "after-" + scope,
            "indices.stats",
            "GET",
            "/{index}/_stats/request_cache",
            ("clear-" + scope,),
            purpose="effect-check",
        )
    for number, path in enumerate(HOT_PATHS):
        case(
            "hot-" + str(number),
            "nodes.hot_threads",
            "GET",
            path + "?threads=1&snapshots=1&interval=1ms",
        )
    case(
        "repository",
        "snapshot.create_repository",
        "PUT",
        "/_snapshot/{repo}",
        ("create",),
        purpose="fixture-setup",
    )
    case(
        "snapshot",
        "snapshot.create",
        "PUT",
        "/_snapshot/{repo}/legacy-methods?wait_for_completion=true",
        ("repository", "read-post", "read-put"),
        purpose="fixture-setup",
    )
    case(
        "cat-global",
        "cat.snapshots",
        "GET",
        "/_cat/snapshots?repository={repo}&format=json&h=id,status,indices",
        ("snapshot",),
    )
    case(
        "count",
        "count",
        "GET",
        "/{index}/_count",
        ("read-post", "read-put"),
        purpose="effect-check",
    )
    case(
        "snapshot-delete",
        "snapshot.delete",
        "DELETE",
        "/_snapshot/{repo}/legacy-methods",
        expected=(200, 404),
        purpose="cleanup",
    )
    case(
        "repository-detach",
        "snapshot.delete_repository",
        "DELETE",
        "/_snapshot/{repo}",
        expected=(200, 404),
        purpose="cleanup",
    )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    case("absent", "indices.exists", "HEAD", "/{index}", ("cleanup",), (404,), "effect-check")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Legacy route fixture is not prepared for this exact release")
    values = {
        "index": prefix + "-legacy-methods",
        "doc_type": "fixture",
        "node": "_local",
        "repo": prefix + "-legacy-methods",
    }

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        case = catalog.cases["legacy-route." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["legacy-route." + item for item in verifies],
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
        assertions=[("owned index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        call("exists")
        for name, number in [("post", 11), ("put", 22)]:
            ndjson = json.dumps({"index": {"_id": name}}) + "\n" + json.dumps({"n": number}) + "\n"
            call(
                "bulk-" + name,
                ndjson.encode(),
                content_type="application/x-ndjson",
                assertions=[
                    ("bulk no item errors", lambda data: data["errors"], False),
                    (
                        "exact typed write item",
                        lambda data, name=name: [item["index"]["_id"] for item in data["items"]],
                        [name],
                    ),
                ],
            )
            call(
                "read-" + name,
                assertions=[
                    (
                        "actual typed document",
                        lambda data: [data["_type"], data["_source"]["n"]],
                        ["fixture", number],
                    )
                ],
                verifies=["bulk-" + name],
                semantic=True,
            )
        for method in ["get", "post"]:
            call(
                "caps-" + method,
                assertions=[
                    (
                        "global integer field capabilities",
                        lambda data: (
                            data["fields"]["n"]["integer"]["searchable"] is True
                            and data["fields"]["n"]["integer"]["aggregatable"] is True
                        ),
                        True,
                    )
                ],
                semantic=True,
            )
            call(
                "synced-" + method,
                assertions=[
                    ("synced flush no failed shards", lambda data: data["_shards"]["failed"], 0)
                ],
            )
        for scope in ["global", "index"]:
            call(
                "prime-" + scope,
                {"size": 0, "aggs": {"owned": {"sum": {"field": "n"}}}},
                assertions=[
                    (
                        "aggregation actually sees both values",
                        lambda data: data["aggregations"]["owned"]["value"],
                        33.0,
                    )
                ],
            )
            call(
                "before-" + scope,
                assertions=[
                    (
                        "actual request cache allocation",
                        lambda data: (
                            data["indices"][values["index"]]["primaries"]["request_cache"][
                                "memory_size_in_bytes"
                            ]
                            > 0
                        ),
                        True,
                    )
                ],
            )
            call(
                "clear-" + scope,
                assertions=[
                    ("cache clear no failed shards", lambda data: data["_shards"]["failed"], 0)
                ],
            )
            call(
                "after-" + scope,
                assertions=[
                    (
                        "request cache memory really released",
                        lambda data: data["indices"][values["index"]]["primaries"]["request_cache"][
                            "memory_size_in_bytes"
                        ],
                        0,
                    )
                ],
                verifies=["clear-" + scope],
                semantic=True,
            )
        for number, _ in enumerate(HOT_PATHS):
            call(
                "hot-" + str(number),
                assertions=[
                    (
                        "actual owned node hot-thread text",
                        lambda data: (
                            isinstance(data, str)
                            and "Hot threads at" in data
                            and "es-cli-anchor" in data
                        ),
                        True,
                    )
                ],
                semantic=True,
            )
        call(
            "repository",
            {"type": "fs", "settings": {"location": "/tmp/es-snapshots/" + values["repo"]}},
            assertions=[("repository acknowledged", lambda data: data["acknowledged"], True)],
        )
        call(
            "snapshot",
            {"indices": values["index"], "include_global_state": False},
            assertions=[
                ("real snapshot successful", lambda data: data["snapshot"]["state"], "SUCCESS")
            ],
        )
        call(
            "cat-global",
            assertions=[
                (
                    "global cat uses explicit repository query",
                    lambda data: [[row["id"], row["status"], int(row["indices"])] for row in data],
                    [["legacy-methods", "SUCCESS", 1]],
                )
            ],
            verifies=["snapshot"],
            semantic=True,
        )
        call(
            "count",
            assertions=[
                ("all read/admin methods preserve real documents", lambda data: data["count"], 2)
            ],
            semantic=True,
        )
    finally:
        call("snapshot-delete")
        call("repository-detach")
        call("cleanup")
        call("absent", verifies=["cleanup"])
