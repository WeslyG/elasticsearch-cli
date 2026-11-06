"""ES6 missing typed/global methods with real owned documents and cache effects."""

import json

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES
from legacy_release_selection import LEGACY_ROUTE_RELEASES as PREPARED_VERSIONS
from legacy_type_family import HOT_PATHS


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if version in EARLY_SEVEN_RELEASES:
            if name.startswith(("synced-", "hot-", "prime-", "before-", "clear-", "after-")):
                return
            if name == "create":
                path += "?include_type_name=true"
        identifier = "legacy-route." + name
        if (
            version
            in {
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
            }
            and name == "put-no-id"
        ):
            purpose = "unsupported-method-probe"
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

    for method in ["GET", "POST"]:
        case(
            "template-" + method.lower(),
            "search_template",
            method,
            "/{index}/{doc_type}/_search/template",
            ("count",),
        )
        case(
            "mtemplate-" + method.lower(),
            "msearch_template",
            method,
            "/{index}/{doc_type}/_msearch/template",
            ("count",),
        )
    case("upgrade-before", "indices.get_upgrade", "GET", "/_upgrade", ("count",))
    case(
        "upgrade-global",
        "indices.upgrade",
        "POST",
        "/_upgrade?only_ancient_segments=true",
        ("upgrade-before",),
    )
    case(
        "upgrade-after",
        "indices.get_upgrade",
        "GET",
        "/_upgrade",
        ("upgrade-global",),
        purpose="effect-check",
    )
    case("put-no-id", "index", "PUT", "/{index}/{doc_type}", ("count",), (405,))
    case("no-auto-write", "count", "GET", "/{index}/_count", ("put-no-id",), purpose="effect-check")
    case(
        "typed-update",
        "update_by_query",
        "POST",
        "/{index}/{doc_type}/_update_by_query?refresh=true",
        ("count",),
    )
    case(
        "updated-read",
        "get",
        "GET",
        "/{index}/{doc_type}/post",
        ("typed-update",),
        purpose="effect-check",
    )
    case(
        "untouched-read",
        "get",
        "GET",
        "/{index}/{doc_type}/put",
        ("typed-update",),
        purpose="effect-check",
    )
    case(
        "typed-delete",
        "delete_by_query",
        "POST",
        "/{index}/{doc_type}/_delete_by_query?refresh=true",
        ("untouched-read", "updated-read"),
    )
    case(
        "deleted-read",
        "get",
        "GET",
        "/{index}/{doc_type}/put",
        ("typed-delete",),
        (404,),
        purpose="effect-check",
    )
    case(
        "remaining-read",
        "get",
        "GET",
        "/{index}/{doc_type}/post",
        ("typed-delete",),
        purpose="effect-check",
    )
    case(
        "remaining-count",
        "count",
        "GET",
        "/{index}/_count",
        ("typed-delete",),
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
            if catalog.version not in EARLY_SEVEN_RELEASES:
                call(
                    "synced-" + method,
                    assertions=[
                        ("synced flush no failed shards", lambda data: data["_shards"]["failed"], 0)
                    ],
                )
        for scope in ["global", "index"] if catalog.version not in EARLY_SEVEN_RELEASES else []:
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
        for number, _ in enumerate(
            HOT_PATHS if catalog.version not in EARLY_SEVEN_RELEASES else []
        ):
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

        template = {"source": '{"query":{"term":{"n":"{{value}}"}}}', "params": {"value": 11}}
        for method in ["get", "post"]:
            call(
                "template-" + method,
                template,
                assertions=[
                    (
                        "typed mustache returns actual document",
                        lambda data: [
                            [hit["_type"], hit["_id"], hit["_source"]["n"]]
                            for hit in data["hits"]["hits"]
                        ],
                        [["fixture", "post", 11]],
                    )
                ],
                semantic=True,
            )
            lines = [{}, template, {}, {**template, "params": {"value": 22}}]
            payload = ("\n".join(json.dumps(line) for line in lines) + "\n").encode()
            call(
                "mtemplate-" + method,
                payload,
                content_type="application/x-ndjson",
                assertions=[
                    (
                        "both typed mustache responses match real data",
                        lambda data: [
                            [
                                [hit["_type"], hit["_id"], hit["_source"]["n"]]
                                for hit in response["hits"]["hits"]
                            ]
                            for response in data["responses"]
                        ],
                        [[["fixture", "post", 11]], [["fixture", "put", 22]]],
                    )
                ],
                semantic=True,
            )
        native = [
            (
                "fresh native segments need no upgrade",
                lambda data: data["indices"][values["index"]]["size_to_upgrade_in_bytes"],
                0,
            )
        ]
        call("upgrade-before", assertions=native)
        call(
            "upgrade-global",
            assertions=[("no-op has no failed shards", lambda data: data["_shards"]["failed"], 0)],
        )
        call("upgrade-after", assertions=native, verifies=["upgrade-global"], semantic=True)
        call(
            "put-no-id",
            {"n": 99},
            assertions=[
                (
                    "metadata Cartesian method/path is rejected",
                    lambda data: "PUT" in data["error"] and "POST" in data["error"],
                    True,
                )
            ],
        )
        call(
            "no-auto-write",
            assertions=[
                ("rejected PUT did not auto-create a document", lambda data: data["count"], 2)
            ],
            verifies=["put-no-id"],
            semantic=True,
        )
        call(
            "typed-update",
            {"query": {"term": {"n": 11}}, "script": {"source": "ctx._source.n += 100"}},
            assertions=[
                (
                    "exactly one actual document updated",
                    lambda data: [data["updated"], data["version_conflicts"], data["failures"]],
                    [1, 0, []],
                )
            ],
        )
        call(
            "updated-read",
            assertions=[("actual updated value", lambda data: data["_source"]["n"], 111)],
            verifies=["typed-update"],
            semantic=True,
        )
        call(
            "untouched-read",
            assertions=[("other document untouched", lambda data: data["_source"]["n"], 22)],
            verifies=["typed-update"],
            semantic=True,
        )
        call(
            "typed-delete",
            {"query": {"term": {"n": 22}}},
            assertions=[
                (
                    "exactly one actual document deleted",
                    lambda data: [data["deleted"], data["version_conflicts"], data["failures"]],
                    [1, 0, []],
                )
            ],
        )
        call(
            "deleted-read",
            assertions=[("actual typed document absent", lambda data: data["found"], False)],
            verifies=["typed-delete"],
            semantic=True,
        )
        call(
            "remaining-read",
            assertions=[
                ("updated document survives delete query", lambda data: data["_source"]["n"], 111)
            ],
            verifies=["typed-delete", "upgrade-global"],
            semantic=True,
        )
        call(
            "remaining-count",
            assertions=[("one real document remains", lambda data: data["count"], 1)],
            verifies=["typed-delete"],
            semantic=True,
        )

    finally:
        call("snapshot-delete")
        call("repository-detach")
        call("cleanup")
        call("absent", verifies=["cleanup"])
