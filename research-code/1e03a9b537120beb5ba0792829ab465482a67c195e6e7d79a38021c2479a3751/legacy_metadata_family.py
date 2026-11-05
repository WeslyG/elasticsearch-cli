"""Typed mapping paths, alias effects and settings scopes on isolated ES 6."""

import json

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, expected=(200,), deps=(), purpose="api-contract"):
        add("legacy-meta." + name, api, method, path, expected=expected, purpose=purpose)
        graph["legacy-meta." + name] = tuple("legacy-meta." + d for d in deps)

    # The lab is disposable and exclusive; previous async fixtures created .tasks.
    case(
        "clear-task-results",
        "indices.delete",
        "DELETE",
        "/.tasks",
        (200, 404),
        purpose="fixture-setup",
    )
    for side in ["a", "b"]:
        case(
            "create-" + side,
            "indices.create",
            "PUT",
            "/{" + side + "}",
            deps=("clear-task-results",),
            purpose="fixture-setup",
        )
        case(
            "seed-" + side,
            "bulk",
            "POST",
            "/{" + side + "}/_bulk?refresh=true",
            deps=("create-" + side,),
            purpose="fixture-setup",
        )
    case(
        "only-owned-indices",
        "cat.indices",
        "GET",
        "/_cat/indices?format=json&h=index",
        deps=("seed-a", "seed-b"),
        purpose="fixture-precondition",
    )
    paths = [
        "/{a}/{doc_type}/_mapping",
        "/{a}/_mapping/{doc_type}",
        "/_mapping/{doc_type}",
        "/{a}/{doc_type}/_mappings",
        "/{a}/_mappings/{doc_type}",
        "/_mappings/{doc_type}",
    ]
    mapping_ids = []
    for method in ["PUT", "POST"]:
        for number, path in enumerate(paths):
            name = "mapping-" + method.lower() + "-" + str(number)
            mapping_ids.append(name)
            case(name, "indices.put_mapping", method, path, deps=("only-owned-indices",))
    for number, path in enumerate(
        ["/_mapping", "/{a}/_mapping", "/_mapping/{doc_type}", "/{a}/_mapping/{doc_type}"]
    ):
        case(
            "get-mapping-" + str(number),
            "indices.get_mapping",
            "GET",
            path,
            deps=tuple(mapping_ids),
            purpose="effect-check",
        )
    case(
        "global-mapping-on-b",
        "indices.get_mapping",
        "GET",
        "/{b}/_mapping",
        deps=tuple(mapping_ids),
        purpose="effect-check",
    )
    for number, path in enumerate(
        [
            "/_mapping/field/{fields}",
            "/{a}/_mapping/field/{fields}",
            "/_mapping/{doc_type}/field/{fields}",
            "/{a}/_mapping/{doc_type}/field/{fields}",
        ]
    ):
        case(
            "get-field-" + str(number),
            "indices.get_field_mapping",
            "GET",
            path,
            deps=("only-owned-indices",),
        )
    case("get-indices", "indices.get", "GET", "/{both}", deps=("only-owned-indices",))
    for method in ["PUT", "POST"]:
        for number, path in enumerate(["/{a}/_alias/{alias}", "/{a}/_aliases/{alias}"]):
            name = "alias-" + method.lower() + "-" + str(number)
            case(name, "indices.put_alias", method, path, deps=("only-owned-indices",))
            case(
                name + "-get",
                "indices.get_alias",
                "GET",
                "/_alias/{alias}",
                deps=(name,),
                purpose="effect-check",
            )
            case(
                name + "-search",
                "search",
                "GET",
                "/{alias}/_search",
                deps=(name,),
                purpose="effect-check",
            )
    alias_deps = ("alias-put-0",)
    for number, path in enumerate(
        ["/_alias", "/_alias/{alias}", "/{a}/_alias/{alias}", "/{a}/_alias"]
    ):
        case("aliases-get-" + str(number), "indices.get_alias", "GET", path, deps=alias_deps)
    for number, path in enumerate(["/_alias/{alias}", "/{a}/_alias/{alias}"]):
        case("aliases-head-" + str(number), "indices.exists_alias", "HEAD", path, deps=alias_deps)
    case("move-alias", "indices.update_aliases", "POST", "/_aliases", deps=alias_deps)
    case(
        "moved-get",
        "indices.get_alias",
        "GET",
        "/_alias/{alias}",
        deps=("move-alias",),
        purpose="effect-check",
    )
    case(
        "moved-search",
        "search",
        "GET",
        "/{alias}/_search",
        deps=("move-alias",),
        purpose="effect-check",
    )
    case("multi-alias", "indices.update_aliases", "POST", "/_aliases", deps=("only-owned-indices",))
    case(
        "multi-write",
        "index",
        "PUT",
        "/{multi_alias}/{doc_type}/rejected",
        (400,),
        ("multi-alias",),
    )
    for side in ["a", "b"]:
        case(
            "multi-absent-" + side,
            "get",
            "GET",
            "/{" + side + "}/{doc_type}/rejected",
            (404,),
            ("multi-write",),
            "effect-check",
        )
    case(
        "write-alias",
        "indices.put_alias",
        "PUT",
        "/{b}/_alias/{write_alias}",
        deps=("only-owned-indices",),
    )
    case(
        "alias-write",
        "index",
        "PUT",
        "/{write_alias}/{doc_type}/three?refresh=true",
        (201,),
        ("write-alias",),
    )
    case(
        "alias-write-on-b",
        "get",
        "GET",
        "/{b}/{doc_type}/three",
        deps=("alias-write",),
        purpose="effect-check",
    )
    case(
        "alias-write-not-a",
        "get",
        "GET",
        "/{a}/{doc_type}/three",
        (404,),
        ("alias-write",),
        "effect-check",
    )
    for number, path in enumerate(["/{a}/_alias/{alias}", "/{a}/_aliases/{alias}"]):
        case(
            "delete-alias-" + str(number),
            "indices.delete_alias",
            "DELETE",
            path,
            deps=("alias-post-" + str(number),),
        )
        case(
            "deleted-alias-" + str(number),
            "indices.exists_alias",
            "HEAD",
            "/_alias/{alias}",
            (404,),
            ("delete-alias-" + str(number),),
            "effect-check",
        )
    case(
        "settings-global", "indices.put_settings", "PUT", "/_settings", deps=("only-owned-indices",)
    )
    for number, path in enumerate(
        ["/_settings", "/{a}/_settings", "/{a}/_settings/{setting}", "/_settings/{setting}"]
    ):
        case(
            "settings-get-" + str(number),
            "indices.get_settings",
            "GET",
            path + "?flat_settings=true",
            deps=("settings-global",),
            purpose="effect-check",
        )
    case(
        "settings-index", "indices.put_settings", "PUT", "/{a}/_settings", deps=("settings-global",)
    )
    case(
        "settings-scope",
        "indices.get_settings",
        "GET",
        "/_settings/{setting}?flat_settings=true",
        deps=("settings-index",),
        purpose="effect-check",
    )
    case(
        "block-write", "indices.put_settings", "PUT", "/{a}/_settings", deps=("only-owned-indices",)
    )
    case("write-blocked", "index", "PUT", "/{a}/{doc_type}/blocked", (403,), ("block-write",))
    case("unblock-write", "indices.put_settings", "PUT", "/{a}/_settings", deps=("write-blocked",))
    case(
        "write-restored",
        "index",
        "PUT",
        "/{a}/{doc_type}/after?refresh=true",
        (201,),
        ("unblock-write",),
    )
    case(
        "restored-readback",
        "get",
        "GET",
        "/{a}/{doc_type}/after",
        deps=("write-restored",),
        purpose="effect-check",
    )
    for side in ["a", "b"]:
        case(
            "cleanup-" + side,
            "indices.delete",
            "DELETE",
            "/{" + side + "}",
            (200, 404),
            purpose="cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    if not catalog.version.startswith("6."):
        raise ValueError("Typed metadata fixture requires Elasticsearch 6")
    values = {
        "a": prefix + "-legacy-meta-a",
        "b": prefix + "-legacy-meta-b",
        "both": prefix + "-legacy-meta-a," + prefix + "-legacy-meta-b",
        "doc_type": "fixture",
        "fields": "n,group",
        "setting": "index.refresh_interval",
        "alias": "unset",
        "multi_alias": prefix + "-multi",
        "write_alias": prefix + "-write",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), ndjson=False):
        spec = catalog.cases["legacy-meta." + name]
        result = catalog.execute(
            run,
            spec.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=spec.dependency_plan,
            verifies=["legacy-meta." + n for n in verifies],
            semantic=bool(verifies),
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(spec.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    aliases = {}
    mapping_ids = []
    all_fields = []
    global_fields = []
    global_ids = []
    call("clear-task-results")
    try:
        for side, first in [("a", 10), ("b", 20)]:
            call(
                "create-" + side,
                {
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "refresh_interval": "-1",
                    },
                    "mappings": {
                        "fixture": {
                            "properties": {"n": {"type": "integer"}, "group": {"type": "keyword"}}
                        }
                    },
                },
                ack,
            )
            lines = []
            for identifier, n, group in [("one", first, "visible"), ("two", first + 1, "hidden")]:
                lines.extend(
                    [{"index": {"_type": "fixture", "_id": identifier}}, {"n": n, "group": group}]
                )
            call(
                "seed-" + side,
                ("\n".join(json.dumps(d) for d in lines) + "\n").encode(),
                [("seed no errors", lambda d: d["errors"], False)],
                ndjson=True,
            )
        call(
            "only-owned-indices",
            assertions=[
                (
                    "global writes restricted to two own fixture indices",
                    lambda d: sorted(row["index"] for row in d),
                    sorted([values["a"], values["b"]]),
                )
            ],
        )
        for method in ["put", "post"]:
            for number in range(6):
                name = "mapping-" + method + "-" + str(number)
                field = "added_" + method + "_" + str(number)
                mapping_ids.append(name)
                all_fields.append(field)
                if number in [2, 5]:
                    global_fields.append(field)
                    global_ids.append(name)
                call(name, {"properties": {field: {"type": "keyword"}}}, ack)
        for number in range(4):
            call(
                "get-mapping-" + str(number),
                assertions=[
                    (
                        "all twelve mapping mutations persisted",
                        lambda d: {
                            f: d[values["a"]]["mappings"]["fixture"]["properties"][f]["type"]
                            for f in all_fields
                        },
                        {f: "keyword" for f in all_fields},
                    )
                ],
                verifies=mapping_ids,
            )
        call(
            "global-mapping-on-b",
            assertions=[
                (
                    "global variants also changed B",
                    lambda d: {
                        f: d[values["b"]]["mappings"]["fixture"]["properties"][f]["type"]
                        for f in global_fields
                    },
                    {f: "keyword" for f in global_fields},
                )
            ],
            verifies=global_ids,
        )
        for number in range(4):
            call(
                "get-field-" + str(number),
                assertions=[
                    (
                        "typed field names",
                        lambda d: sorted(d[values["a"]]["mappings"]["fixture"]),
                        ["group", "n"],
                    )
                ],
            )
        call(
            "get-indices",
            assertions=[
                ("both exact index names", lambda d: sorted(d), sorted([values["a"], values["b"]]))
            ],
        )
        for method in ["put", "post"]:
            for number in range(2):
                name = "alias-" + method + "-" + str(number)
                aliases[name] = prefix + "-" + name
                values["alias"] = aliases[name]
                call(name, {"filter": {"term": {"group": "visible"}}}, ack)
                call(
                    name + "-get",
                    assertions=[
                        (
                            "own filtered alias exists",
                            lambda d: bool(
                                d[values["a"]]["aliases"][values["alias"]].get("filter")
                            ),
                            True,
                        )
                    ],
                    verifies=[name],
                )
                call(
                    name + "-search",
                    assertions=[
                        ("filter selects one document", lambda d: d["hits"]["total"], 1),
                        (
                            "visible source from A",
                            lambda d: d["hits"]["hits"][0]["_source"]["n"],
                            10,
                        ),
                    ],
                    verifies=[name],
                )
        values["alias"] = aliases["alias-put-0"]
        for number in range(4):
            call(
                "aliases-get-" + str(number),
                assertions=[
                    (
                        "selected alias present on A",
                        lambda d: values["alias"] in d[values["a"]]["aliases"],
                        True,
                    )
                ],
            )
        for number in range(2):
            call("aliases-head-" + str(number))
        call(
            "move-alias",
            {
                "actions": [
                    {"remove": {"index": values["a"], "alias": values["alias"]}},
                    {
                        "add": {
                            "index": values["b"],
                            "alias": values["alias"],
                            "filter": {"term": {"group": "visible"}},
                        }
                    },
                ]
            },
            ack,
        )
        call(
            "moved-get",
            assertions=[("alias moved exclusively to B", lambda d: sorted(d), [values["b"]])],
            verifies=["move-alias"],
        )
        call(
            "moved-search",
            assertions=[
                (
                    "filtered target document",
                    lambda d: [h["_source"]["n"] for h in d["hits"]["hits"]],
                    [20],
                )
            ],
            verifies=["move-alias"],
        )
        call(
            "multi-alias",
            {
                "actions": [
                    {"add": {"index": values[s], "alias": values["multi_alias"]}}
                    for s in ["a", "b"]
                ]
            },
            ack,
        )
        call(
            "multi-write",
            {"n": 99},
            [
                (
                    "multi-index alias write rejected",
                    lambda d: values["multi_alias"] in d["error"]["reason"],
                    True,
                )
            ],
        )
        for side in ["a", "b"]:
            call(
                "multi-absent-" + side,
                assertions=[("rejected write created nothing", lambda d: d["found"], False)],
                verifies=["multi-write"],
            )
        call("write-alias", {}, ack)
        call("alias-write", {"n": 30, "group": "visible"})
        call(
            "alias-write-on-b",
            assertions=[("write reached B", lambda d: d["_source"]["n"], 30)],
            verifies=["alias-write"],
        )
        call(
            "alias-write-not-a",
            assertions=[("write did not reach A", lambda d: d["found"], False)],
            verifies=["alias-write"],
        )
        for number in range(2):
            values["alias"] = aliases["alias-post-" + str(number)]
            call("delete-alias-" + str(number), assertions=ack)
            call("deleted-alias-" + str(number), verifies=["delete-alias-" + str(number)])
        call("settings-global", {"index.refresh_interval": "7s"}, ack)
        for number in range(4):
            wanted = [values["a"]] if number in [1, 2] else [values["a"], values["b"]]
            call(
                "settings-get-" + str(number),
                assertions=[
                    (
                        "global settings reached selected indices",
                        lambda d: {
                            k: v["settings"]["index.refresh_interval"] for k, v in d.items()
                        },
                        {k: "7s" for k in wanted},
                    )
                ],
                verifies=["settings-global"],
            )
        call("settings-index", {"index": {"refresh_interval": "9s"}}, ack)
        call(
            "settings-scope",
            assertions=[
                (
                    "index setting does not alter B",
                    lambda d: {k: v["settings"]["index.refresh_interval"] for k, v in d.items()},
                    {values["a"]: "9s", values["b"]: "7s"},
                )
            ],
            verifies=["settings-index"],
        )
        call("block-write", {"index.blocks.write": True}, ack)
        call(
            "write-blocked",
            {"n": 99},
            [("write block error", lambda d: d["error"]["type"], "cluster_block_exception")],
        )
        call("unblock-write", {"index.blocks.write": False}, ack)
        call("write-restored", {"n": 40, "group": "visible"})
        call(
            "restored-readback",
            assertions=[("write allowed after explicit false", lambda d: d["_source"]["n"], 40)],
            verifies=["unblock-write", "write-restored"],
        )
    finally:
        call("cleanup-a")
        call("cleanup-b")
