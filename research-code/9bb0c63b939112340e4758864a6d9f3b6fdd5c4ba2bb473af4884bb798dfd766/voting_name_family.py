"""Exact duplicate-node-name errors and ID-based voting effects on owned ES7 nodes."""

import json
import os
import time
from collections import Counter

from early_voting_family import coordination, valid_zero_timeout_reply
from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.17.29"}
STATE = "/_cluster/state?filter_path=master_node,nodes,metadata.cluster_coordination"
ROOT = "/_cluster/voting_config_exclusions"
POLLS = 40


def ambiguous_name_error(data, name, identifiers):
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict) or error.get("type") != "illegal_argument_exception":
        return False
    reason = error.get("reason")
    return (
        isinstance(reason, str)
        and "node name [" + name + "] is ambiguous" in reason
        and "specify node ID instead" in reason
        and all(identifier in reason for identifier in identifiers)
    )


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(
        name,
        api="cluster.state",
        method="GET",
        path=STATE,
        deps=(),
        expected=(200,),
        purpose="effect-check",
    ):
        identifier = "voting-names." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("voting-names." + value for value in deps)

    def polls(stem, prerequisite):
        for number in range(POLLS):
            previous = prerequisite if number == 0 else stem + "." + str(number - 1)
            case(stem + "." + str(number), deps=(previous,), purpose="fixture-precondition")

    def post(name, selector, deps, expected=(200,)):
        case(
            name,
            "cluster.post_voting_config_exclusions",
            "POST",
            ROOT + "?" + selector,
            deps,
            expected,
            "api-contract",
        )

    def clear(name, deps=(), purpose="api-contract"):
        case(
            name,
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            ROOT + "?wait_for_removal=false",
            deps,
            purpose=purpose,
        )

    case(
        "nodes",
        "nodes.info",
        path="/_nodes?filter_path=_nodes,nodes.*.name",
        purpose="fixture-precondition",
    )
    polls("initial-poll", "nodes")
    case("initial-ready", deps=("initial-poll.*",), purpose="fixture-precondition")
    previous = "initial-ready"
    for name, value in [
        ("duplicate", "{duplicate_name}"),
        ("unique", "{unique_name}"),
        ("absent", "{absent_name}"),
    ]:
        post("reject-" + name, "node_names=" + value + "&timeout=30s", (previous,), (400,))
        case("unchanged-" + name, deps=("reject-" + name,))
        previous = "unchanged-" + name
    post("id-add", "node_ids={node_id}&timeout=30s", (previous,))
    polls("id-poll", "id-add")
    case("id-ready", deps=("id-poll.*",))
    post("id-duplicate", "node_ids={node_id}&timeout=30s", ("id-ready",))
    case("id-duplicate-state", deps=("id-duplicate",))
    post(
        "reject-applied-name",
        "node_names={duplicate_name}&timeout=30s",
        ("id-duplicate-state",),
        (400,),
    )
    case("unchanged-applied-name", deps=("reject-applied-name",))
    case(
        "wait-present",
        "cluster.delete_voting_config_exclusions",
        "DELETE",
        ROOT + "?wait_for_removal=true",
        ("unchanged-applied-name",),
        (500,),
        "api-contract",
    )
    case("wait-unchanged", deps=("wait-present",))
    clear("clear-id", ("wait-unchanged",))
    polls("restored-poll", "clear-id")
    case("restored", deps=("restored-poll.*",))
    post("zero-add", "node_ids={node_id}&timeout=0s", ("restored",), (200, 500))
    case("zero-stored", deps=("zero-add",))
    polls("zero-poll", "zero-stored")
    case("zero-ready", deps=("zero-poll.*",))
    clear("zero-clear", ("zero-ready",))
    polls("zero-restored-poll", "zero-clear")
    case("zero-restored", deps=("zero-restored-poll.*",))
    clear("cleanup", purpose="fixture-cleanup")
    polls("cleanup-poll", "cleanup")
    case("cleanup-state", deps=("cleanup-poll.*",), purpose="fixture-cleanup")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Duplicate-name fixture is not prepared for exact release")
    owned = json.loads(os.environ["ES_TOPOLOGY_NODES"])
    values = {"absent_name": prefix + "-absent-node"}

    def call(name, assertions=(), verifies=(), depends_on=None):
        case = catalog.cases["voting-names." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=OMITTED,
            assertions=assertions,
            depends_on=case.dependency_plan if depends_on is None else depends_on,
            verifies=["voting-names." + value for value in verifies],
            semantic=bool(assertions or verifies),
            deadline=45,
            socket_timeout=35,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def poll(stem, expected):
        last = None
        for number in range(POLLS):
            result = call(
                stem + "." + str(number),
                [
                    (
                        "coordination metadata present",
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
        return [last]

    info = call(
        "nodes",
        [
            ("three actual node IDs", lambda data: len(data["nodes"]), 3),
            (
                "exact owned node names including deliberate duplicate",
                lambda data: sorted(row["name"] for row in data["nodes"].values()),
                sorted(row["node_name"] for row in owned.values()),
            ),
        ],
    )
    if not info.passed:
        return
    names = {identifier: row["name"] for identifier, row in info.data["nodes"].items()}
    counts = Counter(names.values())
    if sorted(counts.values()) != [1, 2]:
        raise ValueError("Expected exactly two duplicate names and one unique name")
    duplicate_name = next(name for name, count in counts.items() if count == 2)
    duplicate_ids = sorted(
        identifier for identifier, name in names.items() if name == duplicate_name
    )
    values.update(
        duplicate_name=duplicate_name,
        unique_name=next(name for name, count in counts.items() if count == 1),
    )
    original = {"accepted": sorted(names), "committed": sorted(names), "exclusions": []}

    def live(data):
        return sorted(data["nodes"]) == sorted(names)

    ready = call(
        "initial-ready",
        [
            ("three accepted/committed voters and empty exclusions", coordination, original),
            ("all three original IDs remain live", live, True),
        ],
        depends_on=poll("initial-poll", original),
    )
    if not ready.passed:
        return
    values["node_id"] = next(
        identifier for identifier in duplicate_ids if identifier != ready.data["master_node"]
    )
    exclusion = {"node_id": values["node_id"], "node_name": duplicate_name}
    excluded = {
        "accepted": [ready.data["master_node"]],
        "committed": [ready.data["master_node"]],
        "exclusions": [exclusion],
    }

    def state_checks(expected):
        return [
            ("exact coordination state", coordination, expected),
            ("all three original node IDs stay live", live, True),
        ]

    ambiguity = [
        (
            "explicit ambiguous-name error names both real IDs and suggests ID selector",
            lambda data: ambiguous_name_error(data, duplicate_name, duplicate_ids),
            True,
        )
    ]
    try:
        for name in ["duplicate", "unique", "absent"]:
            call("reject-" + name, ambiguity)
            call("unchanged-" + name, state_checks(original), ("reject-" + name,))
        call("id-add")
        call("id-ready", state_checks(excluded), ("id-add",), depends_on=poll("id-poll", excluded))
        call("id-duplicate")
        call("id-duplicate-state", state_checks(excluded), ("id-duplicate",))
        call("reject-applied-name", ambiguity)
        call("unchanged-applied-name", state_checks(excluded), ("reject-applied-name",))
        call(
            "wait-present",
            [
                (
                    "actual server timeout with query parameter hint",
                    lambda data: (
                        data["error"]["type"] == "timeout_exception"
                        and "?wait_for_removal=false" in data["error"]["reason"]
                    ),
                    True,
                ),
            ],
        )
        call("wait-unchanged", state_checks(excluded), ("wait-present",))
        call("clear-id")
        call(
            "restored",
            state_checks(original),
            ("clear-id",),
            depends_on=poll("restored-poll", original),
        )
        zero = call("zero-add")
        call(
            "zero-stored",
            [
                (
                    "only success or exact add-wait timeout accepted",
                    lambda _data: valid_zero_timeout_reply(zero),
                    True,
                ),
                (
                    "new actual ID exclusion stored after zero-timeout reply",
                    lambda data: coordination(data)["exclusions"],
                    [exclusion],
                ),
                ("all three original IDs remain live", live, True),
            ],
            ("zero-add",),
        )
        call(
            "zero-ready",
            state_checks(excluded),
            ("zero-add",),
            depends_on=poll("zero-poll", excluded),
        )
        call("zero-clear")
        call(
            "zero-restored",
            state_checks(original),
            ("zero-clear",),
            depends_on=poll("zero-restored-poll", original),
        )
    finally:
        call("cleanup")
        call(
            "cleanup-state",
            state_checks(original),
            ("cleanup",),
            depends_on=poll("cleanup-poll", original),
        )
