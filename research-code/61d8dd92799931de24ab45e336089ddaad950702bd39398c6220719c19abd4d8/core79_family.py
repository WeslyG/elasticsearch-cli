"""Pinned7.9 core additions: write block effects, name resolution, absent dangling IDs."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {
    "7.9.3",
    "7.10.2",
    "7.11.2",
    "7.12.1",
    "7.13.4",
    "7.14.2",
    "7.15.2",
    "7.16.3",
    "8.0.1",
    "8.1.3",
    "8.2.3",
    "8.3.3",
    "8.4.3",
    "8.5.3",
    "8.6.2",
    "8.7.1",
    "8.8.2",
    "8.9.2",
    "8.10.4",
    "8.11.4",
    "8.12.2",
    "8.13.4",
    "8.14.3",
    "8.15.5",
    "8.16.6",
    "8.17.10",
    "8.18.8",
    "9.0.8",
}


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
    if version in {
        "7.12.1",
        "7.13.4",
        "7.14.2",
        "7.15.2",
        "7.16.3",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
        "8.9.2",
        "8.10.4",
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
    }:
        specs.extend(
            [
                (
                    "search-compatible",
                    "search",
                    "GET",
                    "/{index}/_search?min_compatible_shard_node=" + version,
                    ("data-preserved",),
                    (200,),
                ),
                (
                    "search-bad-version",
                    "search",
                    "GET",
                    "/{index}/_search?min_compatible_shard_node=es-cli-invalid",
                    ("search-compatible",),
                    (200,) if version == "9.0.8" else (400,),
                ),
            ]
        )
    if version in {
        "7.12.1",
        "7.13.4",
        "7.14.2",
        "7.15.2",
        "7.16.3",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
        "8.9.2",
        "8.10.4",
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
    }:
        specs.extend(
            [
                (
                    "features",
                    "features.get_features",
                    "GET",
                    "/_features",
                    ("data-preserved",),
                    (200,),
                ),
                (
                    "features-body",
                    "features.get_features",
                    "GET",
                    "/_features",
                    ("features",),
                    (400,),
                ),
                (
                    "features-after",
                    "features.get_features",
                    "GET",
                    "/_features",
                    ("features-body",),
                    (200,),
                ),
            ]
        )
    if version in {
        "7.16.3",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
        "8.9.2",
        "8.10.4",
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
    }:
        specs.extend(
            [
                (
                    "modify-empty",
                    "indices.modify_data_stream",
                    "POST",
                    "/_data_stream/_modify",
                    ("data-preserved",),
                    (400,),
                ),
                (
                    "modify-add-absent",
                    "indices.modify_data_stream",
                    "POST",
                    "/_data_stream/_modify",
                    ("modify-empty",),
                    (400,)
                    if version
                    in {
                        "8.2.3",
                        "8.3.3",
                        "8.4.3",
                        "8.5.3",
                        "8.6.2",
                        "8.7.1",
                        "8.8.2",
                        "8.9.2",
                        "8.10.4",
                        "8.11.4",
                        "8.12.2",
                        "8.13.4",
                        "8.14.3",
                        "8.15.5",
                        "8.16.6",
                        "8.17.10",
                        "8.18.8",
                        "9.0.8",
                    }
                    else (404,),
                ),
                (
                    "modify-remove-absent",
                    "indices.modify_data_stream",
                    "POST",
                    "/_data_stream/_modify",
                    ("modify-add-absent",),
                    (400,)
                    if version
                    in {
                        "8.2.3",
                        "8.3.3",
                        "8.4.3",
                        "8.5.3",
                        "8.6.2",
                        "8.7.1",
                        "8.8.2",
                        "8.9.2",
                        "8.10.4",
                        "8.11.4",
                        "8.12.2",
                        "8.13.4",
                        "8.14.3",
                        "8.15.5",
                        "8.16.6",
                        "8.17.10",
                        "8.18.8",
                        "9.0.8",
                    }
                    else (404,),
                ),
                (
                    "modify-data-preserved",
                    "count",
                    "GET",
                    "/{index}/_count",
                    ("modify-remove-absent",),
                    (200,),
                ),
            ]
        )
    graph = {}
    if version in {"8.14.3", "8.15.5", "8.16.6", "8.17.10", "8.18.8", "9.0.8", "8.13.4"}:
        for name, path in [
            ("cluster-index", "/_resolve/cluster/{index}"),
            ("cluster-alias", "/_resolve/cluster/{alias}"),
            ("cluster-missing", "/_resolve/cluster/{missing_uuid}"),
            ("cluster-wildcard", "/_resolve/cluster/{missing_uuid}*?allow_no_indices=true"),
        ]:
            specs.append((name, "indices.resolve_cluster", "GET", path, ("resolve-alias",), (200,)))
        specs.append(
            (
                "cluster-count",
                "count",
                "GET",
                "/{index}/_count",
                ("cluster-index", "cluster-alias", "cluster-missing", "cluster-wildcard"),
                (200,),
            )
        )
    if version == "9.0.8":
        specs.extend(
            [
                (
                    "search-min-omitted",
                    "search",
                    "GET",
                    "/{index}/_search",
                    ("data-preserved",),
                    (200,),
                ),
                (
                    "search-min-future",
                    "search",
                    "GET",
                    "/{index}/_search?min_compatible_shard_node=99.0.0",
                    ("search-bad-version",),
                    (200,),
                ),
            ]
        )
    if version in {"8.18.8", "9.0.8"}:
        specs.extend(
            [
                (
                    "cluster-remotes-empty",
                    "cluster.remote_info",
                    "GET",
                    "/_remote/info",
                    ("resolve-alias",),
                    (200,),
                ),
                (
                    "cluster-all",
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster",
                    ("cluster-remotes-empty",),
                    (200,),
                ),
                (
                    "cluster-all-timeout",
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster?timeout=1s",
                    ("cluster-all",),
                    (200,),
                ),
                (
                    "cluster-all-bad-timeout",
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster?timeout=garbage",
                    ("cluster-all-timeout",),
                    (400,),
                ),
                (
                    "cluster-all-body",
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster",
                    ("cluster-all",),
                    (400,),
                ),
                (
                    "cluster-all-after",
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster",
                    ("cluster-all-body",),
                    (200,),
                ),
                (
                    "cluster-all-count",
                    "count",
                    "GET",
                    "/{index}/_count",
                    ("cluster-all-after",),
                    (200,),
                ),
            ]
        )
        for param, value in [
            ("expand_wildcards", "open"),
            ("allow_no_indices", "true"),
            ("ignore_unavailable", "true"),
        ]:
            specs.append(
                (
                    "cluster-all-option-" + param,
                    "indices.resolve_cluster",
                    "GET",
                    "/_resolve/cluster?" + param + "=" + value,
                    ("cluster-all",),
                    (400,),
                )
            )
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
        if catalog.version in {
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
            "8.13.4",
        }:
            for name in ["cluster-index", "cluster-alias", "cluster-wildcard"]:
                call(
                    name,
                    assertions=[
                        ("only local cluster", lambda d: sorted(d), ["(local)"]),
                        ("local connected", lambda d: d["(local)"]["connected"], True),
                        ("local never skipped", lambda d: d["(local)"]["skip_unavailable"], False),
                        (
                            "actual matching state",
                            lambda d: d["(local)"]["matching_indices"],
                            name != "cluster-wildcard",
                        ),
                        (
                            "exact local release",
                            lambda d: d["(local)"]["version"]["number"],
                            catalog.version,
                        ),
                    ],
                )
            call(
                "cluster-missing",
                assertions=[
                    (
                        "local exact missing is embedded error",
                        lambda d: values["missing_uuid"] in d["(local)"]["error"],
                        True,
                    ),
                    (
                        "local stays connected despite missing index",
                        lambda d: d["(local)"]["connected"],
                        True,
                    ),
                    (
                        "matching flag absent on error",
                        lambda d: "matching_indices" in d["(local)"],
                        False,
                    ),
                ],
            )
            call(
                "cluster-count",
                assertions=[("resolution writes no documents", lambda d: d["count"], 1)],
                verifies=("cluster-index", "cluster-alias", "cluster-missing", "cluster-wildcard"),
            )
        if catalog.version in {"8.18.8", "9.0.8"}:
            empty = [("no configured remote clusters, no implicit local entry", lambda d: d, {})]
            call(
                "cluster-remotes-empty",
                assertions=[("isolated lab remote configuration empty", lambda d: d, {})],
            )
            call("cluster-all", assertions=empty)
            call("cluster-all-timeout", assertions=empty)
            call(
                "cluster-all-bad-timeout",
                assertions=[
                    (
                        "timeout must parse",
                        lambda d: "timeout" in str(d["error"]) and "garbage" in str(d["error"]),
                        True,
                    )
                ],
            )
            for param in ["expand_wildcards", "allow_no_indices", "ignore_unavailable"]:
                call(
                    "cluster-all-option-" + param,
                    assertions=[
                        (
                            "index options forbidden without index expression",
                            lambda d, param=param: (
                                "No index options are allowed" in str(d["error"])
                                and param in str(d["error"])
                            ),
                            True,
                        )
                    ],
                )
            call(
                "cluster-all-body",
                {"unused": True},
                [
                    (
                        "unused body refused",
                        lambda d: "does not support having a body" in str(d["error"]),
                        True,
                    )
                ],
            )
            call(
                "cluster-all-after",
                assertions=empty,
                verifies=("cluster-all-body", "cluster-all-bad-timeout"),
            )
            call(
                "cluster-all-count",
                assertions=[("resolve-only calls preserve ordinary data", lambda d: d["count"], 1)],
                verifies=("cluster-all", "cluster-all-timeout", "cluster-all-body"),
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
        if catalog.version in {
            "7.16.3",
            "8.0.1",
            "8.1.3",
            "8.2.3",
            "8.3.3",
            "8.4.3",
            "8.5.3",
            "8.6.2",
            "8.7.1",
            "8.8.2",
            "8.9.2",
            "8.10.4",
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
        }:
            call(
                "modify-empty",
                {"actions": []},
                [
                    (
                        "empty action list refused",
                        lambda d: d["error"]["reason"],
                        "no data stream actions specified, at least one must be specified",
                    )
                ],
            )
            for name, action in [
                ("modify-add-absent", "add_backing_index"),
                ("modify-remove-absent", "remove_backing_index"),
            ]:
                missing = prefix + "-absent-stream"
                call(
                    name,
                    {"actions": [{action: {"data_stream": missing, "index": values["index"]}}]},
                    [
                        (
                            "absent data stream rejected",
                            lambda d, missing=missing: d["error"]["reason"],
                            (
                                "data stream [" + missing + "] not found"
                                if catalog.version
                                in {
                                    "8.2.3",
                                    "8.3.3",
                                    "8.4.3",
                                    "8.5.3",
                                    "8.6.2",
                                    "8.7.1",
                                    "8.8.2",
                                    "8.9.2",
                                    "8.10.4",
                                    "8.11.4",
                                    "8.12.2",
                                    "8.13.4",
                                    "8.14.3",
                                    "8.15.5",
                                    "8.16.6",
                                    "8.17.10",
                                    "8.18.8",
                                    "9.0.8",
                                }
                                else "no such index [" + missing + "]"
                            ),
                        ),
                        (
                            "error identifies actual rejection stage",
                            lambda d: d["error"]["type"],
                            "illegal_argument_exception"
                            if catalog.version
                            in {
                                "8.2.3",
                                "8.3.3",
                                "8.4.3",
                                "8.5.3",
                                "8.6.2",
                                "8.7.1",
                                "8.8.2",
                                "8.9.2",
                                "8.10.4",
                                "8.11.4",
                                "8.12.2",
                                "8.13.4",
                                "8.14.3",
                                "8.15.5",
                                "8.16.6",
                                "8.17.10",
                                "8.18.8",
                                "9.0.8",
                            }
                            else "index_not_found_exception",
                        ),
                    ],
                )
            call(
                "modify-data-preserved",
                assertions=[("both ordinary docs survive refusal", lambda d: d["count"], 2)],
                verifies=("modify-empty", "modify-add-absent", "modify-remove-absent"),
            )

        if catalog.version in {
            "7.12.1",
            "7.13.4",
            "7.14.2",
            "7.15.2",
            "7.16.3",
            "8.0.1",
            "8.1.3",
            "8.2.3",
            "8.3.3",
            "8.4.3",
            "8.5.3",
            "8.6.2",
            "8.7.1",
            "8.8.2",
            "8.9.2",
            "8.10.4",
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
        }:
            if catalog.version == "9.0.8":
                call(
                    "search-min-omitted",
                    assertions=[
                        (
                            "omitted old-client parameter baseline",
                            lambda d: sorted(h["_id"] for h in d["hits"]["hits"]),
                            ["one", "two"],
                        )
                    ],
                )
            call(
                "search-compatible",
                assertions=[
                    (
                        "current-version minimum still finds both owned docs",
                        lambda d: sorted(h["_id"] for h in d["hits"]["hits"]),
                        ["one", "two"],
                    )
                ],
            )
            if catalog.version == "9.0.8":
                for name in ["search-bad-version", "search-min-future"]:
                    call(
                        name,
                        assertions=[
                            (
                                "old-client min parameter consumed and ignored",
                                lambda d: sorted(h["_id"] for h in d["hits"]["hits"]),
                                ["one", "two"],
                            )
                        ],
                        verifies=("search-min-omitted",),
                    )
            else:
                call(
                    "search-bad-version",
                    assertions=[
                        (
                            "invalid version string refused",
                            lambda d: d["error"]["type"],
                            "illegal_argument_exception",
                        ),
                        (
                            "error retains supplied version",
                            lambda d: "es-cli-invalid" in str(d["error"]),
                            True,
                        ),
                    ],
                )
        if catalog.version in {
            "7.12.1",
            "7.13.4",
            "7.14.2",
            "7.15.2",
            "7.16.3",
            "8.0.1",
            "8.1.3",
            "8.2.3",
            "8.3.3",
            "8.4.3",
            "8.5.3",
            "8.6.2",
            "8.7.1",
            "8.8.2",
            "8.9.2",
            "8.10.4",
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
        }:
            result = call(
                "features",
                assertions=[
                    (
                        "distinct named features",
                        lambda d: len({f["name"] for f in d["features"]}) == len(d["features"]) > 0,
                        True,
                    ),
                    (
                        "feature descriptions",
                        lambda d: all(
                            isinstance(f["description"], str) and f["description"]
                            for f in d["features"]
                        ),
                        True,
                    ),
                    (
                        "core tasks feature present",
                        lambda d: "tasks" in {f["name"] for f in d["features"]},
                        True,
                    ),
                ],
            )
            call(
                "features-body",
                {"unused": True},
                [
                    (
                        "unused feature body rejected",
                        lambda d: d["error"]["type"],
                        "illegal_argument_exception",
                    ),
                    (
                        "specific feature body refusal",
                        lambda d: d["error"]["reason"],
                        "request [GET /_features] does not support having a body",
                    ),
                ],
            )
            names = sorted(f["name"] for f in result.data["features"]) if result.passed else None
            call(
                "features-after",
                assertions=[
                    (
                        "registry unchanged by body refusal",
                        lambda d: sorted(f["name"] for f in d["features"]),
                        names,
                    )
                ],
                verifies=("features-body",),
            )
    finally:
        call("cleanup")
