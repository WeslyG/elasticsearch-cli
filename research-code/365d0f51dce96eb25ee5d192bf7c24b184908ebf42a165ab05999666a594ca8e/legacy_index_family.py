"""Legacy index effects: typed existence, native-segment no-op and alias rollover."""

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("legacy-index." + name, api, method, path, expected=expected, purpose=purpose)
        graph["legacy-index." + name] = tuple("legacy-index." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case("seed", "index", "PUT", "/{alias}/fixture/one?refresh=true", ("create",), (201,))
    case("type-present", "indices.exists_type", "HEAD", "/{index}/_mapping/fixture", ("seed",))
    case(
        "type-absent", "indices.exists_type", "HEAD", "/{index}/_mapping/missing", ("seed",), (404,)
    )
    case("flush", "indices.flush", "POST", "/{index}/_flush", ("seed",))
    for method in ["GET", "POST"]:
        case(
            "synced-" + method.lower(),
            "indices.flush_synced",
            method,
            "/{index}/_flush/synced",
            ("flush",),
        )
    case("upgrade-before", "indices.get_upgrade", "GET", "/{index}/_upgrade", ("flush",))
    case(
        "upgrade",
        "indices.upgrade",
        "POST",
        "/{index}/_upgrade?only_ancient_segments=false",
        ("upgrade-before",),
    )
    case(
        "upgrade-after",
        "indices.get_upgrade",
        "GET",
        "/{index}/_upgrade",
        ("upgrade",),
        purpose="effect-check",
    )
    case("readback", "get", "GET", "/{index}/fixture/one", ("upgrade",), purpose="effect-check")
    case("rollover-unmet", "indices.rollover", "POST", "/{alias}/_rollover/{target}", ("seed",))
    case(
        "unmet-absent",
        "indices.exists",
        "HEAD",
        "/{target}",
        ("rollover-unmet",),
        (404,),
        "effect-check",
    )
    case(
        "rollover-dry",
        "indices.rollover",
        "POST",
        "/{alias}/_rollover/{target}?dry_run=true",
        ("unmet-absent",),
    )
    case(
        "dry-absent",
        "indices.exists",
        "HEAD",
        "/{target}",
        ("rollover-dry",),
        (404,),
        "effect-check",
    )
    case("rollover", "indices.rollover", "POST", "/{alias}/_rollover/{target}", ("dry-absent",))
    case(
        "alias-after",
        "indices.get_alias",
        "GET",
        "/_alias/{alias}",
        ("rollover",),
        purpose="effect-check",
    )
    case("write-new", "index", "PUT", "/{alias}/fixture/two?refresh=true", ("rollover",), (201,))
    case(
        "new-readback",
        "get",
        "GET",
        "/{target}/fixture/two",
        ("write-new",),
        purpose="effect-check",
    )
    case("old-absent", "get", "GET", "/{index}/fixture/two", ("write-new",), (404,), "effect-check")
    case(
        "old-preserved", "get", "GET", "/{index}/fixture/one", ("rollover",), purpose="effect-check"
    )
    for name, path in [("cleanup-source", "/{index}"), ("cleanup-target", "/{target}")]:
        case(name, "indices.delete", "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-roll-000001",
        "target": prefix + "-roll-000002",
        "alias": prefix + "-roll",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["legacy-index." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["legacy-index." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    settings = {"number_of_shards": 1, "number_of_replicas": 0}
    mappings = {"fixture": {"properties": {"n": {"type": "integer"}}}}
    call(
        "create",
        {"settings": settings, "mappings": mappings, "aliases": {values["alias"]: {}}},
        ack,
    )
    try:
        call(
            "seed",
            {"n": 42},
            [("alias initially writes source", lambda d: d["_index"], values["index"])],
        )
        call("type-present")
        call("type-absent")
        call("flush", assertions=[("no flush failures", lambda d: d["_shards"]["failed"], 0)])
        for method in ["get", "post"]:
            call(
                "synced-" + method,
                assertions=[
                    ("no synced-flush failures", lambda d: d["_shards"]["failed"], 0),
                    ("actual synced-flush shard", lambda d: d["_shards"]["successful"] >= 1, True),
                ],
            )
        native = [
            (
                "fresh native segments require no upgrade",
                lambda d: d["indices"][values["index"]]["size_to_upgrade_in_bytes"],
                0,
            )
        ]
        call("upgrade-before", assertions=native)
        call(
            "upgrade",
            assertions=[("upgrade reports no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call("upgrade-after", assertions=native, verifies=["upgrade"], semantic=True)
        call(
            "readback",
            assertions=[("data survives native-segment no-op", lambda d: d["_source"], {"n": 42})],
            verifies=["upgrade"],
            semantic=True,
        )
        call(
            "rollover-unmet",
            {"conditions": {"max_docs": 2}},
            [
                ("condition false", lambda d: list(d["conditions"].values()), [False]),
                ("no rollover", lambda d: d["rolled_over"], False),
            ],
        )
        call("unmet-absent", verifies=["rollover-unmet"])
        body = {"conditions": {"max_docs": 1}, "settings": settings, "mappings": mappings}
        call(
            "rollover-dry",
            body,
            [
                ("condition actually met", lambda d: list(d["conditions"].values()), [True]),
                ("explicit dry run", lambda d: d["dry_run"], True),
                ("dry run did not roll", lambda d: d["rolled_over"], False),
            ],
        )
        call("dry-absent", verifies=["rollover-dry"])
        call(
            "rollover",
            body,
            [
                ("rolled over", lambda d: d["rolled_over"], True),
                ("old index exact", lambda d: d["old_index"], values["index"]),
                ("new index exact", lambda d: d["new_index"], values["target"]),
            ],
        )
        call(
            "alias-after",
            assertions=[
                ("alias moved exclusively to new index", lambda d: sorted(d), [values["target"]])
            ],
            verifies=["rollover"],
            semantic=True,
        )
        call(
            "write-new",
            {"n": 99},
            [("alias writes target", lambda d: d["_index"], values["target"])],
        )
        call(
            "new-readback",
            assertions=[("target persisted new value", lambda d: d["_source"], {"n": 99})],
            verifies=["write-new"],
            semantic=True,
        )
        call(
            "old-absent",
            assertions=[("old index has no new document", lambda d: d["found"], False)],
            verifies=["write-new"],
        )
        call(
            "old-preserved",
            assertions=[("old document retained", lambda d: d["_source"], {"n": 42})],
            verifies=["rollover"],
            semantic=True,
        )
    finally:
        call("cleanup-source")
        call("cleanup-target")
