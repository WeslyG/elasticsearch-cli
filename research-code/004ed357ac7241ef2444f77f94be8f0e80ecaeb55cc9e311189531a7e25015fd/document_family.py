"""Document lifecycle, concurrency and term-vector evidence."""

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES


def declare(add, version="9.5.6"):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("document." + name, api, method, path, expected=expected, purpose=purpose)
        graph["document." + name] = tuple("document." + d for d in deps)

    case("create-index", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "create-put", "create", "PUT", "/{index}/_create/a?refresh=false", ("create-index",), (201,)
    )
    case(
        "realtime",
        "get",
        "GET",
        "/{index}/_doc/a?realtime=true",
        ("create-put",),
        purpose="effect-check",
    )
    case(
        "not-refreshed",
        "get",
        "GET",
        "/{index}/_doc/a?realtime=false",
        ("create-put",),
        (404,),
        purpose="effect-check",
    )
    case(
        "refresh",
        "indices.refresh",
        "POST",
        "/{index}/_refresh",
        ("not-refreshed",),
        purpose="fixture-setup",
    )
    case(
        "refreshed",
        "get",
        "GET",
        "/{index}/_doc/a?realtime=false",
        ("refresh",),
        purpose="effect-check",
    )
    case("create-post", "create", "POST", "/{index}/_create/b?refresh=true", ("refreshed",), (201,))
    case("create-conflict", "create", "PUT", "/{index}/_create/a", ("create-put",), (409,))
    case(
        "source",
        "get_source",
        "GET",
        "/{index}/_source/a",
        ("create-conflict",),
        purpose="effect-check",
    )
    case(
        "source-filter",
        "get_source",
        "GET",
        "/{index}/_source/a?_source_includes=n",
        ("source",),
        purpose="effect-check",
    )
    case("exists", "exists", "HEAD", "/{index}/_doc/a", ("create-put",))
    for method in ["GET", "POST"]:
        for scope, base in [("global", ""), ("index", "/{index}")]:
            stem = method.lower() + "." + scope
            case("mget." + stem, "mget", method, base + "/_mget", ("create-post",))
            case(
                "mtermvectors." + stem,
                "mtermvectors",
                method,
                base + "/_mtermvectors",
                ("create-post",),
            )
            case(
                "field-caps." + stem,
                "field_caps",
                method,
                base + "/_field_caps?fields=n,text,secret",
                ("create-post",),
            )
        for variant, path in [
            ("stored", "/{index}/_termvectors/a"),
            ("artificial", "/{index}/_termvectors"),
        ]:
            case(
                "termvectors." + method.lower() + "." + variant,
                "termvectors",
                method,
                path,
                ("create-post",),
            )
    if version in EARLY_SEVEN_RELEASES:
        case(
            "source-exists",
            "exists_source",
            "HEAD",
            "/{index}/_source/a",
            ("source",),
            purpose="effect-check",
        )
        case("put-no-id-refused", "index", "PUT", "/{index}/_doc", ("refreshed",), (405,))
        case(
            "put-no-id-count",
            "count",
            "GET",
            "/{index}/_count",
            ("put-no-id-refused",),
            purpose="effect-check",
        )
        for method in ["GET", "POST"]:
            case(
                "termvectors." + method.lower() + ".artificial-trailing",
                "termvectors",
                method,
                "/{index}/_termvectors/",
                ("create-post",),
            )
        case(
            "vectors-count",
            "count",
            "GET",
            "/{index}/_count",
            ("termvectors.get.artificial-trailing", "termvectors.post.artificial-trailing"),
            purpose="effect-check",
        )
    case(
        "get-sequence",
        "get",
        "GET",
        "/{index}/_doc/a",
        ("create-put",),
        purpose="fixture-precondition",
    )
    case(
        "update",
        "update",
        "POST",
        "/{index}/_update/a?if_seq_no={seq}&if_primary_term={term}",
        ("get-sequence",),
    )
    case(
        "update-stale",
        "update",
        "POST",
        "/{index}/_update/a?if_seq_no={seq}&if_primary_term={term}",
        ("update",),
        (409,),
    )
    case(
        "update-readback",
        "get",
        "GET",
        "/{index}/_doc/a",
        ("update-stale",),
        purpose="effect-check",
    )
    case(
        "overwrite",
        "index",
        "PUT",
        "/{index}/_doc/a?if_seq_no={seq}&if_primary_term={term}",
        ("update-readback",),
    )
    case(
        "overwrite-stale",
        "index",
        "PUT",
        "/{index}/_doc/a?if_seq_no={seq}&if_primary_term={term}",
        ("overwrite",),
        (409,),
    )
    case(
        "overwrite-readback",
        "get",
        "GET",
        "/{index}/_doc/a",
        ("overwrite-stale",),
        purpose="effect-check",
    )
    case(
        "delete-stale",
        "delete",
        "DELETE",
        "/{index}/_doc/a?if_seq_no={seq}&if_primary_term={term}",
        ("overwrite-readback",),
        (409,),
    )
    case(
        "delete-preserved",
        "get",
        "GET",
        "/{index}/_doc/a",
        ("delete-stale",),
        purpose="effect-check",
    )
    case(
        "delete",
        "delete",
        "DELETE",
        "/{index}/_doc/a?if_seq_no={seq}&if_primary_term={term}",
        ("delete-preserved",),
    )
    case(
        "deleted-get", "get", "GET", "/{index}/_doc/a", ("delete",), (404,), purpose="effect-check"
    )
    case(
        "deleted-head",
        "exists",
        "HEAD",
        "/{index}/_doc/a",
        ("delete",),
        (404,),
        purpose="effect-check",
    )
    case("delete-again", "delete", "DELETE", "/{index}/_doc/a", ("delete",), (404,))
    case("upsert", "update", "POST", "/{index}/_update/upsert", ("create-index",), (201,))
    case(
        "upsert-readback", "get", "GET", "/{index}/_doc/upsert", ("upsert",), purpose="effect-check"
    )
    case("noop", "update", "POST", "/{index}/_update/upsert", ("upsert-readback",))
    case("noop-readback", "get", "GET", "/{index}/_doc/upsert", ("noop",), purpose="effect-check")
    case("script-update", "update", "POST", "/{index}/_update/upsert", ("noop-readback",))
    case(
        "script-readback",
        "get",
        "GET",
        "/{index}/_doc/upsert",
        ("script-update",),
        purpose="effect-check",
    )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {"index": prefix + "-documents", "seq": 0, "term": 1}
    index = values["index"]
    source = {"n": 1, "text": "red red blue", "secret": "fixture"}

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["document." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["document." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def remember(result):
        data = result.data or {}
        values.update(seq=data.get("_seq_no", 0), term=data.get("_primary_term", 1))

    conflict = [
        ("version conflict", lambda d: d["error"]["type"], "version_conflict_engine_exception")
    ]
    call(
        "create-index",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"},
            "mappings": {
                "properties": {
                    "n": {"type": "integer"},
                    "secret": {"type": "keyword"},
                    "text": {"type": "text", "term_vector": "with_positions_offsets"},
                }
            },
        },
        [("created", lambda d: d["acknowledged"], True)],
    )
    try:
        call("create-put", source, [("created", lambda d: d["result"], "created")])
        call(
            "realtime",
            assertions=[("realtime source", lambda d: d["_source"], source)],
            verifies=["create-put"],
            semantic=True,
        )
        call("not-refreshed", assertions=[("not visible to searcher", lambda d: d["found"], False)])
        call("refresh")
        call(
            "refreshed",
            assertions=[("visible to searcher", lambda d: d["_source"], source)],
            verifies=["refresh"],
            semantic=True,
        )
        if catalog.version in EARLY_SEVEN_RELEASES:
            call(
                "put-no-id-refused",
                {"n": 99},
                [("native405 identifies allowed POST", lambda d: "POST" in str(d["error"]), True)],
            )
            call(
                "put-no-id-count",
                assertions=[
                    ("invalid no-ID PUT did not create another document", lambda d: d["count"], 1)
                ],
                verifies=["put-no-id-refused"],
                semantic=True,
            )
        call("create-post", {**source, "n": 2}, [("created", lambda d: d["result"], "created")])
        call("create-conflict", {"n": 99}, conflict)
        call(
            "source",
            assertions=[("create conflict preserves source", lambda d: d, source)],
            verifies=["create-conflict"],
            semantic=True,
        )
        call(
            "source-filter",
            assertions=[("only requested source field", lambda d: d, {"n": 1})],
            semantic=True,
        )
        call("exists")
        if catalog.version in EARLY_SEVEN_RELEASES:
            call("source-exists", semantic=True)
        for method in ["get", "post"]:
            for scope in ["global", "index"]:
                stem = method + "." + scope
                docs = [
                    {"_index": index, "_id": identifier} for identifier in ["a", "b", "missing"]
                ]
                call(
                    "mget." + stem,
                    {"docs": docs},
                    [
                        (
                            "mixed found states",
                            lambda d: [r["found"] for r in d["docs"]],
                            [True, True, False],
                        ),
                        (
                            "sources in order",
                            lambda d: [r["_source"]["n"] for r in d["docs"][:2]],
                            [1, 2],
                        ),
                    ],
                    semantic=True,
                )
                call(
                    "mtermvectors." + stem,
                    {"docs": [{"_index": index, "_id": "a", "fields": ["text"]}]},
                    [
                        (
                            "stored term frequency",
                            lambda d: d["docs"][0]["term_vectors"]["text"]["terms"]["red"][
                                "term_freq"
                            ],
                            2,
                        )
                    ],
                    semantic=True,
                )
                call(
                    "field-caps." + stem,
                    assertions=[
                        (
                            "integer aggregatable",
                            lambda d: d["fields"]["n"]["integer"]["aggregatable"],
                            True,
                        ),
                        (
                            "text not aggregatable",
                            lambda d: d["fields"]["text"]["text"]["aggregatable"],
                            False,
                        ),
                    ],
                    semantic=True,
                )
            variants = ["stored", "artificial"] + (
                ["artificial-trailing"] if catalog.version in EARLY_SEVEN_RELEASES else []
            )
            for variant in variants:
                body = {"fields": ["text"], "positions": True, "offsets": True}
                if variant.startswith("artificial"):
                    body["doc"] = {"text": "red red blue"}
                call(
                    "termvectors." + method + "." + variant,
                    body,
                    [
                        (
                            "term frequency",
                            lambda d: d["term_vectors"]["text"]["terms"]["red"]["term_freq"],
                            2,
                        ),
                        (
                            "positions retained",
                            lambda d: [
                                t["position"]
                                for t in d["term_vectors"]["text"]["terms"]["red"]["tokens"]
                            ],
                            [0, 1],
                        ),
                    ],
                    semantic=True,
                )
        if catalog.version in EARLY_SEVEN_RELEASES:
            call(
                "vectors-count",
                assertions=[
                    ("artificial vector calls did not persist documents", lambda d: d["count"], 2)
                ],
                verifies=[
                    "termvectors.get.artificial-trailing",
                    "termvectors.post.artificial-trailing",
                ],
                semantic=True,
            )
        response = call("get-sequence")
        remember(response)
        call("update", {"doc": {"n": 2}}, [("updated", lambda d: d["result"], "updated")])
        call("update-stale", {"doc": {"n": 99}}, conflict)
        response = call(
            "update-readback",
            assertions=[("stale update not applied", lambda d: d["_source"]["n"], 2)],
            verifies=["update", "update-stale"],
            semantic=True,
        )
        remember(response)
        call("overwrite", {"n": 3}, [("overwritten", lambda d: d["result"], "updated")])
        call("overwrite-stale", {"n": 99}, conflict)
        response = call(
            "overwrite-readback",
            assertions=[("stale overwrite not applied", lambda d: d["_source"], {"n": 3})],
            verifies=["overwrite", "overwrite-stale"],
            semantic=True,
        )
        newest = response
        call("delete-stale", assertions=conflict)
        response = call(
            "delete-preserved",
            assertions=[("stale delete preserves document", lambda d: d["_source"], {"n": 3})],
            verifies=["delete-stale"],
            semantic=True,
        )
        remember(newest)
        call("delete", assertions=[("deleted", lambda d: d["result"], "deleted")])
        call(
            "deleted-get",
            assertions=[("document absent", lambda d: d["found"], False)],
            verifies=["delete"],
        )
        call("deleted-head")
        call("delete-again", assertions=[("already absent", lambda d: d["result"], "not_found")])
        call(
            "upsert",
            {"doc": {"n": 7}, "doc_as_upsert": True},
            [("upsert created", lambda d: d["result"], "created")],
        )
        response = call(
            "upsert-readback",
            assertions=[("upsert source", lambda d: d["_source"], {"n": 7})],
            verifies=["upsert"],
            semantic=True,
        )
        sequence = (response.data or {}).get("_seq_no")
        call("noop", {"doc": {"n": 7}}, [("no-op", lambda d: d["result"], "noop")])
        call(
            "noop-readback",
            assertions=[("noop preserves sequence", lambda d: d["_seq_no"], sequence)],
            verifies=["noop"],
            semantic=True,
        )
        call(
            "script-update",
            {"script": {"source": "ctx._source.n += params.delta", "params": {"delta": 1}}},
        )
        call(
            "script-readback",
            assertions=[("script changed source", lambda d: d["_source"]["n"], 8)],
            verifies=["script-update"],
            semantic=True,
        )
    finally:
        call("cleanup")
