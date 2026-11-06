"""Real quorum changes and dangling index recovery on persistent three-node data."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

from early_voting_family import PREPARED_VERSIONS as EARLY_VOTING_RELEASES
from early_voting_family import declare as declare_early_voting
from early_voting_family import execute as execute_early_voting
from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    if version in EARLY_VOTING_RELEASES:
        return declare_early_voting(add, version)
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("topology." + name, api, method, path, expected=expected, purpose=purpose)
        graph["topology." + name] = tuple("topology." + d for d in deps)

    health = "/_cluster/health?wait_for_nodes={node_count}&timeout=5s"
    coordination = "/_cluster/state/metadata?filter_path=metadata.cluster_coordination"
    case(
        "nodes",
        "nodes.info",
        "GET",
        "/_nodes?filter_path=_nodes,nodes.*.name",
        purpose="fixture-precondition",
    )
    case(
        "initial-coordination",
        "cluster.state",
        "GET",
        coordination,
        ("nodes",),
        purpose="fixture-precondition",
    )
    if version == "8.19.24":
        case(
            "voting-plain-path",
            "cluster.post_voting_config_exclusions_with_node_name_part",
            "POST",
            "/_cluster/voting_config_exclusions/{node_name}",
            ("initial-coordination",),
            (400,),
        )
        case(
            "voting-plain-state",
            "cluster.state",
            "GET",
            coordination,
            ("voting-plain-path",),
            purpose="effect-check",
        )
        case(
            "voting-compat-path",
            "cluster.post_voting_config_exclusions_with_node_name_part",
            "POST",
            "/_cluster/voting_config_exclusions/{node_name}",
            ("voting-plain-state",),
            (400,),
        )
        case(
            "voting-compat-state",
            "cluster.state",
            "GET",
            coordination,
            ("voting-compat-path",),
            purpose="effect-check",
        )
        case(
            "voting-compat-clear",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            "/_cluster/voting_config_exclusions?wait_for_removal=false",
            ("voting-compat-state",),
        )
        case(
            "voting-compat-cleared",
            "cluster.state",
            "GET",
            coordination,
            ("voting-compat-clear",),
            purpose="effect-check",
        )
    case(
        "voting-name",
        "cluster.post_voting_config_exclusions",
        "POST",
        "/_cluster/voting_config_exclusions?node_names={node_name}&timeout=30s",
        ("initial-coordination",),
    )
    case(
        "voting-name-state",
        "cluster.state",
        "GET",
        coordination,
        ("voting-name",),
        purpose="effect-check",
    )
    case(
        "clear-now",
        "cluster.delete_voting_config_exclusions",
        "DELETE",
        "/_cluster/voting_config_exclusions?wait_for_removal=false",
        ("voting-name-state",),
    )
    case(
        "cleared-now", "cluster.state", "GET", coordination, ("clear-now",), purpose="effect-check"
    )
    case(
        "voting-id",
        "cluster.post_voting_config_exclusions",
        "POST",
        "/_cluster/voting_config_exclusions?node_ids={node_id}&timeout=30s",
        ("cleared-now",),
    )
    case(
        "voting-id-state",
        "cluster.state",
        "GET",
        coordination,
        ("voting-id",),
        purpose="effect-check",
    )
    case(
        "two-nodes",
        "cluster.health",
        "GET",
        health,
        ("voting-id-state",),
        purpose="fixture-precondition",
    )
    case(
        "clear-removed",
        "cluster.delete_voting_config_exclusions",
        "DELETE",
        "/_cluster/voting_config_exclusions?wait_for_removal=true",
        ("two-nodes",),
    )
    case(
        "cleared-removed",
        "cluster.state",
        "GET",
        coordination,
        ("clear-removed",),
        purpose="effect-check",
    )
    case(
        "rejoined",
        "cluster.health",
        "GET",
        "/_cluster/health?wait_for_nodes={node_count}&timeout=90s",
        ("cleared-removed",),
        purpose="fixture-precondition",
    )
    case(
        "same-node-id",
        "nodes.info",
        "GET",
        "/_nodes?filter_path=_nodes,nodes.*.name",
        ("rejoined",),
        purpose="fixture-precondition",
    )
    case(
        "docs-before",
        "nodes.stats",
        "GET",
        "/_nodes/{node_id}/stats/indices/docs?filter_path=nodes.*.indices.docs",
        ("initial-coordination",),
        purpose="fixture-precondition",
    )
    for kind in ["keep", "discard"]:
        case(
            "create-" + kind,
            "indices.create",
            "PUT",
            "/{index}",
            ("docs-before",),
            purpose="fixture-setup",
        )
        case(
            "ready-" + kind,
            "cluster.health",
            "GET",
            "/_cluster/health/{index}?wait_for_status=green&timeout=90s",
            ("create-" + kind,),
            purpose="fixture-precondition",
        )
        case(
            "allocation-" + kind,
            "cluster.allocation_explain",
            "GET",
            "/_cluster/allocation/explain",
            ("create-" + kind,),
            purpose="fixture-diagnostic",
        )
        case(
            "seed-" + kind,
            "bulk",
            "POST",
            "/{index}/_bulk?refresh=true",
            ("ready-" + kind,),
            purpose="fixture-setup",
        )
        case(
            "uuid-" + kind,
            "indices.get_settings",
            "GET",
            "/{index}/_settings?flat_settings=true",
            ("ready-" + kind,),
            purpose="fixture-precondition",
        )
        case(
            "flush-" + kind,
            "indices.flush",
            "POST",
            "/{index}/_flush?force=true",
            ("seed-" + kind,),
            purpose="fixture-precondition",
        )
    case(
        "copies-ready",
        "cluster.health",
        "GET",
        "/_cluster/health/{keep_index},{discard_index}?wait_for_status=green&level=indices&timeout=90s",
        ("flush-keep", "flush-discard"),
        purpose="fixture-precondition",
    )
    case(
        "docs-on-c",
        "indices.stats",
        "GET",
        "/{keep_index},{discard_index}/_stats/docs?level=shards",
        ("copies-ready", "uuid-keep", "uuid-discard"),
        purpose="fixture-precondition",
    )
    case(
        "offline-for-loss",
        "cluster.health",
        "GET",
        health,
        ("docs-on-c",),
        purpose="fixture-precondition",
    )
    for kind in ["keep", "discard"]:
        case(
            "delete-" + kind,
            "indices.delete",
            "DELETE",
            "/{index}",
            ("offline-for-loss",),
            purpose="fixture-setup",
        )
    case(
        "create-filler",
        "indices.create",
        "PUT",
        "/{filler_index}",
        ("delete-keep", "delete-discard"),
        purpose="fixture-setup",
    )
    case(
        "delete-filler",
        "indices.delete",
        "DELETE",
        "/{filler_index}",
        ("create-filler",),
        purpose="fixture-setup",
    )
    case(
        "dangling-rejoined",
        "cluster.health",
        "GET",
        "/_cluster/health?wait_for_nodes={node_count}&timeout=90s",
        ("delete-filler",),
        purpose="fixture-precondition",
    )
    for poll in range(20):
        case(
            "poll." + str(poll),
            "dangling_indices.list_dangling_indices",
            "GET",
            "/_dangling",
            ("dangling-rejoined",),
            purpose="fixture-precondition",
        )
    case(
        "dangling-ready",
        "dangling_indices.list_dangling_indices",
        "GET",
        "/_dangling",
        ("poll.*",),
        purpose="fixture-precondition",
    )
    case(
        "import-reject",
        "dangling_indices.import_dangling_index",
        "POST",
        "/_dangling/{keep_uuid}?accept_data_loss=false",
        ("dangling-ready",),
        (400,),
    )
    case(
        "delete-reject",
        "dangling_indices.delete_dangling_index",
        "DELETE",
        "/_dangling/{discard_uuid}?accept_data_loss=false",
        ("dangling-ready",),
        (400,),
    )
    case(
        "rejects-preserved",
        "dangling_indices.list_dangling_indices",
        "GET",
        "/_dangling",
        ("import-reject", "delete-reject"),
        purpose="effect-check",
    )
    case(
        "import",
        "dangling_indices.import_dangling_index",
        "POST",
        "/_dangling/{keep_uuid}?accept_data_loss=true",
        ("rejects-preserved",),
        (202,),
    )
    case(
        "import-ready",
        "cluster.health",
        "GET",
        "/_cluster/health/{keep_index}?wait_for_status=green&timeout=90s",
        ("import",),
        purpose="fixture-precondition",
    )
    case(
        "import-count",
        "count",
        "GET",
        "/{keep_index}/_count",
        ("import-ready",),
        purpose="effect-check",
    )
    case(
        "import-source",
        "get",
        "GET",
        "/{keep_index}/_doc/3",
        ("import-ready",),
        purpose="effect-check",
    )
    case(
        "import-uuid",
        "indices.get_settings",
        "GET",
        "/{keep_index}/_settings?flat_settings=true",
        ("import-ready",),
        purpose="effect-check",
    )
    case(
        "delete-dangling",
        "dangling_indices.delete_dangling_index",
        "DELETE",
        "/_dangling/{discard_uuid}?accept_data_loss=true",
        ("rejects-preserved",),
        (202,),
    )
    case(
        "deleted-not-indexed",
        "indices.exists",
        "HEAD",
        "/{discard_index}",
        ("delete-dangling",),
        (404,),
        purpose="effect-check",
    )
    for poll in range(40):
        case(
            "delete-poll." + str(poll),
            "dangling_indices.list_dangling_indices",
            "GET",
            "/_dangling",
            ("import-ready", "delete-dangling"),
            purpose="fixture-precondition",
        )
    case(
        "no-dangling-left",
        "dangling_indices.list_dangling_indices",
        "GET",
        "/_dangling",
        ("import-ready", "delete-poll.*"),
        purpose="effect-check",
    )
    for kind in ["keep", "discard"]:
        case(
            "cleanup-" + kind,
            "indices.delete",
            "DELETE",
            "/{index}",
            expected=(200, 404),
            purpose="cleanup",
        )
    case(
        "cleanup-voting",
        "cluster.delete_voting_config_exclusions",
        "DELETE",
        "/_cluster/voting_config_exclusions?wait_for_removal=false",
        purpose="cleanup",
    )
    return graph


def execute(run, catalog, prefix, *, dangling_only=False):
    if catalog.version in EARLY_VOTING_RELEASES:
        if dangling_only:
            raise ValueError("Dangling fixture is not prepared for this exact early release")
        return execute_early_voting(run, catalog, prefix)
    nodes = json.loads(os.environ["ES_TOPOLOGY_NODES"])
    lab = os.environ["ES_RESEARCH_LAB"]
    c = nodes["c"]
    values = {
        "node_name": c["name"],
        "node_id": "unavailable",
        "node_count": 3,
        "keep_index": prefix + "-keep",
        "discard_index": prefix + "-discard",
        "filler_index": prefix + "-tombstone-filler",
        "keep_uuid": "unavailable",
        "discard_uuid": "unavailable",
        "index": "unavailable",
    }
    control_file = run.output / "node-control.json"
    controls = {"kind": "explicit-owned-node-control-not-rest-api", "nodes": nodes, "events": []}

    def save():
        control_file.write_text(json.dumps(controls, indent=2) + "\n")

    def control(action, prerequisite):
        event = {
            "action": action,
            "container": c["id"],
            "at": datetime.now(timezone.utc).isoformat(),
            "prerequisite": prerequisite.scenario_id,
        }
        if not prerequisite.passed:
            event["state"] = "blocked"
            controls["events"].append(event)
            save()
            return
        info = json.loads(
            subprocess.check_output(
                ["docker", "container", "inspect", c["id"]], text=True, timeout=10
            )
        )[0]
        if info["Config"].get("Labels", {}).get("io.es-cli.research") != lab:
            raise RuntimeError("Refusing control of a node outside the owned lab")
        arguments = ["docker", action, *(["--time", "15"] if action == "stop" else []), c["id"]]
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        event.update(exit_code=result.returncode, state="executed")
        controls["events"].append(event)
        save()
        if result.returncode:
            raise RuntimeError("Owned topology node control failed: " + result.stderr[-1000:])

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        ndjson=False,
        depends_on=None,
        deadline=None,
    ):
        long_wait = name in {
            "rejoined",
            "dangling-rejoined",
            "copies-ready",
            "import-ready",
            "ready-keep",
            "ready-discard",
        }
        hard_deadline = deadline if deadline is not None else (110 if long_wait else 60)
        case = catalog.cases["topology." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan if depends_on is None else depends_on,
            semantic=semantic,
            verifies=["topology." + n for n in verifies],
            deadline=hard_deadline,
            socket_timeout=min(100 if long_wait else 45, hard_deadline),
            content_type=(
                "application/vnd.elasticsearch+json;compatible-with=7"
                if name == "voting-compat-path"
                else "application/x-ndjson"
                if ndjson
                else "application/json"
            ),
            headers={"Accept": "application/vnd.elasticsearch+json;compatible-with=7"}
            if name == "voting-compat-path"
            else None,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def coord(data):
        return data["metadata"]["cluster_coordination"]

    def exclusion(data):
        return (
            any(
                item["node_id"] == values["node_id"] and item["node_name"] == values["node_name"]
                for item in coord(data)["voting_config_exclusions"]
            )
            and values["node_id"] not in coord(data)["last_committed_config"]
        )

    def doc_count(data):
        return sum(node["indices"]["docs"]["count"] for node in data["nodes"].values())

    def own_dangling(data):
        return sorted(
            row["index_uuid"]
            for row in data["dangling_indices"]
            if row["index_name"] in {values["keep_index"], values["discard_index"]}
        )

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    save()
    response = call(
        "nodes",
        assertions=[
            (
                "three configured node names",
                lambda d: sorted(item["name"] for item in d["nodes"].values()),
                sorted(node["name"] for node in nodes.values()),
            )
        ],
    )
    values["node_id"] = next(
        (
            identifier
            for identifier, node in (response.data or {}).get("nodes", {}).items()
            if node["name"] == c["name"]
        ),
        "unavailable",
    )
    try:
        call(
            "initial-coordination",
            assertions=[
                (
                    "all three node IDs are committed voters",
                    lambda d: sorted(coord(d)["last_committed_config"]),
                    sorted((response.data or {}).get("nodes", {})),
                )
            ],
        )
        if not dangling_only:
            if catalog.version == "8.19.24":
                call(
                    "voting-plain-path",
                    assertions=[
                        ("default media rejects legacy path", lambda d: bool(d.get("error")), True)
                    ],
                )
                call(
                    "voting-plain-state",
                    assertions=[
                        (
                            "rejected legacy request preserved exclusions",
                            lambda d: coord(d)["voting_config_exclusions"],
                            [],
                        )
                    ],
                    verifies=["voting-plain-path"],
                    semantic=True,
                )
                call(
                    "voting-compat-path",
                    assertions=[
                        (
                            "legacy node_name removed despite compatibility media",
                            lambda d: d["error"]["reason"],
                            "[node_name] has been removed, you must set [node_names] or [node_ids]",
                        )
                    ],
                )
                call(
                    "voting-compat-state",
                    assertions=[
                        (
                            "v7 media refusal preserves exclusions",
                            lambda d: coord(d)["voting_config_exclusions"],
                            [],
                        )
                    ],
                    verifies=["voting-compat-path"],
                    semantic=True,
                )
                call("voting-compat-clear")
                call(
                    "voting-compat-cleared",
                    assertions=[
                        (
                            "legacy-path exclusion cleared",
                            lambda d: coord(d)["voting_config_exclusions"],
                            [],
                        )
                    ],
                    verifies=["voting-compat-clear"],
                    semantic=True,
                )
            call("voting-name")
            call(
                "voting-name-state",
                assertions=[("named node excluded from committed voters", exclusion, True)],
                verifies=["voting-name"],
                semantic=True,
            )
            call("clear-now")
            call(
                "cleared-now",
                assertions=[
                    (
                        "exclusions cleared without node removal",
                        lambda d: coord(d)["voting_config_exclusions"],
                        [],
                    )
                ],
                verifies=["clear-now"],
                semantic=True,
            )
            call("voting-id")
            result = call(
                "voting-id-state",
                assertions=[("node ID excluded from committed voters", exclusion, True)],
                verifies=["voting-id"],
                semantic=True,
            )
            control("stop", result)
            values["node_count"] = 2
            call("two-nodes", assertions=[("node really left", lambda d: d["number_of_nodes"], 2)])
            call("clear-removed")
            result = call(
                "cleared-removed",
                assertions=[
                    (
                        "exclusions cleared after removal",
                        lambda d: coord(d)["voting_config_exclusions"],
                        [],
                    )
                ],
                verifies=["clear-removed"],
                semantic=True,
            )
            control("start", result)
            values["node_count"] = 3
            call("rejoined", assertions=[("three nodes again", lambda d: d["number_of_nodes"], 3)])
            call(
                "same-node-id",
                assertions=[
                    (
                        "persistent volume preserves node identity",
                        lambda d: d["nodes"][values["node_id"]]["name"],
                        c["name"],
                    )
                ],
            )
        call(
            "docs-before",
            assertions=[("node document counter available", lambda d: doc_count(d) >= 0, True)],
        )
        for kind in ["keep", "discard"]:
            values["index"] = values[kind + "_index"]
            call(
                "create-" + kind,
                {
                    "settings": {"number_of_shards": 1, "number_of_replicas": 2},
                    "mappings": {"properties": {"n": {"type": "integer"}}},
                },
                ack,
            )
            call("ready-" + kind, assertions=[("all copies green", lambda d: d["status"], "green")])
            call(
                "allocation-" + kind,
                {"index": values["index"], "shard": 0, "primary": False},
                [
                    (
                        "allocation explanation belongs to fixture",
                        lambda d: d["index"],
                        values["index"],
                    )
                ],
            )
            parts = []
            for n in range(20):
                parts.extend([{"index": {"_id": str(n)}}, {"n": n}])
            call(
                "seed-" + kind,
                ("\n".join(json.dumps(p) for p in parts) + "\n").encode(),
                [("seed no errors", lambda d: d["errors"], False)],
                ndjson=True,
            )
            response = call(
                "uuid-" + kind,
                assertions=[
                    (
                        "UUID present",
                        lambda d: bool(d[values["index"]]["settings"]["index.uuid"]),
                        True,
                    )
                ],
            )
            values[kind + "_uuid"] = (
                (response.data or {})
                .get(values["index"], {})
                .get("settings", {})
                .get("index.uuid", "unavailable")
            )
            call(
                "flush-" + kind,
                assertions=[
                    ("all three shard copies flushed", lambda d: d["_shards"]["successful"], 3)
                ],
            )
        call(
            "copies-ready",
            assertions=[
                (
                    "each index has three active copies",
                    lambda d: [
                        d["indices"][values[k + "_index"]]["active_shards"]
                        for k in ["keep", "discard"]
                    ],
                    [3, 3],
                )
            ],
        )
        result = call(
            "docs-on-c",
            assertions=[
                (
                    "each owned index has twenty documents on the offline node",
                    lambda d: {
                        kind: [
                            shard["docs"]["count"]
                            for shard in d["indices"][values[kind + "_index"]]["shards"]["0"]
                            if shard["routing"]["node"] == values["node_id"]
                            and shard["routing"]["state"] == "STARTED"
                        ]
                        for kind in ["keep", "discard"]
                    },
                    {"keep": [20], "discard": [20]},
                )
            ],
        )
        control("stop", result)
        values["node_count"] = 2
        call(
            "offline-for-loss",
            assertions=[
                ("C is offline before metadata deletion", lambda d: d["number_of_nodes"], 2)
            ],
        )
        for kind in ["keep", "discard"]:
            values["index"] = values[kind + "_index"]
            call("delete-" + kind, assertions=ack)
        call(
            "create-filler",
            {"settings": {"number_of_shards": 1, "number_of_replicas": 0}},
            ack,
        )
        filler_deleted = call("delete-filler", assertions=ack)
        control("start", filler_deleted)
        values["node_count"] = 3
        call(
            "dangling-rejoined",
            assertions=[("offline node rejoined", lambda d: d["number_of_nodes"], 3)],
        )
        expected = sorted([values["keep_uuid"], values["discard_uuid"]])
        last = "topology.poll.0"
        for poll in range(20):
            name = "poll." + str(poll)
            response = call(
                name,
                assertions=[
                    ("dangling array", lambda d: isinstance(d["dangling_indices"], list), True)
                ],
            )
            last = "topology." + name
            if not response.passed or own_dangling(response.data) == expected:
                break
            time.sleep(0.25)
        call(
            "dangling-ready",
            depends_on=[last],
            assertions=[("both actual offline index UUIDs are dangling", own_dangling, expected)],
        )
        call(
            "import-reject",
            assertions=[
                (
                    "loss acknowledgement required",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
        call(
            "delete-reject",
            assertions=[
                (
                    "loss acknowledgement required",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
        call(
            "rejects-preserved",
            assertions=[("rejected operations preserve dangling entries", own_dangling, expected)],
            verifies=["import-reject", "delete-reject"],
            semantic=True,
        )
        call("import", assertions=ack)
        call("import-ready", assertions=[("recovered index green", lambda d: d["status"], "green")])
        call(
            "import-count",
            assertions=[("twenty documents recovered from offline data", lambda d: d["count"], 20)],
            verifies=["import"],
            semantic=True,
        )
        call(
            "import-source",
            assertions=[("original document source recovered", lambda d: d["_source"], {"n": 3})],
            verifies=["import"],
            semantic=True,
        )
        call(
            "import-uuid",
            assertions=[
                (
                    "same original index UUID",
                    lambda d: d[values["keep_index"]]["settings"]["index.uuid"],
                    values["keep_uuid"],
                )
            ],
            verifies=["import"],
            semantic=True,
        )
        call("delete-dangling", assertions=ack)
        call("deleted-not-indexed")
        settle_deadline = time.monotonic() + 60
        last_delete_poll = "topology.delete-poll.0"
        for poll in range(40):
            remaining = max(0.1, settle_deadline - time.monotonic())
            response = call(
                "delete-poll." + str(poll),
                assertions=[
                    ("dangling array", lambda d: isinstance(d["dangling_indices"], list), True)
                ],
                deadline=min(10, remaining),
            )
            last_delete_poll = response.scenario_id
            if not response.passed or own_dangling(response.data) == []:
                break
            if time.monotonic() >= settle_deadline:
                break
            time.sleep(min(1, max(0, settle_deadline - time.monotonic())))
        call(
            "no-dangling-left",
            depends_on=["topology.import-ready", last_delete_poll],
            assertions=[("both fixture dangling entries removed", own_dangling, [])],
            verifies=["import", "delete-dangling"],
            semantic=True,
        )
    finally:
        for kind in ["keep", "discard"]:
            values["index"] = values[kind + "_index"]
            call("cleanup-" + kind)
        call("cleanup-voting")
