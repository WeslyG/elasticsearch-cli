"""Index metadata recipes: aliases, mapping conflicts and verified write blocks."""

from evidence_runner import OMITTED
from legacy_release_selection import ALIAS_REMOVE_MUST_EXIST_RELEASES, EARLY_SEVEN_PILOTS


def declare(add, version="9.5.6"):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if version in EARLY_SEVEN_PILOTS and name == "resolve":
            return
        add("metadata." + name, api, method, path, expected=expected, purpose=purpose)
        graph["metadata." + name] = tuple("metadata." + d for d in deps)

    for name, path in [("create", "/{index}"), ("create-target", "/{target}")]:
        case(name, "indices.create", "PUT", path, purpose="fixture-setup")
    case(
        "missing-before",
        "indices.exists_alias",
        "HEAD",
        "/_alias/{alias}",
        expected=(404,),
        purpose="fixture-precondition",
    )
    for method in ["PUT", "POST"]:
        for route in ["_alias", "_aliases"]:
            stem = method.lower() + "." + route
            case(
                "put." + stem,
                "indices.put_alias",
                method,
                "/{index}/" + route + "/{alias}",
                ("create",),
                purpose="api-contract",
            )
            case(
                "get." + stem,
                "indices.get_alias",
                "GET",
                "/{index}/_alias/{alias}",
                ("put." + stem,),
                purpose="effect-check",
            )
    for name, path in [
        ("all", "/_alias"),
        ("name", "/_alias/{alias}"),
        ("index-name", "/{index}/_alias/{alias}"),
        ("index", "/{index}/_alias"),
    ]:
        case(
            "aliases." + name,
            "indices.get_alias",
            "GET",
            path,
            ("put.post._aliases",),
            purpose="effect-check",
        )
    case("exists-global", "indices.exists_alias", "HEAD", "/_alias/{alias}", ("put.post._aliases",))
    case(
        "exists-index",
        "indices.exists_alias",
        "HEAD",
        "/{index}/_alias/{alias}",
        ("put.post._aliases",),
    )
    case(
        "seed",
        "index",
        "PUT",
        "/{index}/_doc/{id}?refresh=true",
        ("create",),
        (201,),
        purpose="fixture-setup",
    )
    case(
        "seed-visible",
        "index",
        "PUT",
        "/{index}/_doc/visible?refresh=true",
        ("create",),
        (201,),
        purpose="fixture-setup",
    )
    case(
        "seed-count",
        "count",
        "GET",
        "/{index}/_count",
        ("seed", "seed-visible"),
        purpose="fixture-precondition",
    )
    case(
        "filtered-search",
        "search",
        "POST",
        "/{alias}/_search",
        ("seed-count", "put.post._aliases"),
        purpose="effect-check",
    )
    if version in EARLY_SEVEN_PILOTS and version not in ALIAS_REMOVE_MUST_EXIST_RELEASES:
        case(
            "move-unsupported-must-exist",
            "indices.update_aliases",
            "POST",
            "/_aliases",
            ("filtered-search", "create-target"),
            (400,),
        )
        case(
            "move-refusal-preserved",
            "indices.get_alias",
            "GET",
            "/_alias/{alias}",
            ("move-unsupported-must-exist",),
            purpose="effect-check",
        )
    case(
        "move", "indices.update_aliases", "POST", "/_aliases", ("filtered-search", "create-target")
    )
    case(
        "moved-readback",
        "indices.get_alias",
        "GET",
        "/_alias/{alias}",
        ("move",),
        purpose="effect-check",
    )
    case("write-alias", "index", "PUT", "/{alias}/_doc/{id}?refresh=true", ("move",), (201,))
    case(
        "write-readback",
        "get",
        "GET",
        "/{target}/_doc/{id}",
        ("write-alias",),
        purpose="effect-check",
    )
    for name, api, method, path in [
        ("index-exists", "indices.exists", "HEAD", "/{target}"),
        ("index-get", "indices.get", "GET", "/{target}?flat_settings=true"),
        ("resolve", "indices.resolve_index", "GET", "/_resolve/index/{alias}"),
        ("settings", "indices.get_settings", "GET", "/{target}/_settings?flat_settings=true"),
    ]:
        case(name, api, method, path, ("move",), purpose="effect-check")
    for method in ["PUT", "POST"]:
        case(
            "mapping." + method.lower(),
            "indices.put_mapping",
            method,
            "/{target}/_mapping",
            ("create-target",),
        )
    for name, path in [("global", "/_mapping"), ("index", "/{target}/_mapping")]:
        case(
            "mapping-get." + name,
            "indices.get_mapping",
            "GET",
            path,
            ("mapping.put", "mapping.post"),
            purpose="effect-check",
        )
    for name, path in [
        ("global", "/_mapping/field/{fields}"),
        ("index", "/{target}/_mapping/field/{fields}"),
    ]:
        case(
            "field-get." + name,
            "indices.get_field_mapping",
            "GET",
            path,
            ("mapping.put", "mapping.post"),
            purpose="effect-check",
        )
    case(
        "mapping-conflict",
        "indices.put_mapping",
        "PUT",
        "/{target}/_mapping",
        ("mapping.put",),
        (400,),
    )
    case("invalid-document", "index", "PUT", "/{target}/_doc/{badid}", ("create-target",), (400,))
    case(
        "invalid-absent",
        "get",
        "GET",
        "/{target}/_doc/{badid}",
        ("invalid-document",),
        (404,),
        purpose="effect-check",
    )
    if version in EARLY_SEVEN_PILOTS:
        case("block", "indices.put_settings", "PUT", "/{target}/_settings", ("write-readback",))
    else:
        case("block", "indices.add_block", "PUT", "/{target}/_block/write", ("write-readback",))
    case("blocked-write", "index", "PUT", "/{target}/_doc/{blockedid}", ("block",), (403,))
    case(
        "blocked-absent",
        "get",
        "GET",
        "/{target}/_doc/{blockedid}",
        ("blocked-write",),
        (404,),
        purpose="effect-check",
    )
    case("unblock", "indices.put_settings", "PUT", "/{target}/_settings", ("blocked-write",))
    case("unblocked-write", "index", "PUT", "/{target}/_doc/{blockedid}", ("unblock",), (201,))
    case(
        "unblocked-readback",
        "get",
        "GET",
        "/{target}/_doc/{blockedid}",
        ("unblocked-write",),
        purpose="effect-check",
    )
    case(
        "remove-singular",
        "indices.delete_alias",
        "DELETE",
        "/{target}/_alias/{alias}",
        ("moved-readback",),
    )
    case(
        "removed-head",
        "indices.exists_alias",
        "HEAD",
        "/_alias/{alias}",
        ("remove-singular",),
        (404,),
        purpose="effect-check",
    )
    case("recreate", "indices.put_alias", "PUT", "/{target}/_alias/{alias}", ("remove-singular",))
    case(
        "remove-plural",
        "indices.delete_alias",
        "DELETE",
        "/{target}/_aliases/{alias}",
        ("recreate",),
    )
    case(
        "removed-get",
        "indices.get_alias",
        "GET",
        "/_alias/{alias}",
        ("remove-plural",),
        (404,),
        purpose="effect-check",
    )
    for name, path in [("cleanup-source", "/{index}"), ("cleanup-target", "/{target}")]:
        case(name, "indices.delete", "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-meta-a",
        "target": prefix + "-meta-b",
        "alias": prefix + "-live",
        "id": "one",
        "badid": "invalid",
        "blockedid": "blocked",
        "fields": "n,added_put,added_post",
    }
    index, target, alias = values["index"], values["target"], values["alias"]

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["metadata." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["metadata." + n for n in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    config = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": {"n": {"type": "integer"}, "group": {"type": "keyword"}}},
    }
    call("create", config, ack)
    call("create-target", config, ack)
    try:
        call("missing-before")
        for method in ["put", "post"]:
            for route in ["_alias", "_aliases"]:
                stem = method + "." + route
                call(
                    "put." + stem,
                    {"filter": {"term": {"group": "visible"}}, "is_write_index": True},
                    ack,
                )
                call(
                    "get." + stem,
                    assertions=[
                        (
                            "filter persisted",
                            lambda d: d[index]["aliases"][alias]["filter"],
                            {"term": {"group": "visible"}},
                        ),
                        (
                            "write index persisted",
                            lambda d: d[index]["aliases"][alias]["is_write_index"],
                            True,
                        ),
                    ],
                    verifies=["put." + stem],
                    semantic=True,
                )
        for name in ["all", "name", "index-name", "index"]:
            call(
                "aliases." + name,
                assertions=[
                    ("fixture alias present", lambda d: alias in d[index]["aliases"], True)
                ],
                verifies=["put.post._aliases"],
                semantic=True,
            )
        call("exists-global")
        call("exists-index")
        call("seed", {"n": 7, "group": "hidden"})
        call("seed-visible", {"n": 8, "group": "visible"})
        call("seed-count", assertions=[("two source documents", lambda d: d["count"], 2)])
        call(
            "filtered-search",
            {"query": {"match_all": {}}},
            [
                (
                    "filter returns only visible document",
                    lambda d: [h["_id"] for h in d["hits"]["hits"]],
                    ["visible"],
                )
            ],
            verifies=["put.post._aliases"],
            semantic=True,
        )
        move_actions = [
            {"remove": {"index": index, "alias": alias, "must_exist": True}},
            {"add": {"index": target, "alias": alias, "is_write_index": True}},
        ]
        if (
            catalog.version in EARLY_SEVEN_PILOTS
            and catalog.version not in ALIAS_REMOVE_MUST_EXIST_RELEASES
        ):
            call(
                "move-unsupported-must-exist",
                {"actions": move_actions},
                [
                    (
                        "native parser rejects must_exist",
                        lambda d: "must_exist" in str(d["error"]),
                        True,
                    )
                ],
            )
            call(
                "move-refusal-preserved",
                assertions=[
                    (
                        "rejected atomic operation retains original sole alias owner",
                        lambda d: sorted(d),
                        [index],
                    )
                ],
                semantic=True,
                verifies=["move-unsupported-must-exist"],
            )
            move_actions[0]["remove"].pop("must_exist")
        call("move", {"actions": move_actions}, ack)
        call(
            "moved-readback",
            assertions=[
                ("only target owns alias", lambda d: sorted(d), [target]),
                (
                    "target is write index",
                    lambda d: d[target]["aliases"][alias]["is_write_index"],
                    True,
                ),
            ],
            verifies=["move"],
            semantic=True,
        )
        call(
            "write-alias",
            {"n": 11, "group": "visible"},
            [("resolved destination", lambda d: d["_index"], target)],
        )
        call(
            "write-readback",
            assertions=[("alias write persisted at target", lambda d: d["_source"]["n"], 11)],
            verifies=["write-alias"],
            semantic=True,
        )
        call("index-exists")
        call("index-get", assertions=[("target metadata", lambda d: target in d, True)])
        if catalog.version not in EARLY_SEVEN_PILOTS:
            call(
                "resolve",
                assertions=[
                    (
                        "alias resolves to target",
                        lambda d: next(a for a in d["aliases"] if a["name"] == alias)["indices"],
                        [target],
                    )
                ],
                verifies=["move"],
                semantic=True,
            )
        call(
            "settings",
            assertions=[
                ("zero replicas", lambda d: d[target]["settings"]["index.number_of_replicas"], "0")
            ],
        )
        for method in ["put", "post"]:
            call("mapping." + method, {"properties": {"added_" + method: {"type": "keyword"}}}, ack)
        for name in ["global", "index"]:
            call(
                "mapping-get." + name,
                assertions=[
                    (
                        "added fields retained",
                        lambda d: sorted(
                            k for k in d[target]["mappings"]["properties"] if k.startswith("added_")
                        ),
                        ["added_post", "added_put"],
                    )
                ],
                verifies=["mapping.put", "mapping.post"],
                semantic=True,
            )
            call(
                "field-get." + name,
                assertions=[
                    (
                        "requested fields returned",
                        lambda d: sorted(d[target]["mappings"]),
                        ["added_post", "added_put", "n"],
                    )
                ],
                verifies=["mapping.put", "mapping.post"],
                semantic=True,
            )
        call(
            "mapping-conflict",
            {"properties": {"n": {"type": "keyword"}}},
            [
                (
                    "conflicting type rejected",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
        call(
            "invalid-document",
            {"n": "invalid"},
            [
                (
                    "parsing error",
                    lambda d: d["error"]["type"],
                    "mapper_parsing_exception"
                    if catalog.version == "7.17.29" or catalog.version in EARLY_SEVEN_PILOTS
                    else "document_parsing_exception",
                )
            ],
        )
        call(
            "invalid-absent",
            assertions=[("document not created", lambda d: d["found"], False)],
            verifies=["invalid-document"],
            semantic=True,
        )
        call(
            "block",
            {"index.blocks.write": True} if catalog.version in EARLY_SEVEN_PILOTS else OMITTED,
            assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
        )
        call(
            "blocked-write",
            {"n": 4},
            [("cluster write block", lambda d: d["error"]["type"], "cluster_block_exception")],
        )
        call(
            "blocked-absent",
            assertions=[("blocked write absent", lambda d: d["found"], False)],
            verifies=["blocked-write"],
            semantic=True,
        )
        call("unblock", {"index.blocks.write": False}, ack)
        call("unblocked-write", {"n": 4})
        call(
            "unblocked-readback",
            assertions=[("write succeeded after unblock", lambda d: d["_source"]["n"], 4)],
            verifies=["unblock", "unblocked-write"],
            semantic=True,
        )
        call("remove-singular", assertions=ack)
        call("removed-head")
        call("recreate", {}, ack)
        call("remove-plural", assertions=ack)
        call(
            "removed-get",
            assertions=[("alias not found", lambda d: d["status"], 404)],
            verifies=["remove-plural"],
            semantic=True,
        )
    finally:
        call("cleanup-source")
        call("cleanup-target")
