"""Exact reviewed early-7 voting path contracts on an owned three-master-node fixture."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

PREPARED_VERSIONS = {"7.0.1", "7.1.1"}
ADD_API = "cluster.post_voting_config_exclusions_with_node_name_part"
CLEAR_API = "cluster.delete_voting_config_exclusions"
STATE = "/_cluster/state?filter_path=master_node,nodes,metadata.cluster_coordination"
POLLS = 20


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "topology." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("topology." + value for value in deps)

    def polls(stem, prerequisite):
        for number in range(POLLS):
            previous = prerequisite if number == 0 else stem + "." + str(number - 1)
            case(
                stem + "." + str(number),
                "cluster.state",
                "GET",
                STATE,
                (previous,),
                purpose="fixture-precondition",
            )

    case(
        "nodes",
        "nodes.info",
        "GET",
        "/_nodes?filter_path=_nodes,nodes.*.name",
        purpose="fixture-precondition",
    )
    polls("initial-poll", "nodes")
    case(
        "initial-ready",
        "cluster.state",
        "GET",
        STATE,
        ("initial-poll.*",),
        purpose="fixture-precondition",
    )
    case(
        "absent",
        ADD_API,
        "POST",
        "/_cluster/voting_config_exclusions/{absent_name}?timeout=1s",
        ("initial-ready",),
        (400,),
    )
    case("absent-state", "cluster.state", "GET", STATE, ("absent",), purpose="effect-check")
    case(
        "negative-timeout",
        ADD_API,
        "POST",
        "/_cluster/voting_config_exclusions/{node_name}?timeout=-1s",
        ("absent-state",),
        (400,),
    )
    case(
        "timeout-state",
        "cluster.state",
        "GET",
        STATE,
        ("negative-timeout",),
        purpose="effect-check",
    )
    case(
        "add-name",
        ADD_API,
        "POST",
        "/_cluster/voting_config_exclusions/{node_name}?timeout=30s",
        ("timeout-state",),
    )
    case("name-state", "cluster.state", "GET", STATE, ("add-name",), purpose="effect-check")
    case(
        "duplicate",
        ADD_API,
        "POST",
        "/_cluster/voting_config_exclusions/{node_name},{node_name}?timeout=30s",
        ("name-state",),
    )
    case("duplicate-state", "cluster.state", "GET", STATE, ("duplicate",), purpose="effect-check")
    case(
        "clear-present",
        CLEAR_API,
        "DELETE",
        "/_cluster/voting_config_exclusions?wait_for_removal=false",
        ("duplicate-state",),
    )
    polls("restore-poll", "clear-present")
    case("restored", "cluster.state", "GET", STATE, ("restore-poll.*",), purpose="effect-check")
    case(
        "add-id",
        ADD_API,
        "POST",
        "/_cluster/voting_config_exclusions/{node_id}?timeout=30s",
        ("restored",),
    )
    case("id-state", "cluster.state", "GET", STATE, ("add-id",), purpose="effect-check")
    health = "/_cluster/health?wait_for_nodes={node_count}&timeout=90s"
    case(
        "two-nodes", "cluster.health", "GET", health, ("id-state",), purpose="fixture-precondition"
    )
    case("clear-removed", CLEAR_API, "DELETE", "/_cluster/voting_config_exclusions", ("two-nodes",))
    case("removed-state", "cluster.state", "GET", STATE, ("clear-removed",), purpose="effect-check")
    case(
        "rejoined",
        "cluster.health",
        "GET",
        health,
        ("removed-state",),
        purpose="fixture-precondition",
    )
    polls("final-poll", "rejoined")
    case("final-ready", "cluster.state", "GET", STATE, ("final-poll.*",), purpose="effect-check")
    case("clear-empty", CLEAR_API, "DELETE", "/_cluster/voting_config_exclusions", ("final-ready",))
    case("empty-state", "cluster.state", "GET", STATE, ("clear-empty",), purpose="effect-check")
    case(
        "cleanup-clear",
        CLEAR_API,
        "DELETE",
        "/_cluster/voting_config_exclusions?wait_for_removal=false",
        ("initial-ready",),
        purpose="fixture-cleanup",
    )
    case(
        "cleanup-state",
        "cluster.state",
        "GET",
        STATE,
        ("cleanup-clear",),
        purpose="fixture-cleanup",
    )
    return graph


def coordination(data):
    value = data["metadata"]["cluster_coordination"]
    return {
        "accepted": sorted(value["last_accepted_config"]),
        "committed": sorted(value["last_committed_config"]),
        "exclusions": sorted(value["voting_config_exclusions"], key=lambda item: item["node_id"]),
    }


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Early voting fixture is not prepared for this exact release")
    nodes = json.loads(os.environ["ES_TOPOLOGY_NODES"])
    lab = os.environ["ES_RESEARCH_LAB"]
    values = {
        "absent_name": prefix + "-absent-master",
        "node_name": "unavailable",
        "node_id": "unavailable",
        "node_count": 3,
    }
    control_file = run.output / "node-control.json"
    controls = {"kind": "explicit-owned-node-control-not-rest-api", "nodes": nodes, "events": []}
    target = None
    stopped = False

    def save_controls():
        control_file.write_text(json.dumps(controls, indent=2) + "\n")

    def control(action, prerequisite=None, *, cleanup=False):
        event = {
            "action": action,
            "container": target["id"],
            "at": datetime.now(timezone.utc).isoformat(),
            "prerequisite": prerequisite.scenario_id if prerequisite else None,
            "purpose": "cleanup" if cleanup else "fixture-control",
        }
        if not cleanup and not prerequisite.passed:
            event["state"] = "blocked"
            controls["events"].append(event)
            save_controls()
            return False
        info = json.loads(
            subprocess.check_output(
                ["docker", "container", "inspect", target["id"]], text=True, timeout=10
            )
        )[0]
        if info["Config"].get("Labels", {}).get("io.es-cli.research") != lab:
            raise RuntimeError("Refusing node control outside the owned lab")
        arguments = [
            "docker",
            action,
            *(["--time", "15"] if action == "stop" else []),
            target["id"],
        ]
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=35)
        event.update(exit_code=result.returncode, state="executed")
        controls["events"].append(event)
        save_controls()
        if result.returncode:
            raise RuntimeError("Owned early voting node control failed: " + result.stderr[-1000:])
        return True

    def call(name, assertions=(), verifies=(), depends_on=None):
        case = catalog.cases["topology." + name]
        long_wait = name in {"two-nodes", "rejoined"}
        return catalog.execute(
            run,
            case.id,
            values=values,
            assertions=assertions,
            depends_on=case.dependency_plan if depends_on is None else depends_on,
            verifies=["topology." + value for value in verifies],
            semantic=bool(verifies),
            deadline=110 if long_wait else 45,
            socket_timeout=100 if long_wait else 35,
        )

    def poll(stem, expected):
        last = None
        for number in range(POLLS):
            result = call(
                stem + "." + str(number),
                [
                    (
                        "coordination object",
                        lambda data: isinstance(
                            data.get("metadata", {}).get("cluster_coordination"), dict
                        ),
                        True,
                    )
                ],
            )
            last = result.scenario_id
            if not result.passed or coordination(result.data) == expected:
                break
            time.sleep(0.25)
        return last

    save_controls()
    information = call(
        "nodes",
        [
            (
                "exact owned node names",
                lambda data: sorted(row["name"] for row in data["nodes"].values()),
                sorted(row["name"] for row in nodes.values()),
            )
        ],
    )
    if not information.passed:
        return
    identities = {row["name"]: identifier for identifier, row in information.data["nodes"].items()}
    original_ids = sorted(identities.values())
    original = {"accepted": original_ids, "committed": original_ids, "exclusions": []}
    last = poll("initial-poll", original)
    initial = call(
        "initial-ready",
        [("three actual committed/accepted voters and no exclusions", coordination, original)],
        depends_on=[last],
    )
    if not initial.passed:
        return
    target = next(
        nodes[letter]
        for letter in ["c", "b", "a"]
        if identities[nodes[letter]["name"]] != initial.data["master_node"]
    )
    values.update(node_name=target["name"], node_id=identities[target["name"]])
    single_voter = [initial.data["master_node"]]
    # Exact7.0 default Reconfigurator selects size1 for two non-retired live nodes.
    # This fixture keeps the current master live and excludes a different node.
    excluded = {
        "accepted": single_voter,
        "committed": single_voter,
        "exclusions": [{"node_id": values["node_id"], "node_name": values["node_name"]}],
    }
    try:
        call(
            "absent",
            [
                (
                    "no existing master matched",
                    lambda data: "matched no master-eligible nodes" in data["error"]["reason"],
                    True,
                )
            ],
        )
        call(
            "absent-state",
            [("absent selector did not mutate voting state", coordination, original)],
            ["absent"],
        )
        call(
            "negative-timeout",
            [
                (
                    "nonnegative timeout required",
                    lambda data: "must be non-negative" in data["error"]["reason"],
                    True,
                )
            ],
        )
        call(
            "timeout-state",
            [("invalid timeout did not mutate voting state", coordination, original)],
            ["negative-timeout"],
        )
        call("add-name")
        call(
            "name-state",
            [
                (
                    "default7.0 reconfiguration excludes actual node and keeps one master voter",
                    coordination,
                    excluded,
                ),
                ("all three nodes remain live", lambda data: len(data["nodes"]), 3),
            ],
            ["add-name"],
        )
        call("duplicate")
        call(
            "duplicate-state",
            [("duplicate selector preserves one exclusion", coordination, excluded)],
            ["duplicate"],
        )
        call("clear-present")
        last = poll("restore-poll", original)
        call(
            "restored",
            [("present node voting membership restored", coordination, original)],
            ["clear-present"],
            depends_on=[last],
        )
        call("add-id")
        id_state = call(
            "id-state",
            [("actual node ID resolves through old path", coordination, excluded)],
            ["add-id"],
        )
        if id_state.passed:
            stopped = True
        control("stop", id_state)
        values["node_count"] = 2
        call(
            "two-nodes",
            [("excluded node actually removed", lambda data: data["number_of_nodes"], 2)],
        )
        call("clear-removed")
        removed = call(
            "removed-state",
            [
                (
                    "default removal wait clears exclusion",
                    coordination,
                    {"accepted": single_voter, "committed": single_voter, "exclusions": []},
                )
            ],
            ["clear-removed"],
        )
        if control("start", removed):
            stopped = False
        values["node_count"] = 3
        call("rejoined", [("persistent node rejoined", lambda data: data["number_of_nodes"], 3)])
        last = poll("final-poll", original)
        call(
            "final-ready",
            [
                ("original voting configuration restored", coordination, original),
                (
                    "same persistent node ID",
                    lambda data: data["nodes"][values["node_id"]]["name"],
                    values["node_name"],
                ),
            ],
            ["clear-removed"],
            depends_on=[last],
        )
        call("clear-empty")
        call(
            "empty-state", [("empty clear is idempotent", coordination, original)], ["clear-empty"]
        )
    finally:
        if stopped:
            control("start", cleanup=True)
        call("cleanup-clear")
        call(
            "cleanup-state",
            [("fixture exclusions cleared", lambda data: coordination(data)["exclusions"], [])],
        )
