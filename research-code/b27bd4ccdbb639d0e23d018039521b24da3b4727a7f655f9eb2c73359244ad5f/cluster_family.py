"""Single-node cluster diagnostics with a deliberate unassigned replica."""

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("cluster." + name, api, method, path, expected=expected, purpose=purpose)
        graph["cluster." + name] = tuple("cluster." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    for name, path in [("global", "/_cluster/health"), ("index", "/_cluster/health/{index}")]:
        case(
            "health." + name,
            "cluster.health",
            "GET",
            path + "?wait_for_status=yellow&level=shards&timeout=3s",
            ("create",),
        )
    case(
        "health.timeout",
        "cluster.health",
        "GET",
        "/_cluster/health/{index}?wait_for_status=green&timeout=1s",
        ("health.index",),
        (408,),
    )
    for method in ["GET", "POST"]:
        case(
            "allocation." + method.lower(),
            "cluster.allocation_explain",
            method,
            "/_cluster/allocation/explain?include_yes_decisions=true&include_disk_info=true",
            ("health.index",),
        )
    for name, path in [
        ("global", "/_cluster/state"),
        ("metric", "/_cluster/state/metadata"),
        ("index", "/_cluster/state/metadata/{index}"),
    ]:
        case(
            "state." + name,
            "cluster.state",
            "GET",
            path + "?filter_path=metadata.indices.*.settings",
            ("create",),
        )
    for name, path in [("global", "/_cluster/stats"), ("local", "/_cluster/stats/nodes/_local")]:
        case("stats." + name, "cluster.stats", "GET", path, ("create",))
    case("settings.before", "cluster.get_settings", "GET", "/_cluster/settings?flat_settings=true")
    case("settings.put", "cluster.put_settings", "PUT", "/_cluster/settings", ("settings.before",))
    case(
        "settings.after",
        "cluster.get_settings",
        "GET",
        "/_cluster/settings?flat_settings=true",
        ("settings.put",),
        purpose="effect-check",
    )
    case(
        "settings.restore",
        "cluster.put_settings",
        "PUT",
        "/_cluster/settings",
        ("settings.put",),
        purpose="cleanup",
    )
    case(
        "settings.restored",
        "cluster.get_settings",
        "GET",
        "/_cluster/settings?flat_settings=true",
        ("settings.restore",),
        purpose="effect-check",
    )
    case("pending", "cluster.pending_tasks", "GET", "/_cluster/pending_tasks")
    case("remote", "cluster.remote_info", "GET", "/_remote/info")
    case(
        "info",
        "cluster.info",
        "GET",
        "/_info/http,ingest?filter_path=cluster_name,http.current_open,http.total_opened,ingest.total",
    )
    case(
        "reroute",
        "cluster.reroute",
        "POST",
        "/_cluster/reroute?dry_run=true&explain=true&metric=version",
        ("create",),
    )
    for name, path in [
        ("all", "/_health_report"),
        ("shards", "/_health_report/shards_availability"),
    ]:
        case(
            "health-report." + name,
            "health_report",
            "GET",
            path + "?verbose=true",
            ("health.index",),
        )
    case("features", "features.get_features", "GET", "/_features")
    case("script-contexts", "get_script_context", "GET", "/_script_context")
    case("script-languages", "get_script_languages", "GET", "/_script_language")
    for name, path in [
        ("all", "/_nodes"),
        ("local", "/_nodes/_local"),
        ("metrics", "/_nodes/jvm,process"),
        ("local-metrics", "/_nodes/_local/jvm,process"),
    ]:
        case(
            "nodes-info." + name,
            "nodes.info",
            "GET",
            path + "?filter_path=_nodes,nodes.*.version,nodes.*.jvm,nodes.*.process",
        )
    for name, path in [
        ("all", "/_nodes/stats"),
        ("local", "/_nodes/_local/stats"),
        ("metrics", "/_nodes/stats/jvm,process"),
        ("local-metrics", "/_nodes/_local/stats/jvm,process"),
        ("index-metrics", "/_nodes/stats/indices/docs"),
        ("local-index-metrics", "/_nodes/_local/stats/indices/docs"),
    ]:
        case(
            "nodes-stats." + name,
            "nodes.stats",
            "GET",
            path + "?filter_path=_nodes,nodes.*.jvm.mem,nodes.*.process,nodes.*.indices.docs",
        )
    for name, path in [
        ("all", "/_nodes/usage"),
        ("local", "/_nodes/_local/usage"),
        ("metric", "/_nodes/usage/rest_actions"),
        ("local-metric", "/_nodes/_local/usage/rest_actions"),
    ]:
        case("nodes-usage." + name, "nodes.usage", "GET", path)
    for name, path in [("all", "/_nodes/hot_threads"), ("local", "/_nodes/_local/hot_threads")]:
        case(
            "hot-threads." + name,
            "nodes.hot_threads",
            "GET",
            path + "?threads=1&interval=50ms&snapshots=1&ignore_idle_threads=false",
        )
    for name, path in [
        ("all", "/_nodes/reload_secure_settings"),
        ("local", "/_nodes/_local/reload_secure_settings"),
    ]:
        case("reload." + name, "nodes.reload_secure_settings", "POST", path)
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {"index": prefix + "-diagnostic"}
    index = values["index"]

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["cluster." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["cluster." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    call("create", {"settings": {"number_of_shards": 1, "number_of_replicas": 1}}, ack)
    try:
        for name in ["global", "index"]:
            call(
                "health." + name,
                assertions=[
                    ("deliberate yellow cluster", lambda d: d["status"], "yellow"),
                    ("one unassigned replica", lambda d: d["unassigned_shards"], 1),
                    ("wait completed", lambda d: d["timed_out"], False),
                ],
                semantic=True,
            )
        call(
            "health.timeout",
            assertions=[
                ("green wait actually timed out", lambda d: d["timed_out"], True),
                ("degraded status retained", lambda d: d["status"], "yellow"),
            ],
        )
        for method in ["get", "post"]:
            call(
                "allocation." + method,
                {"index": index, "shard": 0, "primary": False},
                [
                    ("replica unassigned", lambda d: d["current_state"], "unassigned"),
                    ("allocation refused on only node", lambda d: d["can_allocate"], "no"),
                    (
                        "same-shard explanation exists",
                        lambda d: any(
                            decision["decider"] == "same_shard" and decision["decision"] == "NO"
                            for node in d["node_allocation_decisions"]
                            for decision in node["deciders"]
                        ),
                        True,
                    ),
                ],
                semantic=True,
            )
        for name in ["global", "metric", "index"]:
            call(
                "state." + name,
                assertions=[
                    ("fixture metadata exists", lambda d: index in d["metadata"]["indices"], True)
                ],
            )
        for name in ["global", "local"]:
            call(
                "stats." + name,
                assertions=[("one node", lambda d: d["nodes"]["count"]["total"], 1)],
            )
        call(
            "settings.before",
            assertions=[
                (
                    "fixture setting originally absent",
                    lambda d: "cluster.max_shards_per_node" not in d["persistent"],
                    True,
                )
            ],
        )
        call("settings.put", {"persistent": {"cluster.max_shards_per_node": 2000}}, ack)
        call(
            "settings.after",
            assertions=[
                (
                    "persistent setting read back",
                    lambda d: d["persistent"]["cluster.max_shards_per_node"],
                    "2000",
                )
            ],
            verifies=["settings.put"],
            semantic=True,
        )
        call(
            "pending",
            assertions=[("task list shape", lambda d: isinstance(d["tasks"], list), True)],
        )
        call("remote", assertions=[("no remote clusters configured", lambda d: d, {})])
        call(
            "info",
            assertions=[
                (
                    "aggregated HTTP and ingest sections",
                    lambda d: "http" in d and "ingest" in d,
                    True,
                )
            ],
        )
        call(
            "reroute",
            {"commands": []},
            [
                (
                    "empty dry-run response",
                    lambda d: {
                        "acknowledged": d["acknowledged"],
                        "explanations": d["explanations"],
                    },
                    {"acknowledged": True, "explanations": []},
                )
            ],
        )
        for name in ["all", "shards"]:
            call(
                "health-report." + name,
                assertions=[
                    (
                        "replica accounting and diagnosis",
                        lambda d: {
                            "replicas": d["indicators"]["shards_availability"]["details"][
                                "creating_replicas"
                            ]
                            + d["indicators"]["shards_availability"]["details"][
                                "unassigned_replicas"
                            ],
                            "diagnosed": any(
                                index in item.get("affected_resources", {}).get("indices", [])
                                for item in d["indicators"]["shards_availability"].get(
                                    "diagnosis", []
                                )
                            ),
                        },
                        {"replicas": 1, "diagnosed": True},
                    )
                ],
                semantic=True,
            )
        call(
            "features",
            assertions=[
                ("feature catalogue is a list", lambda d: isinstance(d["features"], list), True)
            ],
        )
        call(
            "script-contexts",
            assertions=[
                (
                    "score context exists",
                    lambda d: any(c["name"] == "score" for c in d["contexts"]),
                    True,
                )
            ],
        )
        call(
            "script-languages",
            assertions=[
                (
                    "Painless supported",
                    lambda d: any(c["language"] == "painless" for c in d["language_contexts"]),
                    True,
                )
            ],
        )
        for family, names in [
            ("nodes-info", ["all", "local", "metrics", "local-metrics"]),
            (
                "nodes-stats",
                [
                    "all",
                    "local",
                    "metrics",
                    "local-metrics",
                    "index-metrics",
                    "local-index-metrics",
                ],
            ),
            ("nodes-usage", ["all", "local", "metric", "local-metric"]),
        ]:
            for name in names:
                call(
                    family + "." + name,
                    assertions=[
                        ("one successful node", lambda d: d["_nodes"]["successful"], 1),
                        ("one node entry", lambda d: len(d["nodes"]), 1),
                    ],
                )
        for name in ["all", "local"]:
            call(
                "hot-threads." + name,
                assertions=[
                    (
                        "plain text report",
                        lambda d: isinstance(d, str) and "Hot threads at" in d,
                        True,
                    )
                ],
            )
            call(
                "reload." + name,
                {},
                [
                    ("no reload failures", lambda d: d["_nodes"]["failed"], 0),
                    (
                        "no per-node exception",
                        lambda d: all("reload_exception" not in n for n in d["nodes"].values()),
                        True,
                    ),
                ],
            )
    finally:
        call("settings.restore", {"persistent": {"cluster.max_shards_per_node": None}}, ack)
        call(
            "settings.restored",
            assertions=[
                (
                    "setting removed",
                    lambda d: "cluster.max_shards_per_node" not in d["persistent"],
                    True,
                )
            ],
            verifies=["settings.restore"],
            semantic=True,
        )
        call("cleanup")
