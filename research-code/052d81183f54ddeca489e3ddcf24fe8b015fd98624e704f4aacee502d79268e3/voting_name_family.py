"""Exact duplicate-node-name errors and ID-based voting effects on owned ES nodes."""

import json
import os
import time
from collections import Counter

from early_voting_family import coordination, valid_zero_timeout_reply
from evidence_runner import OMITTED

PROFILES = {
    "7.17.29": {"status": 400, "wait_hint": "?wait_for_removal=false", "name_error": "ambiguous"},
    "8.0.1": {
        "status": 500,
        "wait_hint": "waitForRemoval to false.",
        "name_error": "duplicate-key",
    },
    "8.1.3": {
        "status": 500,
        "wait_hint": "waitForRemoval to false.",
        "name_error": "duplicate-key",
    },
    "8.2.3": {
        "status": 500,
        "wait_hint": "waitForRemoval to false.",
        "name_error": "duplicate-key",
    },
    "8.3.3": {"status": 500, "wait_hint": "?wait_for_removal=false", "name_error": "duplicate-key"},
    "8.4.3": {"status": 400, "wait_hint": "?wait_for_removal=false", "name_error": "ambiguous"},
    "8.5.3": {"status": 400, "wait_hint": "?wait_for_removal=false", "name_error": "ambiguous"},
    "8.6.2": {"status": 400, "wait_hint": "?wait_for_removal=false", "name_error": "ambiguous"},
}
PREPARED_VERSIONS = set(PROFILES)
MASTER_TIMEOUT_RELEASES = {"8.3.3", "8.4.3", "8.5.3", "8.6.2"}
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


def duplicate_name_error(data, name, identifiers, version):
    profile = PROFILES.get(version)
    if profile is None:
        raise ValueError("Duplicate-name error profile not prepared for exact release")
    if profile["name_error"] == "ambiguous":
        return ambiguous_name_error(data, name, identifiers)
    if profile["name_error"] != "duplicate-key":
        raise ValueError("Unreviewed duplicate-name error kind")
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict) or error.get("type") != "illegal_state_exception":
        return False
    reason = error.get("reason")
    return (
        isinstance(reason, str)
        and "Duplicate key" in reason
        and name in reason
        and all(identifier in reason for identifier in identifiers)
    )


