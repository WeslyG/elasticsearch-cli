"""Modern missing method/path variants with actual owned state and readbacks."""

from evidence_runner import OMITTED


def declare(add, version):
    if version not in {"8.19.24", "9.5.6"}:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "route-variant." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("route-variant." + item for item in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed",
        "index",
        "PUT",
        "/{index}/_doc/seed?refresh=true",
        ("create",),
        (201,),
        "fixture-setup",
    )
    case("post-id", "index", "POST", "/{index}/_doc/post?refresh=true", ("seed",), (201,))
    case("post-id-read", "get", "GET", "/{index}/_doc/post", ("post-id",), purpose="effect-check")
    case("post-auto", "index", "POST", "/{index}/_doc?refresh=true", ("seed",), (201,))
    case(
        "post-auto-read",
        "get",
        "GET",
        "/{index}/_doc/{autoid}",
        ("post-auto",),
        purpose="effect-check",
    )
    for method in ["GET", "POST"]:
        case(
            "analyze-global-" + method.lower(), "indices.analyze", method, "/_analyze", ("create",)
        )
    case("analyze-index-get", "indices.analyze", "GET", "/{index}/_analyze", ("create",))
    for name, path in [
        ("settings-global", "/_settings"),
        ("settings-name", "/{index}/_settings/index.refresh_interval"),
        ("settings-global-name", "/_settings/index.refresh_interval"),
    ]:
        case(name, "indices.get_settings", "GET", path, ("create",))
    case("settings-put-global", "indices.put_settings", "PUT", "/_settings", ("create",))
    case(
        "settings-effect",
        "indices.get_settings",
        "GET",
        "/{index}/_settings/index.refresh_interval",
        ("settings-put-global",),
        purpose="effect-check",
    )
    case(
        "settings-restore",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings",
        expected=(200,),
        purpose="cleanup",
    )
    for method, path, name in [
        ("POST", "/_flush", "flush-global-post"),
        ("GET", "/_flush", "flush-global-get"),
        ("GET", "/{index}/_flush", "flush-index-get"),
    ]:
        case(name, "indices.flush", method, path, ("post-id-read", "post-auto-read"))
    case(
        "merge-before",
        "indices.segments",
        "GET",
        "/{index}/_segments",
        ("post-id-read", "post-auto-read"),
        purpose="fixture-precondition",
    )
    case(
        "merge-global",
        "indices.forcemerge",
        "POST",
        "/_forcemerge?max_num_segments=1&flush=true",
        ("merge-before",),
    )
    case(
        "merge-effect",
        "indices.segments",
        "GET",
        "/{index}/_segments",
        ("merge-global",),
        purpose="effect-check",
    )
    for method, path, name in [
        ("POST", "/_refresh", "refresh-global-post"),
        ("GET", "/_refresh", "refresh-global-get"),
        ("GET", "/{index}/_refresh", "refresh-index-get"),
    ]:
        case(name, "indices.refresh", method, path, ("post-id-read", "post-auto-read"))
    case(
        "refresh-effect",
        "search",
        "GET",
        "/{index}/_search",
        ("refresh-global-post", "refresh-global-get", "refresh-index-get"),
        purpose="effect-check",
    )
    for api, name, path in [
        ("indices.recovery", "recovery-global", "/_recovery"),
        ("indices.segments", "segments-global", "/_segments"),
        ("indices.shard_stores", "stores-global", "/_shard_stores"),
        ("indices.stats", "stats-global", "/_stats"),
        ("indices.stats", "stats-global-docs", "/_stats/docs"),
        ("indices.stats", "stats-index", "/{index}/_stats"),
    ]:
        case(name, api, "GET", path, ("post-id-read", "post-auto-read"))
    case("repository-post", "snapshot.create_repository", "POST", "/_snapshot/{repo}", ("create",))
    case(
        "snapshot-post",
        "snapshot.create",
        "POST",
        "/_snapshot/{repo}/method?wait_for_completion=true",
        ("repository-post", "refresh-effect"),
    )
    case(
        "snapshot-get",
        "snapshot.get",
        "GET",
        "/_snapshot/{repo}/method",
        ("snapshot-post",),
        purpose="effect-check",
    )
    case(
        "restore",
        "snapshot.restore",
        "POST",
        "/_snapshot/{repo}/method/_restore?wait_for_completion=true",
        ("snapshot-get",),
        purpose="effect-check",
    )
    case(
        "restored-read", "get", "GET", "/{restored}/_doc/seed", ("restore",), purpose="effect-check"
    )
    case(
        "restored-count", "count", "GET", "/{restored}/_count", ("restore",), purpose="effect-check"
    )
    case("rollover", "indices.rollover", "POST", "/{alias}/_rollover/{next}", ("refresh-effect",))
    case(
        "alias-write",
        "index",
        "POST",
        "/{alias}/_doc/alias-one?refresh=true",
        ("rollover",),
        (201,),
        "effect-check",
    )
    case(
        "new-read", "get", "GET", "/{next}/_doc/alias-one", ("alias-write",), purpose="effect-check"
    )
    case(
        "old-absent",
        "get",
        "GET",
        "/{index}/_doc/alias-one",
        ("alias-write",),
        (404,),
        "effect-check",
    )
    case(
        "source-preserved",
        "count",
        "GET",
        "/{index}/_count",
        ("alias-write",),
        purpose="effect-check",
    )
    case("cancel-target", "indices.create", "PUT", "/{target}", purpose="fixture-setup")
    case(
        "launch",
        "reindex",
        "POST",
        "/_reindex?wait_for_completion=false&requests_per_second=0.1",
        ("cancel-target", "source-preserved"),
        purpose="fixture-setup",
    )
    case(
        "running", "tasks.get", "GET", "/_tasks/{task}", ("launch",), purpose="fixture-precondition"
    )
    cancel_path = (
        "/_tasks/_cancel?actions=indices:data/write/reindex&nodes=_local&wait_for_completion=true"
    )
    case("cancel-global", "tasks.cancel", "POST", cancel_path, ("running",))
    case(
        "cancel-completed",
        "tasks.get",
        "GET",
        "/_tasks/{task}?wait_for_completion=true&timeout=15s",
        ("cancel-global",),
        purpose="effect-check",
    )
    case(
        "cancel-refresh",
        "indices.refresh",
        "POST",
        "/{target}/_refresh",
        ("cancel-completed",),
        purpose="effect-check",
    )
    case(
        "cancel-count",
        "count",
        "GET",
        "/{target}/_count",
        ("cancel-refresh",),
        purpose="effect-check",
    )
    case("cancel-cleanup", "tasks.cancel", "POST", cancel_path, purpose="cleanup")
    case(
        "snapshot-delete",
        "snapshot.delete",
        "DELETE",
        "/_snapshot/{repo}/method",
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
    for name in ["index", "target", "restored", "next"]:
        case(
            "cleanup-" + name,
            "indices.delete",
            "DELETE",
            "/{" + name + "}",
            expected=(200, 404),
            purpose="cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-method-000001",
        "alias": prefix + "-method-write",
        "next": prefix + "-method-next",
        "restored": prefix + "-method-restored",
        "target": prefix + "-method-cancel",
        "repo": prefix + "-method-repository",
        "autoid": "not-created",
        "task": "not-launched",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["route-variant." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["route-variant." + item for item in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    shard_checks = [("no failed shard", lambda data: data["_shards"]["failed"], 0)]
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"},
            "mappings": {"properties": {"n": {"type": "integer"}}},
            "aliases": {values["alias"]: {"is_write_index": True}},
        },
        assertions=[("index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        call("seed", {"n": 11})
        call(
            "post-id",
            {"n": 12},
            assertions=[("explicit ID created", lambda data: data["_id"], "post")],
        )
        call(
            "post-id-read",
            assertions=[("actual explicit-ID value", lambda data: data["_source"]["n"], 12)],
            verifies=["post-id"],
            semantic=True,
        )
        generated = call(
            "post-auto",
            {"n": 13},
            assertions=[
                (
                    "auto ID returned",
                    lambda data: isinstance(data.get("_id"), str) and bool(data["_id"]),
                    True,
                )
            ],
        )
        if generated.state == "passed":
            values["autoid"] = generated.data["_id"]
        call(
            "post-auto-read",
            assertions=[("actual auto-ID value", lambda data: data["_source"]["n"], 13)],
            verifies=["post-auto"],
            semantic=True,
        )
        for name in ["analyze-global-get", "analyze-global-post", "analyze-index-get"]:
            call(
                name,
                {"analyzer": "standard", "text": "Alpha Beta"},
                assertions=[
                    (
                        "actual analysis tokens",
                        lambda data: [token["token"] for token in data["tokens"]],
                        ["alpha", "beta"],
                    )
                ],
                semantic=True,
            )
        for name in ["settings-global", "settings-name", "settings-global-name"]:
            call(
                name,
                assertions=[
                    (
                        "owned index setting",
                        lambda data: data[values["index"]]["settings"]["index"]["refresh_interval"],
                        "-1",
                    )
                ],
                semantic=True,
            )
        call(
            "settings-put-global",
            {"index": {"refresh_interval": "30s"}},
            assertions=[("global update acknowledged", lambda data: data["acknowledged"], True)],
        )
        call(
            "settings-effect",
            assertions=[
                (
                    "global update actually applied",
                    lambda data: data[values["index"]]["settings"]["index"]["refresh_interval"],
                    "30s",
                )
            ],
            verifies=["settings-put-global"],
            semantic=True,
        )
        call("settings-restore", {"index": {"refresh_interval": "-1"}})
        for name in ["flush-global-post", "flush-global-get", "flush-index-get"]:
            call(name, assertions=shard_checks)
        call(
            "merge-before",
            assertions=[
                (
                    "multiple segments actually exist before merge",
                    lambda data: (
                        sum(
                            len(copy["segments"])
                            for copies in data["indices"][values["index"]]["shards"].values()
                            for copy in copies
                        )
                        > 1
                    ),
                    True,
                )
            ],
        )
        call("merge-global", assertions=shard_checks)
        call(
            "merge-effect",
            assertions=[
                (
                    "three writes merged into one segment",
                    lambda data: sum(
                        len(copy["segments"])
                        for copies in data["indices"][values["index"]]["shards"].values()
                        for copy in copies
                    ),
                    1,
                )
            ],
            verifies=["merge-global"],
            semantic=True,
        )
        for name in ["refresh-global-post", "refresh-global-get", "refresh-index-get"]:
            call(name, assertions=shard_checks)
        call(
            "refresh-effect",
            {"query": {"match_all": {}}, "sort": ["n"], "size": 10},
            assertions=[
                (
                    "actual visible values",
                    lambda data: [hit["_source"]["n"] for hit in data["hits"]["hits"]],
                    [11, 12, 13],
                )
            ],
            verifies=["refresh-global-post", "refresh-global-get", "refresh-index-get"],
            semantic=True,
        )
        call(
            "recovery-global",
            assertions=[
                (
                    "owned shard recovery completed",
                    lambda data: (
                        all(shard["stage"] == "DONE" for shard in data[values["index"]]["shards"])
                        and bool(data[values["index"]]["shards"])
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "segments-global",
            assertions=[
                (
                    "global segment result contains owned index",
                    lambda data: values["index"] in data["indices"],
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "stores-global",
            assertions=[
                (
                    "owned primary has a store",
                    lambda data: bool(data["indices"][values["index"]]["shards"]["0"]["stores"]),
                    True,
                )
            ],
            semantic=True,
        )
        for name in ["stats-global", "stats-global-docs", "stats-index"]:
            call(
                name,
                assertions=[
                    (
                        "actual document count in primary stats",
                        lambda data: data["_all"]["primaries"]["docs"]["count"],
                        3,
                    )
                ],
                semantic=True,
            )
        call(
            "repository-post",
            {"type": "fs", "settings": {"location": "/tmp/es-snapshots/" + values["repo"]}},
            assertions=[("repository acknowledged", lambda data: data["acknowledged"], True)],
        )
        call(
            "snapshot-post",
            {"indices": values["index"], "include_global_state": False},
            assertions=[
                ("POST snapshot succeeds", lambda data: data["snapshot"]["state"], "SUCCESS"),
                (
                    "only owned index captured",
                    lambda data: data["snapshot"]["indices"],
                    [values["index"]],
                ),
            ],
        )
        call(
            "snapshot-get",
            assertions=[
                (
                    "POST snapshot is retrievable",
                    lambda data: data["snapshots"][0]["state"],
                    "SUCCESS",
                )
            ],
            verifies=["snapshot-post", "repository-post"],
            semantic=True,
        )
        call(
            "restore",
            {
                "indices": values["index"],
                "include_global_state": False,
                "include_aliases": False,
                "rename_pattern": "(.+)",
                "rename_replacement": values["restored"],
            },
            assertions=[
                ("restore no failed shards", lambda data: data["snapshot"]["shards"]["failed"], 0)
            ],
        )
        call(
            "restored-read",
            assertions=[
                ("snapshot contains real original data", lambda data: data["_source"]["n"], 11)
            ],
            verifies=["snapshot-post", "repository-post"],
            semantic=True,
        )
        call(
            "restored-count",
            assertions=[("all three original documents restored", lambda data: data["count"], 3)],
            verifies=["snapshot-post"],
            semantic=True,
        )
        call(
            "rollover",
            {
                "conditions": {"max_docs": 1},
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            },
            assertions=[
                ("actual rollover performed", lambda data: data["rolled_over"], True),
                ("explicit destination index used", lambda data: data["new_index"], values["next"]),
            ],
        )
        call("alias-write", {"n": 99})
        call(
            "new-read",
            assertions=[
                ("alias write reaches explicit new index", lambda data: data["_source"]["n"], 99)
            ],
            verifies=["rollover"],
            semantic=True,
        )
        call("old-absent", verifies=["rollover"])
        call(
            "source-preserved",
            assertions=[("old three documents preserved", lambda data: data["count"], 3)],
            verifies=["rollover"],
            semantic=True,
        )
        call("cancel-target", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
        launched = call(
            "launch",
            {"source": {"index": values["index"], "size": 1}, "dest": {"index": values["target"]}},
            assertions=[
                ("real async task returned", lambda data: isinstance(data.get("task"), str), True)
            ],
        )
        if launched.state == "passed":
            values["task"] = launched.data["task"]
        call(
            "running",
            assertions=[
                ("task still running before global cancel", lambda data: data["completed"], False),
                ("task is cancellable", lambda data: data["task"]["cancellable"], True),
            ],
        )
        call(
            "cancel-global",
            assertions=[
                (
                    "global cancel identifies our task",
                    lambda data: any(
                        identifier == values["task"] and task["cancelled"] is True
                        for node in data["nodes"].values()
                        for identifier, task in node.get("tasks", {}).items()
                    ),
                    True,
                )
            ],
        )
        call(
            "cancel-completed",
            assertions=[
                ("cancelled task completed", lambda data: data["completed"], True),
                (
                    "result has an actual cancellation error",
                    lambda data: "cancel" in str(data.get("error", {})).lower(),
                    True,
                ),
            ],
            verifies=["cancel-global"],
            semantic=True,
        )
        call("cancel-refresh", assertions=shard_checks)
        call(
            "cancel-count",
            assertions=[("cancel stopped full copy", lambda data: 0 <= data["count"] < 3, True)],
            verifies=["cancel-global"],
            semantic=True,
        )
    finally:
        call("cancel-cleanup")
        call("snapshot-delete")
        call("repository-detach")
        for name in ["index", "target", "restored", "next"]:
            call("cleanup-" + name)
