"""Actual ES7 custom-type routes and mapping aliases, not _doc-shaped guesses."""

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES

PREPARED_VERSIONS = {
    "7.0.1",
    "7.1.1",
    "7.2.1",
    "7.3.2",
    "7.4.2",
    "7.5.2",
    "7.6.2",
    "7.7.1",
    "7.8.1",
    "7.17.29",
    "7.9.3",
    "7.10.2",
    "7.11.2",
    "7.12.1",
    "7.13.4",
    "7.14.2",
    "7.15.2",
    "7.16.3",
}

MAPPING_PATHS = [
    ("/{index}/{doc_type}/_mapping", True),
    ("/{index}/_mapping/{doc_type}", True),
    ("/{index}/{doc_type}/_mappings", True),
    ("/{index}/_mappings/{doc_type}", True),
    ("/_mappings/{doc_type}", True),
    ("/{index}/_mappings", False),
    ("/_mapping/{doc_type}", True),
]
HOT_PATHS = [
    "/_cluster/nodes/hotthreads",
    "/_cluster/nodes/{node}/hotthreads",
    "/_nodes/hotthreads",
    "/_nodes/{node}/hotthreads",
    "/_cluster/nodes/hot_threads",
    "/_cluster/nodes/{node}/hot_threads",
]


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "legacy-type." + name
        if (
            version in EARLY_SEVEN_RELEASES
            and api == "indices.put_mapping"
            and path.startswith("/_mapping")
            and name != "global-default-refused"
        ):
            path += ("&" if "?" in path else "?") + "index={index}"
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("legacy-type." + item for item in deps)

    case(
        "fixture-absent" if version in EARLY_SEVEN_RELEASES else "no-tasks",
        "indices.exists",
        "HEAD",
        "/{index}" if version in EARLY_SEVEN_RELEASES else "/.tasks",
        expected=(404,),
        purpose="fixture-precondition",
    )
    case(
        "create",
        "indices.create",
        "PUT",
        "/{index}?include_type_name=true",
        ("fixture-absent" if version in EARLY_SEVEN_RELEASES else "no-tasks",),
        purpose="fixture-setup",
    )
    if version in EARLY_SEVEN_RELEASES:
        case(
            "task-namespace-present",
            "indices.exists",
            "HEAD",
            "/.tasks",
            purpose="fixture-precondition",
        )
        case(
            "global-default-refused",
            "indices.put_mapping",
            "PUT",
            "/_mapping/{doc_type}?include_type_name=true",
            ("seed", "task-namespace-present"),
            (400,),
            "multi-index-type-conflict",
        )
        case(
            "global-refusal-own-mapping",
            "indices.get_mapping",
            "GET",
            "/{index}/_mapping/{doc_type}?include_type_name=true",
            ("global-default-refused",),
            purpose="effect-check",
        )
        case(
            "global-refusal-task-mapping",
            "indices.get_mapping",
            "GET",
            "/.tasks/_mapping/task?include_type_name=true",
            ("global-default-refused",),
            purpose="effect-check",
        )
    if version in {"7.12.1", "7.13.4", "7.14.2", "7.15.2", "7.16.3"}:
        case(
            "system-task-schema",
            "indices.get_mapping",
            "GET",
            "/.tasks/_mapping/task?include_type_name=true",
            ("task-namespace-present",),
            purpose="effect-check",
        )
    case(
        "seed",
        "index",
        "PUT",
        "/{index}/{doc_type}/seed?refresh=true",
        ("create",),
        (201,),
        "fixture-setup",
    )
    case(
        "index-exists",
        "indices.exists",
        "HEAD",
        "/{index}",
        ("seed",),
        purpose="fixture-precondition",
    )
    case(
        "type-exists",
        "indices.exists_type",
        "HEAD",
        "/{index}/_mapping/{doc_type}",
        ("seed",),
        purpose="fixture-precondition",
    )
    case("get", "get", "GET", "/{index}/{doc_type}/seed", ("seed",))
    case("source", "get_source", "GET", "/{index}/{doc_type}/seed/_source", ("seed",))
    case("exists", "exists", "HEAD", "/{index}/{doc_type}/seed", ("seed",))
    case("exists-source", "exists_source", "HEAD", "/{index}/{doc_type}/seed/_source", ("seed",))
    for method in ["GET", "POST"]:
        for name, api, suffix in [
            ("count", "count", "/_count"),
            ("search", "search", "/_search"),
            ("validate", "indices.validate_query", "/_validate/query"),
            ("mget", "mget", "/_mget"),
            ("msearch", "msearch", "/_msearch"),
            ("mtermvectors", "mtermvectors", "/_mtermvectors"),
        ]:
            case(
                name + "-" + method.lower(), api, method, "/{index}/{doc_type}" + suffix, ("seed",)
            )
        case(
            "explain-" + method.lower(),
            "explain",
            method,
            "/{index}/{doc_type}/seed/_explain",
            ("seed",),
        )
        case(
            "term-stored-" + method.lower(),
            "termvectors",
            method,
            "/{index}/{doc_type}/seed/_termvectors",
            ("seed",),
        )
        case(
            "term-artificial-" + method.lower(),
            "termvectors",
            method,
            "/{index}/{doc_type}/_termvectors",
            ("seed",),
        )
    for method in ["PUT", "POST"]:
        case(
            "bulk-" + method.lower(),
            "bulk",
            method,
            "/{index}/{doc_type}/_bulk?refresh=true",
            ("seed",),
        )
        case(
            "bulk-read-" + method.lower(),
            "get",
            "GET",
            "/{index}/{doc_type}/{id}",
            ("bulk-" + method.lower(),),
            purpose="effect-check",
        )
        case(
            "create-" + method.lower(),
            "create",
            method,
            "/{index}/{doc_type}/{id}/_create?refresh=true",
            ("seed",),
            (201,),
        )
        case(
            "create-read-" + method.lower(),
            "get",
            "GET",
            "/{index}/{doc_type}/{id}",
            ("create-" + method.lower(),),
            purpose="effect-check",
        )
        case(
            "index-" + method.lower(),
            "index",
            method,
            "/{index}/{doc_type}/{id}?refresh=true",
            ("seed",),
            (201,),
        )
        case(
            "index-read-" + method.lower(),
            "get",
            "GET",
            "/{index}/{doc_type}/{id}",
            ("index-" + method.lower(),),
            purpose="effect-check",
        )
    case("index-auto", "index", "POST", "/{index}/{doc_type}?refresh=true", ("seed",), (201,))
    case(
        "auto-read",
        "get",
        "GET",
        "/{index}/{doc_type}/{autoid}",
        ("index-auto",),
        purpose="effect-check",
    )
    for name, path in [
        ("mapping-global", "/_mapping/{doc_type}"),
        ("mapping-index", "/{index}/_mapping/{doc_type}"),
        ("field-global", "/_mapping/{doc_type}/field/n"),
        ("field-index", "/{index}/_mapping/{doc_type}/field/n"),
    ]:
        api = "indices.get_field_mapping" if name.startswith("field") else "indices.get_mapping"
        case(name, api, "GET", path + "?include_type_name=true", ("seed",))
    case(
        "mapping-default-get-rejected",
        "indices.get_mapping",
        "GET",
        "/{index}/_mapping/{doc_type}",
        ("seed",),
        (400,),
    )
    case(
        "mapping-default-put-rejected",
        "indices.put_mapping",
        "PUT",
        "/{index}/_mapping/{doc_type}",
        ("seed",),
        (400,),
    )
    case(
        "mapping-rejection-effect",
        "indices.get_mapping",
        "GET",
        "/{index}/_mapping/{doc_type}?include_type_name=true",
        ("mapping-default-put-rejected",),
        purpose="effect-check",
    )
    for number, (path, typed) in enumerate(MAPPING_PATHS):
        for method in ["PUT", "POST"]:
            name = "mapping-" + str(number) + "-" + method.lower()
            case(
                name,
                "indices.put_mapping",
                method,
                path + "?include_type_name=" + ("true" if typed else "false"),
                ("seed",),
            )
            case(
                name + "-read",
                "indices.get_mapping",
                "GET",
                "/{index}/_mapping/{doc_type}?include_type_name=true",
                (name,),
                purpose="effect-check",
            )
    for method in ["GET", "POST"]:
        case(
            "synced-flush-" + method.lower(),
            "indices.flush_synced",
            method,
            "/_flush/synced",
            ("seed",),
            (200, 409) if version in EARLY_SEVEN_RELEASES else (200,),
        )
    if version in EARLY_SEVEN_RELEASES:
        case(
            "flush-before-stable-synced",
            "indices.flush",
            "POST",
            "/_flush",
            ("synced-flush-get", "synced-flush-post"),
            purpose="fixture-precondition",
        )
        for method in ["GET", "POST"]:
            case(
                "stable-synced-flush-" + method.lower(),
                "indices.flush_synced",
                method,
                "/_flush/synced",
                ("flush-before-stable-synced",),
            )
    case("upgrade-before", "indices.get_upgrade", "GET", "/_upgrade", ("seed",))
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
    case(
        "upgrade-data",
        "get",
        "GET",
        "/{index}/{doc_type}/seed",
        ("upgrade-after",),
        purpose="effect-check",
    )
    for number, path in enumerate(HOT_PATHS):
        case(
            "hot-" + str(number),
            "nodes.hot_threads",
            "GET",
            path + "?interval=10ms&snapshots=1&threads=1&ignore_idle_threads=false",
            ("seed",),
        )
    case("update", "update", "POST", "/{index}/{doc_type}/seed/_update?refresh=true", ("seed",))
    case(
        "update-read", "get", "GET", "/{index}/{doc_type}/seed", ("update",), purpose="effect-check"
    )
    case("delete", "delete", "DELETE", "/{index}/{doc_type}/seed?refresh=true", ("update-read",))
    case(
        "deleted-absent",
        "get",
        "GET",
        "/{index}/{doc_type}/seed",
        ("delete",),
        (404,),
        "effect-check",
    )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    case("cleanup-read", "indices.exists", "HEAD", "/{index}", ("cleanup",), (404,), "effect-check")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Legacy type fixture not prepared for this exact release")
    values = {
        "index": prefix + "-legacy-types",
        "doc_type": "fixture",
        "id": "seed",
        "autoid": "not-created",
        "node": "_local",
    }

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        case = catalog.cases["legacy-type." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            content_type=content_type,
            verifies=["legacy-type." + item for item in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def n_value(data):
        return data["_source"]["n"]

    def mappings(data):
        return data[values["index"]]["mappings"]["fixture"]["properties"]

    def term_frequency(data):
        return data["term_vectors"]["text"]["terms"]["alpha"]["term_freq"]

    def needs_flag(data):
        return (
            data["error"]["type"] == "illegal_argument_exception"
            and "include_type_name" in data["error"]["reason"]
        )

    call("fixture-absent" if catalog.version in EARLY_SEVEN_RELEASES else "no-tasks")
    if catalog.version in EARLY_SEVEN_RELEASES:
        call("task-namespace-present")
        if catalog.version in {"7.12.1", "7.13.4", "7.14.2", "7.15.2", "7.16.3"}:
            call(
                "system-task-schema",
                assertions=[
                    (
                        "system mapping version string",
                        lambda d: d[".tasks"]["mappings"]["task"]["_meta"]["version"],
                        catalog.version,
                    ),
                    (
                        "strict task mapping",
                        lambda d: d[".tasks"]["mappings"]["task"]["dynamic"],
                        "strict",
                    ),
                    (
                        "completed field is boolean",
                        lambda d: d[".tasks"]["mappings"]["task"]["properties"]["completed"][
                            "type"
                        ],
                        "boolean",
                    ),
                ],
                semantic=True,
            )

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "fixture": {
                    "properties": {
                        "n": {"type": "integer"},
                        "text": {"type": "text", "term_vector": "yes"},
                    }
                }
            },
        },
        assertions=[("typed index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        call("seed", {"n": 11, "text": "alpha beta"})
        call("index-exists")
        call("type-exists")
        call("get", assertions=[("real typed document", n_value, 11)], semantic=True)
        call(
            "source", assertions=[("typed source value", lambda data: data["n"], 11)], semantic=True
        )
        call("exists")
        call("exists-source")
        query = {"query": {"term": {"n": 11}}}
        for method in ["get", "post"]:
            call(
                "count-" + method,
                query,
                assertions=[("typed count matches fixture", lambda data: data["count"], 1)],
                semantic=True,
            )
            call(
                "search-" + method,
                query,
                assertions=[
                    (
                        "typed search matches fixture",
                        lambda data: [hit["_source"]["n"] for hit in data["hits"]["hits"]],
                        [11],
                    )
                ],
                semantic=True,
            )
            call(
                "validate-" + method,
                query,
                assertions=[("typed query valid", lambda data: data["valid"], True)],
                semantic=True,
            )
            call(
                "explain-" + method,
                query,
                assertions=[
                    ("typed document matches explanation", lambda data: data["matched"], True)
                ],
                semantic=True,
            )
            call(
                "mget-" + method,
                {"ids": ["seed"]},
                assertions=[
                    ("typed multi-get value", lambda data: data["docs"][0]["_source"]["n"], 11)
                ],
                semantic=True,
            )
            call(
                "msearch-" + method,
                b"{}\n" + b'{"query":{"term":{"n":11}}}\n',
                assertions=[
                    (
                        "typed multi-search result",
                        lambda data: [
                            hit["_source"]["n"] for hit in data["responses"][0]["hits"]["hits"]
                        ],
                        [11],
                    )
                ],
                content_type="application/x-ndjson",
                semantic=True,
            )
            call(
                "mtermvectors-" + method,
                {"docs": [{"_id": "seed", "fields": ["text"]}]},
                assertions=[
                    (
                        "typed multi-termvector frequency",
                        lambda data: term_frequency(data["docs"][0]),
                        1,
                    )
                ],
                semantic=True,
            )
            call(
                "term-stored-" + method,
                {"fields": ["text"]},
                assertions=[("typed stored term frequency", term_frequency, 1)],
                semantic=True,
            )
            call(
                "term-artificial-" + method,
                {"doc": {"text": "alpha beta"}, "fields": ["text"]},
                assertions=[("typed artificial term frequency", term_frequency, 1)],
                semantic=True,
            )
        for method in ["post", "put"]:
            values["id"] = "bulk-" + method
            payload = ('{"index":{"_id":"' + values["id"] + '"}}\n{"n":22}\n').encode()
            call(
                "bulk-" + method,
                payload,
                assertions=[
                    ("typed bulk no partial errors", lambda data: data["errors"], False),
                    (
                        "typed bulk item created",
                        lambda data: data["items"][0]["index"]["status"],
                        201,
                    ),
                ],
                content_type="application/x-ndjson",
            )
            call(
                "bulk-read-" + method,
                assertions=[("typed bulk actual value", n_value, 22)],
                verifies=["bulk-" + method],
                semantic=True,
            )
        for method in ["put", "post"]:
            values["id"] = "create-" + method
            call("create-" + method, {"n": 31})
            call(
                "create-read-" + method,
                assertions=[("typed create actual value", n_value, 31)],
                verifies=["create-" + method],
                semantic=True,
            )
            values["id"] = "index-" + method
            call("index-" + method, {"n": 41})
            call(
                "index-read-" + method,
                assertions=[("typed index actual value", n_value, 41)],
                verifies=["index-" + method],
                semantic=True,
            )
        generated = call(
            "index-auto",
            {"n": 43},
            assertions=[
                (
                    "typed auto-ID returned",
                    lambda data: isinstance(data.get("_id"), str) and bool(data["_id"]),
                    True,
                )
            ],
        )
        if generated.state == "passed":
            values["autoid"] = generated.data["_id"]
        call(
            "auto-read",
            assertions=[("typed auto-ID value", n_value, 43)],
            verifies=["index-auto"],
            semantic=True,
        )
        for name in ["mapping-global", "mapping-index"]:
            call(
                name,
                assertions=[
                    (
                        "actual custom mapping type retained",
                        lambda data: mappings(data)["n"]["type"],
                        "integer",
                    )
                ],
                semantic=True,
            )
        for name in ["field-global", "field-index"]:
            call(
                name,
                assertions=[
                    (
                        "actual typed field mapping",
                        lambda data: data[values["index"]]["mappings"]["fixture"]["n"]["mapping"][
                            "n"
                        ]["type"],
                        "integer",
                    )
                ],
                semantic=True,
            )
        call(
            "mapping-default-get-rejected",
            assertions=[("typed GET needs explicit include_type_name", needs_flag, True)],
        )
        call(
            "mapping-default-put-rejected",
            {"properties": {"forbidden_by_default": {"type": "keyword"}}},
            assertions=[("typed PUT needs explicit include_type_name", needs_flag, True)],
        )
        call(
            "mapping-rejection-effect",
            assertions=[
                (
                    "rejected mapping field absent",
                    lambda data: "forbidden_by_default" not in mappings(data),
                    True,
                )
            ],
            verifies=["mapping-default-put-rejected"],
            semantic=True,
        )
        if catalog.version in EARLY_SEVEN_RELEASES:
            call(
                "global-default-refused",
                {"properties": {"global_probe": {"type": "keyword"}}},
                assertions=[
                    (
                        "native global type conflict identifies task index",
                        lambda d: ".tasks" in str(d["error"]) and "type" in str(d["error"]),
                        True,
                    )
                ],
            )
            call(
                "global-refusal-own-mapping",
                assertions=[
                    (
                        "refused global mapping did not alter fixture",
                        lambda d: "global_probe" in mappings(d),
                        False,
                    )
                ],
                verifies=["global-default-refused"],
                semantic=True,
            )
            call(
                "global-refusal-task-mapping",
                assertions=[
                    (
                        "refused global mapping did not alter task properties",
                        lambda d: "global_probe" in d[".tasks"]["mappings"]["task"]["properties"],
                        False,
                    )
                ],
                verifies=["global-default-refused"],
                semantic=True,
            )
        for number, _ in enumerate(MAPPING_PATHS):
            for method in ["put", "post"]:
                name = "mapping-" + str(number) + "-" + method
                field = "field_" + str(number) + "_" + method
                call(
                    name,
                    {"properties": {field: {"type": "keyword"}}},
                    assertions=[("mapping acknowledged", lambda data: data["acknowledged"], True)],
                )
                call(
                    name + "-read",
                    assertions=[
                        (
                            "actual new mapping field",
                            lambda data, field=field: mappings(data)[field]["type"],
                            "keyword",
                        ),
                        (
                            "existing custom type data retained",
                            lambda data: mappings(data)["n"]["type"],
                            "integer",
                        ),
                    ],
                    verifies=[name],
                    semantic=True,
                )
        for method in ["get", "post"]:
            call(
                "synced-flush-" + method,
                assertions=[
                    (
                        "owned index primary synced successfully",
                        lambda data: (
                            data[values["index"]]["successful"] == 1
                            and data[values["index"]]["failed"] == 0
                        ),
                        True,
                    ),
                    (
                        "root counts equal per-index shard counts",
                        lambda data: all(
                            data["_shards"][key]
                            == sum(
                                result[key] for name, result in data.items() if name != "_shards"
                            )
                            for key in ["total", "successful", "failed"]
                        ),
                        True,
                    ),
                ]
                if catalog.version in EARLY_SEVEN_RELEASES
                else [
                    (
                        "global synced flush no failed shards",
                        lambda data: data["_shards"]["failed"],
                        0,
                    )
                ],
            )
        if catalog.version in EARLY_SEVEN_RELEASES:
            call(
                "flush-before-stable-synced",
                assertions=[
                    (
                        "explicit global flush completes on all shards",
                        lambda data: data["_shards"]["failed"],
                        0,
                    )
                ],
            )
            for method in ["get", "post"]:
                call(
                    "stable-synced-flush-" + method,
                    assertions=[
                        (
                            "stable global sync has no failed shards",
                            lambda data: data["_shards"]["failed"],
                            0,
                        ),
                        (
                            "same owned index synced",
                            lambda data: data[values["index"]]["successful"],
                            1,
                        ),
                    ],
                )
        native = [
            (
                "fresh native segments need no physical upgrade",
                lambda data: data["indices"][values["index"]]["size_to_upgrade_in_bytes"],
                0,
            )
        ]
        call("upgrade-before", assertions=native)
        call(
            "upgrade-global",
            assertions=[
                (
                    "global native-segment no-op has no failed shards",
                    lambda data: data["_shards"]["failed"],
                    0,
                )
            ],
        )
        call("upgrade-after", assertions=native, verifies=["upgrade-global"], semantic=True)
        call(
            "upgrade-data",
            assertions=[("native no-op preserves typed data", n_value, 11)],
            verifies=["upgrade-global", "synced-flush-get", "synced-flush-post"]
            + (
                ["stable-synced-flush-get", "stable-synced-flush-post"]
                if catalog.version in EARLY_SEVEN_RELEASES
                else []
            ),
            semantic=True,
        )
        for number, _ in enumerate(HOT_PATHS):
            call(
                "hot-" + str(number),
                assertions=[
                    (
                        "actual hot-thread text",
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
            "update",
            {"doc": {"n": 12}},
            assertions=[("typed update applied", lambda data: data["result"], "updated")],
        )
        call(
            "update-read",
            assertions=[("typed update readback", n_value, 12)],
            verifies=["update"],
            semantic=True,
        )
        call(
            "delete",
            assertions=[("typed document deleted", lambda data: data["result"], "deleted")],
        )
        call("deleted-absent", verifies=["delete"])
    finally:
        call("cleanup")
        call("cleanup-read", verifies=["cleanup"])
