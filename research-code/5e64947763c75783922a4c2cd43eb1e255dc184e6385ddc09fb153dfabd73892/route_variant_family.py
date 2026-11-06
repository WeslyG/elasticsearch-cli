"""Modern missing method/path variants with actual owned state and readbacks."""

import time

from evidence_runner import OMITTED
from legacy_release_selection import (
    CANCEL_RESPONSE_WITHOUT_CANCELLED_RELEASES,
    CANCEL_WITHOUT_WAIT_RELEASES,
    EARLY_SEVEN_RELEASES,
    ROLLOVER_PREFIXED_RECIPE_RELEASES,
    ROLLOVER_SHORT_SETTINGS_REFUSAL_RELEASES,
    ROUTE_VARIANT_RELEASES,
    TASK_RESULT_DOCUMENT_TYPES,
)


def declare(add, version):
    if version not in ROUTE_VARIANT_RELEASES:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "route-variant." + name
        path = path.replace("{doc_type}", "fixture" if version.startswith("6.") else "_doc")
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("route-variant." + item for item in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed",
        "index",
        "PUT",
        "/{index}/{doc_type}/seed?refresh=true",
        ("create",),
        (201,),
        "fixture-setup",
    )
    case("post-id", "index", "POST", "/{index}/{doc_type}/post?refresh=true", ("seed",), (201,))
    case(
        "post-id-read",
        "get",
        "GET",
        "/{index}/{doc_type}/post",
        ("post-id",),
        purpose="effect-check",
    )
    case("post-auto", "index", "POST", "/{index}/{doc_type}?refresh=true", ("seed",), (201,))
    case(
        "post-auto-read",
        "get",
        "GET",
        "/{index}/{doc_type}/{autoid}",
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
        expected=(200, 404),
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
        "merge-committed",
        "indices.segments",
        "GET",
        "/{index}/_segments",
        ("merge-global",),
        purpose="effect-check",
    )
    case(
        "merge-refresh",
        "indices.refresh",
        "POST",
        "/{index}/_refresh",
        ("merge-committed",),
        purpose="fixture-precondition",
    )
    case(
        "merge-effect",
        "indices.segments",
        "GET",
        "/{index}/_segments",
        ("merge-refresh",),
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
    case(
        "stores-global-all", "indices.shard_stores", "GET", "/_shard_stores?status=all", ("create",)
    )
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
        "restored-read",
        "get",
        "GET",
        "/{restored}/{doc_type}/seed",
        ("restore",),
        purpose="effect-check",
    )
    case(
        "restored-count", "count", "GET", "/{restored}/_count", ("restore",), purpose="effect-check"
    )
    if version in ROLLOVER_SHORT_SETTINGS_REFUSAL_RELEASES:
        case(
            "rollover-unprefixed",
            "indices.rollover",
            "POST",
            "/{alias}/_rollover/{next}",
            ("refresh-effect",),
            (400,),
        )
        case(
            "rollover-refusal-alias",
            "indices.get_alias",
            "GET",
            "/{alias}/_alias/{alias}",
            ("rollover-unprefixed",),
            purpose="effect-check",
        )
        case(
            "rollover-refusal-next",
            "indices.exists",
            "HEAD",
            "/{next}",
            ("rollover-unprefixed",),
            (404,),
            purpose="effect-check",
        )
        case(
            "rollover-refusal-count",
            "count",
            "GET",
            "/{index}/_count",
            ("rollover-unprefixed",),
            purpose="effect-check",
        )
    if version in {
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
    }:
        for name, expected in [
            ("rollover-min-only", (400,)),
            ("rollover-min-unmet", (200,)),
            ("rollover-max-unmet", (200,)),
        ]:
            case(
                name,
                "indices.rollover",
                "POST",
                "/{alias}/_rollover/{next}",
                ("refresh-effect",),
                expected,
            )
        conditions = ("rollover-min-only", "rollover-min-unmet", "rollover-max-unmet")
        case(
            "rollover-min-preserved-alias",
            "indices.get_alias",
            "GET",
            "/{alias}/_alias/{alias}",
            conditions,
            purpose="effect-check",
        )
        case(
            "rollover-min-preserved-next",
            "indices.exists",
            "HEAD",
            "/{next}",
            conditions,
            (404,),
            "effect-check",
        )
        case(
            "rollover-min-preserved-count",
            "count",
            "GET",
            "/{index}/_count",
            conditions,
            purpose="effect-check",
        )
    case(
        "rollover",
        "indices.rollover",
        "POST",
        "/{alias}/_rollover" if version.startswith("6.") else "/{alias}/_rollover/{next}",
        ("rollover-refusal-alias", "rollover-refusal-next", "rollover-refusal-count")
        if version in ROLLOVER_SHORT_SETTINGS_REFUSAL_RELEASES
        else (
            (
                "rollover-min-preserved-alias",
                "rollover-min-preserved-next",
                "rollover-min-preserved-count",
            )
            if version
            in {
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
            }
            else ("refresh-effect",)
        ),
    )
    case(
        "alias-write",
        "index",
        "POST",
        "/{alias}/{doc_type}/alias-one?refresh=true",
        ("rollover",),
        (201,),
        "effect-check",
    )
    case(
        "new-read",
        "get",
        "GET",
        "/{next}/{doc_type}/alias-one",
        ("alias-write",),
        purpose="effect-check",
    )
    case(
        "old-absent",
        "get",
        "GET",
        "/{index}/{doc_type}/alias-one",
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
    if version in {
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
    }:
        case(
            "implicit-rollover",
            "indices.rollover",
            "POST",
            "/{alias}/_rollover",
            ("new-read", "old-absent", "source-preserved"),
        )
        case(
            "implicit-write",
            "index",
            "POST",
            "/{alias}/_doc/auto-next?refresh=true",
            ("implicit-rollover",),
            (201,),
            "effect-check",
        )
        case(
            "implicit-read",
            "get",
            "GET",
            "/{auto_next}/_doc/auto-next",
            ("implicit-write",),
            purpose="effect-check",
        )
        case(
            "implicit-old-preserved",
            "get",
            "GET",
            "/{next}/_doc/alias-one",
            ("implicit-read",),
            purpose="effect-check",
        )
        case(
            "cleanup-auto-next",
            "indices.delete",
            "DELETE",
            "/{auto_next}",
            expected=(200, 404),
            purpose="cleanup",
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
    for number in range(20):
        case(
            "running-poll-" + str(number),
            "tasks.get",
            "GET",
            "/_tasks/{task}",
            ("launch",),
            purpose="fixture-precondition",
        )
    case(
        "running", "tasks.get", "GET", "/_tasks/{task}", ("launch",), purpose="fixture-precondition"
    )
    cancel_path = (
        "/_tasks/_cancel?actions=indices:data/write/reindex&nodes=_local&wait_for_completion=true"
    )
    if version in CANCEL_WITHOUT_WAIT_RELEASES:
        cancel_path = "/_tasks/_cancel?actions=indices:data/write/reindex&nodes=_local"
    if version in {
        "6.4.3",
        "6.5.4",
        "6.6.2",
        "6.7.2",
        "6.8.23",
        "7.0.1",
        "7.1.1",
        "7.2.1",
        "7.3.2",
        "7.4.2",
        "7.5.2",
        "7.6.2",
        "7.7.1",
        "7.8.1",
    }:
        cancel_path += "&group_by=none"
    case("cancel-global", "tasks.cancel", "POST", cancel_path, ("running",))
    case(
        "cancel-completed",
        "tasks.get",
        "GET",
        "/_tasks/{task}?wait_for_completion=true&timeout=15s",
        ("cancel-global",),
        purpose="effect-check",
    )
    if version in EARLY_SEVEN_RELEASES:
        case(
            "task-result-read",
            "get",
            "GET",
            "/.tasks/task/{task}",
            ("cancel-completed",),
            purpose="effect-check",
        )
        case(
            "task-result-absent",
            "get",
            "GET",
            "/.tasks/task/{task}",
            ("task-result-delete",),
            (404,),
            "effect-check",
        )
    if version in {"7.14.2", "7.15.2", "7.16.3"}:
        case(
            "stored-task-public-get",
            "tasks.get",
            "GET",
            "/_tasks/{task}",
            ("task-result-read",),
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
        "task-result-delete",
        "delete",
        "DELETE",
        "/.tasks/" + TASK_RESULT_DOCUMENT_TYPES[version] + "/{task}",
        ("launch",),
        (200, 404),
        "cleanup",
    )
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
    if catalog.version not in ROUTE_VARIANT_RELEASES:
        raise ValueError("Method variant fixture is not prepared for this exact release")
    values = {
        "index": prefix + "-method-000001",
        "alias": prefix + "-method-write",
        "next": prefix + ("-method-000002" if catalog.version.startswith("6.") else "-method-next"),
        "restored": prefix + "-method-restored",
        "target": prefix + "-method-cancel",
        "repo": prefix + "-method-repository",
        "doc_type": "fixture" if catalog.version.startswith("6.") else "_doc",
        "autoid": "not-created",
        "task": "not-launched",
    }

    if catalog.version in {
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
    }:
        values["next"] = prefix + "-method-000002"
        values["auto_next"] = prefix + "-method-000003"

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

    def cancelled_task_returned(data):
        if catalog.version in {
            "6.4.3",
            "6.5.4",
            "6.6.2",
            "6.7.2",
            "6.8.23",
            "7.0.1",
            "7.1.1",
            "7.2.1",
            "7.3.2",
            "7.4.2",
            "7.5.2",
            "7.6.2",
            "7.7.1",
            "7.8.1",
        }:
            tasks = data.get("tasks")
            return (
                isinstance(tasks, list)
                and "nodes" not in data
                and any(
                    str(task.get("node")) + ":" + str(task.get("id")) == values["task"]
                    and task.get("cancellable") is True
                    for task in tasks
                )
            )
        return any(
            identifier == values["task"]
            and (
                task.get("cancellable") is True
                if catalog.version in CANCEL_RESPONSE_WITHOUT_CANCELLED_RELEASES
                else task.get("cancelled") is True
            )
            for node in data["nodes"].values()
            for identifier, task in node.get("tasks", {}).items()
        )

    shard_checks = [("no failed shard", lambda data: data["_shards"]["failed"], 0)]
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"},
            "mappings": {"fixture": {"properties": {"n": {"type": "integer"}}}}
            if catalog.version.startswith("6.")
            else {"properties": {"n": {"type": "integer"}}},
            "aliases": {
                values["alias"]: {}
                if catalog.version.startswith("6.")
                else {"is_write_index": True}
            },
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
            "merge-committed",
            assertions=[
                (
                    "one committed primary segment",
                    lambda data: sum(
                        copy["num_committed_segments"]
                        for copies in data["indices"][values["index"]]["shards"].values()
                        for copy in copies
                    ),
                    1,
                ),
                (
                    "committed merged segment contains all three fixture documents",
                    lambda data: sum(
                        segment["num_docs"]
                        for copies in data["indices"][values["index"]]["shards"].values()
                        for copy in copies
                        for segment in copy["segments"].values()
                        if segment["committed"] is True
                    ),
                    3,
                ),
            ],
            verifies=["merge-global"],
            semantic=True,
        )
        call("merge-refresh", assertions=shard_checks)
        call(
            "merge-effect",
            assertions=[
                (
                    "refresh exposes the single merged segment",
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
                ("healthy shard omitted by default status filter", lambda data: data["indices"], {})
            ],
            semantic=True,
        )
        call(
            "stores-global-all",
            assertions=[
                (
                    "status=all exposes owned primary store",
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
                        lambda data: data["indices"][values["index"]]["primaries"]["docs"]["count"],
                        3,
                    ),
                    (
                        "global primary total equals all returned index primary counts",
                        lambda data: (
                            data["_all"]["primaries"]["docs"]["count"]
                            == sum(
                                entry["primaries"]["docs"]["count"]
                                for entry in data["indices"].values()
                            )
                        ),
                        True,
                    ),
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
        rollover_settings = {"number_of_shards": 1, "number_of_replicas": 0}
        if catalog.version in ROLLOVER_SHORT_SETTINGS_REFUSAL_RELEASES:
            call(
                "rollover-unprefixed",
                {"conditions": {"max_docs": 1}, "settings": rollover_settings},
                assertions=[
                    (
                        "native setting prefix refusal",
                        lambda d: (
                            "index.number_of_replicas" in str(d["error"])
                            and "unknown setting" in str(d["error"])
                        ),
                        True,
                    )
                ],
            )
            call(
                "rollover-refusal-alias",
                assertions=[
                    (
                        "alias still references original source",
                        lambda d: sorted(d),
                        [values["index"]],
                    ),
                    (
                        "same alias remains attached",
                        lambda d: values["alias"] in d[values["index"]]["aliases"],
                        True,
                    ),
                ],
                verifies=["rollover-unprefixed"],
                semantic=True,
            )
            call("rollover-refusal-next", verifies=["rollover-unprefixed"])
            call(
                "rollover-refusal-count",
                assertions=[("all three source documents unchanged", lambda d: d["count"], 3)],
                verifies=["rollover-unprefixed"],
                semantic=True,
            )
        if catalog.version in ROLLOVER_PREFIXED_RECIPE_RELEASES:
            rollover_settings = {"index." + k: v for k, v in rollover_settings.items()}
        if catalog.version in {
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
        }:
            call(
                "rollover-min-only",
                {"conditions": {"min_docs": 1}},
                assertions=[
                    (
                        "min-only validation",
                        lambda d: "at least one max_* rollover condition" in str(d["error"]),
                        True,
                    )
                ],
            )
            for name, conditions in [
                ("rollover-min-unmet", {"max_docs": 1, "min_docs": 4}),
                ("rollover-max-unmet", {"max_docs": 4, "min_docs": 1}),
            ]:
                call(
                    name,
                    {"conditions": conditions},
                    assertions=[
                        ("thresholds prevent rollover", lambda d: d["rolled_over"], False),
                        ("original write index", lambda d: d["old_index"], values["index"]),
                        (
                            "one predicate true and one false",
                            lambda d: sorted(d["conditions"].values()),
                            [False, True],
                        ),
                    ],
                )
            call(
                "rollover-min-preserved-alias",
                assertions=[
                    (
                        "original alias survives refused conditions",
                        lambda d: values["alias"] in d[values["index"]]["aliases"],
                        True,
                    )
                ],
                verifies=["rollover-min-only", "rollover-min-unmet", "rollover-max-unmet"],
                semantic=True,
            )
            call(
                "rollover-min-preserved-next",
                verifies=["rollover-min-only", "rollover-min-unmet", "rollover-max-unmet"],
            )
            call(
                "rollover-min-preserved-count",
                assertions=[("three source docs unchanged", lambda d: d["count"], 3)],
                verifies=["rollover-min-only", "rollover-min-unmet", "rollover-max-unmet"],
                semantic=True,
            )
        call(
            "rollover",
            {
                "conditions": {
                    "max_docs": 1,
                    **(
                        {"min_docs": 3}
                        if catalog.version
                        in {
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
                        }
                        else {}
                    ),
                },
                "settings": rollover_settings,
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
        if catalog.version in {
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
        }:
            call(
                "implicit-rollover",
                {"settings": {"number_of_shards": 1, "number_of_replicas": 0}},
                assertions=[
                    ("automatic rollover performed", lambda d: d["rolled_over"], True),
                    ("previous write index identified", lambda d: d["old_index"], values["next"]),
                    ("numeric suffix advanced", lambda d: d["new_index"], values["auto_next"]),
                ],
            )
            call("implicit-write", {"n": 101})
            call(
                "implicit-read",
                assertions=[
                    (
                        "alias write reaches automatically named index",
                        lambda d: d["_source"]["n"],
                        101,
                    )
                ],
                verifies=["implicit-rollover", "implicit-write"],
                semantic=True,
            )
            call(
                "implicit-old-preserved",
                assertions=[
                    ("prior explicit-index document preserved", lambda d: d["_source"]["n"], 99)
                ],
                verifies=["implicit-rollover"],
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
        for number in range(20):
            progress = call(
                "running-poll-" + str(number),
                assertions=[
                    ("task still active", lambda data: data["completed"], False),
                    ("task cancellable", lambda data: data["task"]["cancellable"], True),
                ],
            )
            if progress.state != "passed" or progress.data["task"]["status"]["created"] >= 1:
                break
            time.sleep(0.1)
        call(
            "running",
            assertions=[
                ("task still running before global cancel", lambda data: data["completed"], False),
                ("task is cancellable", lambda data: data["task"]["cancellable"], True),
                (
                    "partial batch actually copied before cancellation",
                    lambda data: 1 <= data["task"]["status"]["created"] < 3,
                    True,
                ),
            ],
        )
        call(
            "cancel-global",
            assertions=[
                (
                    "global cancel identifies our task",
                    cancelled_task_returned,
                    True,
                )
            ],
        )
        completed = call(
            "cancel-completed",
            assertions=[
                ("cancelled task completed", lambda data: data["completed"], True),
                (
                    "response records actual cancellation",
                    lambda data: data["response"]["canceled"],
                    "by user request",
                ),
            ],
            verifies=["cancel-global"],
            semantic=True,
        )
        if catalog.version in EARLY_SEVEN_RELEASES:
            stored = call(
                "task-result-read",
                assertions=[
                    (
                        "native persistent result type is task",
                        lambda d: d["_type"],
                        TASK_RESULT_DOCUMENT_TYPES[catalog.version],
                    ),
                    (
                        "same actual completed task",
                        lambda d: (
                            str(d["_source"]["task"]["node"])
                            + ":"
                            + str(d["_source"]["task"]["id"])
                        ),
                        values["task"],
                    ),
                    (
                        "stored result records actual cancellation",
                        lambda d: d["_source"]["response"]["canceled"],
                        "by user request",
                    ),
                ],
                semantic=True,
            )
        if catalog.version in {"7.14.2", "7.15.2", "7.16.3"}:
            call(
                "stored-task-public-get",
                assertions=[
                    ("completed persisted task", lambda d: d["completed"], True),
                    (
                        "stored source deliberately omits cancelled",
                        lambda d: "cancelled" not in stored.data["_source"]["task"],
                        True,
                    ),
                    (
                        "public stored task defaults cancelled to false",
                        lambda d: d["task"]["cancelled"],
                        False,
                    ),
                    (
                        "real cancellation reason survives",
                        lambda d: d["response"]["canceled"],
                        "by user request",
                    ),
                    (
                        "same task identity",
                        lambda d: str(d["task"]["node"]) + ":" + str(d["task"]["id"]),
                        values["task"],
                    ),
                ],
                verifies=["cancel-global", "task-result-read"],
                semantic=True,
            )
        copied = completed.data["response"]["created"] if completed.state == "passed" else None
        call("cancel-refresh", assertions=shard_checks)
        call(
            "cancel-count",
            assertions=[
                ("cancel stopped full copy", lambda data: 0 <= data["count"] < 3, True),
                (
                    "actual target matches returned partial count",
                    lambda data: data["count"],
                    copied,
                ),
            ],
            verifies=["cancel-global"],
            semantic=True,
        )
    finally:
        if catalog.version in {
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
        }:
            call("cleanup-auto-next")
        call("cancel-cleanup")
        call(
            "task-result-delete",
            assertions=[
                ("owned persistent task document deleted", lambda d: d["result"], "deleted")
            ]
            if catalog.version in EARLY_SEVEN_RELEASES
            else [],
        )
        if catalog.version in EARLY_SEVEN_RELEASES:
            call(
                "task-result-absent",
                assertions=[("deleted native task result absent", lambda d: d["found"], False)],
                verifies=["task-result-delete"],
                semantic=True,
            )
        call("snapshot-delete")
        call("repository-detach")
        for name in ["index", "target", "restored", "next"]:
            call("cleanup-" + name)
