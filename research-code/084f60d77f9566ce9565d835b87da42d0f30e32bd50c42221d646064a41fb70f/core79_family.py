"""Pinned7.9 core additions: write block effects, name resolution, absent dangling IDs."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.9.3", "7.10.2", "7.11.2"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    specs = [
        ("create", "indices.create", "PUT", "/{index}", (), (200,)),
        ("write", "index", "PUT", "/{index}/_doc/one?refresh=true", ("create",), (201,)),
        (
            "resolve-index",
            "indices.resolve_index",
            "GET",
            "/_resolve/index/{index}",
            ("write",),
            (200,),
        ),
        (
            "resolve-alias",
            "indices.resolve_index",
            "GET",
            "/_resolve/index/{alias}",
            ("resolve-index",),
            (200,),
        ),
        (
            "invalid-block",
            "indices.add_block",
            "PUT",
            "/{index}/_block/not-a-block",
            ("resolve-alias",),
            (400,),
        ),
        ("block", "indices.add_block", "PUT", "/{index}/_block/write", ("invalid-block",), (200,)),
        ("blocked-write", "index", "PUT", "/{index}/_doc/two?refresh=true", ("block",), (403,)),
        ("unchanged", "count", "GET", "/{index}/_count", ("blocked-write",), (200,)),
        (
            "settings",
            "indices.get_settings",
            "GET",
            "/{index}/_settings?flat_settings=true",
            ("block",),
            (200,),
        ),
        ("unblock", "indices.put_settings", "PUT", "/{index}/_settings", ("unchanged",), (200,)),
        ("write-after", "index", "PUT", "/{index}/_doc/two?refresh=true", ("unblock",), (201,)),
        ("read-after", "get", "GET", "/{index}/_doc/two", ("write-after",), (200,)),
        (
            "dangling-list",
            "dangling_indices.list_dangling_indices",
            "GET",
            "/_dangling",
            ("read-after",),
            (200,),
        ),
        (
            "import-default",
            "dangling_indices.import_dangling_index",
            "POST",
            "/_dangling/{missing_uuid}",
            ("dangling-list",),
            (400,),
        ),
        (
            "import-accept",
            "dangling_indices.import_dangling_index",
            "POST",
            "/_dangling/{missing_uuid}?accept_data_loss=true",
            ("import-default",),
            (400,),
        ),
        (
            "delete-default",
            "dangling_indices.delete_dangling_index",
            "DELETE",
            "/_dangling/{missing_uuid}",
            ("import-accept",),
            (400,),
        ),
        (
            "delete-accept",
            "dangling_indices.delete_dangling_index",
            "DELETE",
            "/_dangling/{missing_uuid}?accept_data_loss=true",
            ("delete-default",),
            (400,),
        ),
        (
            "dangling-unchanged",
            "dangling_indices.list_dangling_indices",
            "GET",
            "/_dangling",
            ("delete-accept",),
            (200,),
        ),
        ("data-preserved", "count", "GET", "/{index}/_count", ("dangling-unchanged",), (200,)),
        ("cleanup", "indices.delete", "DELETE", "/{index}", (), (200, 404)),
    ]
    graph = {}
    for name, api, method, path, deps, expected in specs:
        identifier = "core79." + name
        add(
            identifier,
            api,
            method,
            path,
            expected=expected,
            purpose="fixture-cleanup" if name == "cleanup" else "api-contract",
        )
        graph[identifier] = tuple("core79." + d for d in deps)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Core additions not prepared for exact release")
    values = {
        "index": prefix + "-core79",
        "alias": prefix + "-core79-alias",
        "missing_uuid": prefix + "-absent-uuid",
    }

    def call(name, body=OMITTED, assertions=(), verifies=()):
        case = catalog.cases["core79." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=bool(assertions),
            verifies=["core79." + d for d in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    try:
        call(
            "create",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "aliases": {values["alias"]: {}},
            },
            ack,
        )
        call("write", {"n": 1})
        call(
            "resolve-index",
            assertions=[
                (
                    "resolved exact index",
                    lambda d: [i["name"] for i in d["indices"]],
                    [values["index"]],
                ),
                ("index advertises alias", lambda d: d["indices"][0]["aliases"], [values["alias"]]),
                ("not a data stream", lambda d: d["data_streams"], []),
            ],
            verifies=("create",),
        )
        call(
            "resolve-alias",
            assertions=[
                (
                    "resolved exact alias",
                    lambda d: [i["name"] for i in d["aliases"]],
                    [values["alias"]],
                ),
                (
                    "alias targets owned index",
                    lambda d: d["aliases"][0]["indices"],
                    [values["index"]],
                ),
            ],
            verifies=("create",),
        )
        call(
            "invalid-block",
            assertions=[
                (
                    "invalid block argument",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
        call("block", assertions=ack)
        call(
            "blocked-write",
            {"n": 2},
            [("write blocked", lambda d: d["error"]["type"], "cluster_block_exception")],
        )
        call(
            "unchanged",
            assertions=[("failed write adds no doc", lambda d: d["count"], 1)],
            verifies=("blocked-write",),
        )
        call(
            "settings",
            assertions=[
                (
                    "write block stored",
                    lambda d: d[values["index"]]["settings"]["index.blocks.write"],
                    "true",
                )
            ],
            verifies=("block",),
        )
        call("unblock", {"index.blocks.write": False}, ack)
        call("write-after", {"n": 2})
        call(
            "read-after",
            assertions=[("write works again", lambda d: d["_source"], {"n": 2})],
            verifies=("unblock", "write-after"),
        )
        empty = [("no dangling indices in owned node", lambda d: d["dangling_indices"], [])]
        call("dangling-list", assertions=empty)
        for name in ["import-default", "import-accept", "delete-default", "delete-accept"]:
            call(
                name,
                assertions=[
                    (
                        "absent UUID before acceptance guard",
                        lambda d: "No dangling index found for UUID" in str(d["error"]),
                        True,
                    ),
                    ("argument error", lambda d: d["error"]["type"], "illegal_argument_exception"),
                ],
            )
        call(
            "dangling-unchanged",
            assertions=empty,
            verifies=("import-default", "import-accept", "delete-default", "delete-accept"),
        )
        call("data-preserved", assertions=[("existing index unaffected", lambda d: d["count"], 2)])
    finally:
        call("cleanup")
