"""Typed document contracts and version-based concurrency on Elasticsearch 6."""

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, expected=(200,), deps=(), purpose="api-contract"):
        add("legacy-doc." + name, api, method, path, expected=expected, purpose=purpose)
        graph["legacy-doc." + name] = tuple("legacy-doc." + d for d in deps)

    base = "/{index}/{doc_type}"
    case("create-index", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "create-put", "create", "PUT", base + "/one/_create?refresh=true", (201,), ("create-index",)
    )
    case(
        "create-post",
        "create",
        "POST",
        base + "/two/_create?refresh=true",
        (201,),
        ("create-index",),
    )
    case("create-conflict", "create", "PUT", base + "/one/_create", (409,), ("create-put",))
    case(
        "created-readback",
        "get",
        "GET",
        base + "/one",
        deps=("create-put", "create-conflict"),
        purpose="effect-check",
    )
    case("source", "get_source", "GET", base + "/one/_source", deps=("create-put",))
    case("exists", "exists", "HEAD", base + "/one", deps=("create-put",))
    case("exists-source", "exists_source", "HEAD", base + "/one/_source", deps=("create-put",))
    for method in ["GET", "POST"]:
        for scope, path in [
            ("global", "/_mget"),
            ("index", "/{index}/_mget"),
            ("typed", base + "/_mget"),
        ]:
            case("mget-" + method.lower() + "-" + scope, "mget", method, path, deps=("create-put",))
        for scope, path in [
            ("stored", base + "/one/_termvectors"),
            ("artificial", base + "/_termvectors"),
        ]:
            case(
                "vectors-" + method.lower() + "-" + scope,
                "termvectors",
                method,
                path,
                deps=("create-put",),
            )
        for scope, path in [
            ("global", "/_mtermvectors"),
            ("index", "/{index}/_mtermvectors"),
            ("typed", base + "/_mtermvectors"),
        ]:
            case(
                "mvectors-" + method.lower() + "-" + scope,
                "mtermvectors",
                method,
                path,
                deps=("create-put",),
            )
        case(
            "explain-" + method.lower(),
            "explain",
            method,
            base + "/one/_explain",
            deps=("create-put",),
        )
        case(
            "field-caps-" + method.lower(),
            "field_caps",
            method,
            "/{index}/_field_caps?fields=n,text",
            deps=("create-index",),
        )
    case(
        "update",
        "update",
        "POST",
        base + "/one/_update?version=1&refresh=true",
        deps=("created-readback",),
    )
    case("update-stale", "update", "POST", base + "/one/_update?version=1", (409,), ("update",))
    case(
        "updated-readback",
        "get",
        "GET",
        base + "/one",
        deps=("update", "update-stale"),
        purpose="effect-check",
    )
    case(
        "overwrite",
        "index",
        "PUT",
        base + "/one?version=2&refresh=true",
        deps=("updated-readback",),
    )
    case("overwrite-stale", "index", "PUT", base + "/one?version=2", (409,), ("overwrite",))
    case(
        "overwritten-readback",
        "get",
        "GET",
        base + "/one",
        deps=("overwrite", "overwrite-stale"),
        purpose="effect-check",
    )
    case(
        "delete-stale",
        "delete",
        "DELETE",
        base + "/one?version=2",
        (409,),
        ("overwritten-readback",),
    )
    case(
        "delete-preserved",
        "get",
        "GET",
        base + "/one",
        deps=("delete-stale",),
        purpose="effect-check",
    )
    case(
        "delete",
        "delete",
        "DELETE",
        base + "/one?version=3&refresh=true",
        deps=("delete-preserved",),
    )
    case("deleted-get", "get", "GET", base + "/one", (404,), ("delete",), "effect-check")
    case(
        "deleted-source",
        "exists_source",
        "HEAD",
        base + "/one/_source",
        (404,),
        ("delete",),
        "effect-check",
    )
    case("delete-again", "delete", "DELETE", base + "/one", (404,), ("delete",))
    case(
        "upsert", "update", "POST", base + "/three/_update?refresh=true", (201,), ("create-index",)
    )
    case("noop", "update", "POST", base + "/three/_update", deps=("upsert",))
    case("noop-readback", "get", "GET", base + "/three", deps=("noop",), purpose="effect-check")
    case(
        "script-update",
        "update",
        "POST",
        base + "/three/_update?refresh=true",
        deps=("noop-readback",),
    )
    case(
        "script-readback",
        "get",
        "GET",
        base + "/three",
        deps=("script-update",),
        purpose="effect-check",
    )
    case(
        "count-after-delete",
        "count",
        "GET",
        "/{index}/_count",
        deps=("delete", "create-post", "script-update"),
        purpose="effect-check",
    )
    case("cleanup", "indices.delete", "DELETE", "/{index}", (200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    if not catalog.version.startswith("6."):
        raise ValueError("Typed legacy document fixture requires Elasticsearch 6")
    values = {"index": prefix + "-legacy-doc", "doc_type": "fixture"}
    original = {"n": 1, "text": "hello elastic", "group": "g1"}

    def call(name, body=OMITTED, assertions=(), verifies=()):
        spec = catalog.cases["legacy-doc." + name]
        result = catalog.execute(
            run,
            spec.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=spec.dependency_plan,
            verifies=["legacy-doc." + n for n in verifies],
            semantic=bool(verifies),
        )
        print(spec.id, result.state, result.status, flush=True)
        return result

    def version_and_n(number, version):
        return [
            ("source n", lambda d: d["_source"]["n"], number),
            ("internal version", lambda d: d["_version"], version),
        ]

    conflict = [
        ("version conflict", lambda d: d["error"]["type"], "version_conflict_engine_exception")
    ]
    call(
        "create-index",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "fixture": {
                    "properties": {
                        "n": {"type": "integer"},
                        "group": {"type": "keyword"},
                        "text": {"type": "text", "term_vector": "with_positions_offsets"},
                    }
                }
            },
        },
        [("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        call("create-put", original, [("created", lambda d: d["result"], "created")])
        call("create-post", {"n": 2, "text": "world elastic", "group": "g2"})
        call("create-conflict", {"n": 99}, conflict)
        call(
            "created-readback",
            assertions=version_and_n(1, 1),
            verifies=["create-put", "create-conflict"],
        )
        call(
            "source",
            assertions=[("raw source body", lambda d: d, original)],
            verifies=["create-put"],
        )
        call("exists")
        call("exists-source")
        for method in ["get", "post"]:
            for scope in ["global", "index", "typed"]:
                call(
                    "mget-" + method + "-" + scope,
                    {
                        "docs": [
                            {"_index": values["index"], "_type": "fixture", "_id": identifier}
                            for identifier in ["one", "missing"]
                        ]
                    },
                    [
                        ("existing item source", lambda d: d["docs"][0]["_source"]["n"], 1),
                        ("missing item distinguished", lambda d: d["docs"][1]["found"], False),
                    ],
                )
            for scope in ["stored", "artificial"]:
                body = {"fields": ["text"]}
                if scope == "artificial":
                    body["doc"] = {"text": "hello synthetic"}
                term = "elastic" if scope == "stored" else "synthetic"
                call(
                    "vectors-" + method + "-" + scope,
                    body,
                    [
                        (
                            "expected term frequency",
                            lambda d: d["term_vectors"]["text"]["terms"][term]["term_freq"],
                            1,
                        )
                    ],
                )
            for scope in ["global", "index", "typed"]:
                call(
                    "mvectors-" + method + "-" + scope,
                    {
                        "docs": [
                            {
                                "_index": values["index"],
                                "_type": "fixture",
                                "_id": "one",
                                "fields": ["text"],
                            }
                        ]
                    },
                    [
                        (
                            "document term vector",
                            lambda d: d["docs"][0]["term_vectors"]["text"]["terms"]["elastic"][
                                "term_freq"
                            ],
                            1,
                        )
                    ],
                )
            call(
                "explain-" + method,
                {"query": {"term": {"n": 1}}},
                [("query matches stored document", lambda d: d["matched"], True)],
            )
            call(
                "field-caps-" + method,
                assertions=[
                    (
                        "integer field searchable",
                        lambda d: d["fields"]["n"]["integer"]["searchable"],
                        True,
                    ),
                    (
                        "text field searchable",
                        lambda d: d["fields"]["text"]["text"]["searchable"],
                        True,
                    ),
                ],
            )
        call("update", {"doc": {"n": 3}}, [("updated", lambda d: d["result"], "updated")])
        call("update-stale", {"doc": {"n": 99}}, conflict)
        call(
            "updated-readback", assertions=version_and_n(3, 2), verifies=["update", "update-stale"]
        )
        call("overwrite", {**original, "n": 4}, [("updated", lambda d: d["result"], "updated")])
        call("overwrite-stale", {"n": 99}, conflict)
        call(
            "overwritten-readback",
            assertions=version_and_n(4, 3),
            verifies=["overwrite", "overwrite-stale"],
        )
        call("delete-stale", assertions=conflict)
        call("delete-preserved", assertions=version_and_n(4, 3), verifies=["delete-stale"])
        call("delete", assertions=[("deleted", lambda d: d["result"], "deleted")])
        call(
            "deleted-get",
            assertions=[("not found", lambda d: d["found"], False)],
            verifies=["delete"],
        )
        call("deleted-source")
        call("delete-again", assertions=[("already absent", lambda d: d["result"], "not_found")])
        call(
            "upsert",
            {"doc": {"n": 5, "text": "upsert elastic"}, "doc_as_upsert": True},
            [("created by upsert", lambda d: d["result"], "created")],
        )
        call("noop", {"doc": {"n": 5}}, [("noop", lambda d: d["result"], "noop")])
        call("noop-readback", assertions=version_and_n(5, 1), verifies=["upsert", "noop"])
        call(
            "script-update",
            {
                "script": {
                    "source": "ctx._source.n += params.delta",
                    "lang": "painless",
                    "params": {"delta": 2},
                }
            },
        )
        call("script-readback", assertions=version_and_n(7, 2), verifies=["script-update"])
        call(
            "count-after-delete",
            assertions=[("two surviving documents", lambda d: d["count"], 2)],
            verifies=["delete", "script-update"],
        )
    finally:
        call("cleanup")