def invalid_master_timeout_error(data):
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict) or error.get("type") != "illegal_argument_exception":
        return False
    reason = error.get("reason")
    return isinstance(reason, str) and all(
        fragment in reason for fragment in ("failed to parse", "master_timeout", "bad-time")
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
        dimensions=None,
    ):
        identifier = "voting-names." + name
        options = {} if dimensions is None else {"dimensions": dimensions}
        add(identifier, api, method, path, expected=expected, purpose=purpose, **options)
        graph[identifier] = tuple("voting-names." + value for value in deps)

    def polls(stem, prerequisite):
        for number in range(POLLS):
            previous = prerequisite if number == 0 else stem + "." + str(number - 1)
            case(stem + "." + str(number), deps=(previous,), purpose="fixture-precondition")

    def post(name, selector, deps, expected=(200,), dimensions=None):
        case(
            name,
            "cluster.post_voting_config_exclusions",
            "POST",
            ROOT + "?" + selector,
            deps,
            expected,
            "api-contract",
            dimensions=dimensions,
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
        post(
            "reject-" + name,
            "node_names=" + value + "&timeout=30s",
            (previous,),
            (PROFILES[version]["status"],),
        )
        case("unchanged-" + name, deps=("reject-" + name,))
        previous = "unchanged-" + name
    if version in MASTER_TIMEOUT_RELEASES:
        post(
            "master-bad-add",
            "node_ids={node_id}&timeout=30s&master_timeout=bad-time",
            (previous,),
            (400,),
            ("query.master_timeout.invalid", "response.expected-error"),
        )
        case("master-bad-add-state", deps=("master-bad-add",))
        previous = "master-bad-add-state"
    post(
        "id-add",
        "node_ids={node_id}&timeout=30s"
        + ("&master_timeout=5s" if version in MASTER_TIMEOUT_RELEASES else ""),
        (previous,),
        dimensions=("response.success", "query.master_timeout.parser-accepted")
        if version in MASTER_TIMEOUT_RELEASES
        else None,
    )
    polls("id-poll", "id-add")
    case("id-ready", deps=("id-poll.*",))
    post("id-duplicate", "node_ids={node_id}&timeout=30s", ("id-ready",))
    case("id-duplicate-state", deps=("id-duplicate",))
    post(
        "reject-applied-name",
        "node_names={duplicate_name}&timeout=30s",
        ("id-duplicate-state",),
        (PROFILES[version]["status"],),
    )
    case("unchanged-applied-name", deps=("reject-applied-name",))
    wait_previous = "unchanged-applied-name"
    if version in MASTER_TIMEOUT_RELEASES:
        case(
            "master-bad-clear",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            ROOT + "?wait_for_removal=false&master_timeout=bad-time",
            (wait_previous,),
            (400,),
            "api-contract",
            dimensions=("query.master_timeout.invalid", "response.expected-error"),
        )
        case("master-bad-clear-state", deps=("master-bad-clear",))
        case(
            "master-short-wait",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            ROOT + "?wait_for_removal=true&master_timeout=250ms",
            ("master-bad-clear-state",),
            (500,),
            "api-contract",
            dimensions=("query.master_timeout.clear-removal-wait", "response.expected-error"),
        )
        case("master-short-state", deps=("master-short-wait",))
        wait_previous = "master-short-state"
    case(
        "wait-present",
        "cluster.delete_voting_config_exclusions",
        "DELETE",
        ROOT + "?wait_for_removal=true",
        (wait_previous,),
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
        short_wait = name == "master-short-wait"
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=OMITTED,
            assertions=assertions,
            depends_on=case.dependency_plan if depends_on is None else depends_on,
            verifies=["voting-names." + value for value in verifies],
            semantic=bool(assertions or verifies),
            deadline=6 if short_wait else 45,
            socket_timeout=5 if short_wait else 35,
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
            "explicit ambiguous-name error names both real IDs and suggests ID selector"
            if PROFILES[catalog.version]["name_error"] == "ambiguous"
            else "duplicate-key failure identifies both actual node IDs",
            lambda data: duplicate_name_error(data, duplicate_name, duplicate_ids, catalog.version),
            True,
        )
    ]
    try:
        for name in ["duplicate", "unique", "absent"]:
            call("reject-" + name, ambiguity)
            call("unchanged-" + name, state_checks(original), ("reject-" + name,))
        if catalog.version in MASTER_TIMEOUT_RELEASES:
            call(
                "master-bad-add",
                [
                    (
                        "master_timeout parse error identifies invalid value",
                        invalid_master_timeout_error,
                        True,
                    )
                ],
            )
            call("master-bad-add-state", state_checks(original), ("master-bad-add",))
        call("id-add")
        call("id-ready", state_checks(excluded), ("id-add",), depends_on=poll("id-poll", excluded))
        call("id-duplicate")
        call("id-duplicate-state", state_checks(excluded), ("id-duplicate",))
        call("reject-applied-name", ambiguity)
        call("unchanged-applied-name", state_checks(excluded), ("reject-applied-name",))
        if catalog.version in MASTER_TIMEOUT_RELEASES:
            call(
                "master-bad-clear",
                [
                    (
                        "master_timeout parse error identifies invalid value",
                        invalid_master_timeout_error,
                        True,
                    )
                ],
            )
            call("master-bad-clear-state", state_checks(excluded), ("master-bad-clear",))
            call(
                "master-short-wait",
                [
                    (
                        "actual short server timeout with query hint",
                        lambda data: (
                            data["error"]["type"] == "timeout_exception"
                            and PROFILES[catalog.version]["wait_hint"] in data["error"]["reason"]
                        ),
                        True,
                    )
                ],
            )
            call("master-short-state", state_checks(excluded), ("master-short-wait",))
        call(
            "wait-present",
            [
                (
                    "actual server timeout with query parameter hint"
                    if PROFILES[catalog.version]["wait_hint"].startswith("?")
                    else "actual server timeout with literal legacy hint",
                    lambda data: (
                        data["error"]["type"] == "timeout_exception"
                        and PROFILES[catalog.version]["wait_hint"] in data["error"]["reason"]
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
