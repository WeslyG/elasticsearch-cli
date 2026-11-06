"""Exact7.8 voting exclusion storage using absent names/IDs; no real quorum removal."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {
    "7.8.1",
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
}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    state = "/_cluster/state?filter_path=master_node,nodes,metadata.cluster_coordination"
    graph = {}
    specs = [
        ("initial", "cluster.state", "GET", state, (), (200,)),
        (
            "add-name",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions?node_names={absent_name}&timeout=1s",
            ("initial",),
            (200,),
        ),
        ("state-name", "cluster.state", "GET", state, ("add-name",), (200,)),
        (
            "add-id",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions?node_ids={absent_id}&timeout=1s",
            ("state-name",),
            (200,),
        ),
        ("state-two", "cluster.state", "GET", state, ("add-id",), (200,)),
        (
            "add-duplicate",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions?node_names={absent_name}&timeout=1s",
            ("state-two",),
            (200,),
        ),
        ("state-duplicate", "cluster.state", "GET", state, ("add-duplicate",), (200,)),
        (
            "invalid-both",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions?node_names={absent_name}&node_ids={absent_id}",
            ("state-duplicate",),
            (400,),
        ),
        ("state-invalid", "cluster.state", "GET", state, ("invalid-both",), (200,)),
        (
            "legacy-absent",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions?node_name={absent_name}&timeout=1s",
            ("state-invalid",),
            (400,),
        ),
        ("state-legacy", "cluster.state", "GET", state, ("legacy-absent",), (200,)),
        (
            "legacy-path",
            "cluster.post_voting_config_exclusions",
            "POST",
            "/_cluster/voting_config_exclusions/{absent_name}?timeout=1s",
            ("state-legacy",),
            (400,),
        ),
        ("state-legacy-path", "cluster.state", "GET", state, ("legacy-path",), (200,)),
        (
            "clear-default",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            "/_cluster/voting_config_exclusions",
            ("state-legacy-path",),
            (200,),
        ),
        ("state-empty", "cluster.state", "GET", state, ("clear-default",), (200,)),
        (
            "clear-again",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            "/_cluster/voting_config_exclusions?wait_for_removal=false",
            ("state-empty",),
            (200,),
        ),
        ("state-empty-again", "cluster.state", "GET", state, ("clear-again",), (200,)),
        (
            "health",
            "cluster.health",
            "GET",
            "/_cluster/health?timeout=1s",
            ("state-empty-again",),
            (200,),
        ),
        (
            "cleanup",
            "cluster.delete_voting_config_exclusions",
            "DELETE",
            "/_cluster/voting_config_exclusions?wait_for_removal=false",
            (),
            (200,),
        ),
    ]
    for name, api, method, path, deps, expected in specs:
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
        }:
            if name in {"legacy-absent", "state-legacy", "legacy-path", "state-legacy-path"}:
                continue
            if name == "clear-default":
                deps = ("state-invalid",)
        identifier = "voting-state." + name
        add(
            identifier,
            api,
            method,
            path,
            expected=expected,
            purpose="fixture-precondition"
            if name == "initial"
            else "fixture-cleanup"
            if name == "cleanup"
            else "api-contract",
        )
        graph[identifier] = tuple("voting-state." + d for d in deps)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Voting fixture not prepared for exact release")
    values = {"absent_name": prefix + "-absent-name", "absent_id": prefix + "-absent-id"}

    def exclusions(data):
        return data["metadata"]["cluster_coordination"].get("voting_config_exclusions", [])

    def pairs(data):
        return sorted([[v["node_id"], v["node_name"]] for v in exclusions(data)])

    def call(name, assertions=(), verifies=()):
        case = catalog.cases["voting-state." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=OMITTED,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["voting-state." + d for d in verifies],
            semantic=bool(assertions),
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    initial = call(
        "initial",
        [
            ("initial exclusion list empty", exclusions, []),
            (
                "one disposable master node",
                lambda d: len(d["nodes"]) == 1 and d["master_node"] in d["nodes"],
                True,
            ),
            (
                "fixture name and ID match no real node",
                lambda d: (
                    values["absent_id"] not in d["nodes"]
                    and all(n["name"] != values["absent_name"] for n in d["nodes"].values())
                ),
                True,
            ),
        ],
    )
    if not initial.passed:
        raise ValueError("Fresh owned voting fixture required; no voting mutation executed")
    master = initial.data["master_node"]
    config = initial.data["metadata"]["cluster_coordination"]["last_committed_config"]

    def state(expected):
        return [
            ("actual exclusion storage", pairs, expected),
            ("real master unchanged", lambda d: d["master_node"], master),
            (
                "real voting config unchanged",
                lambda d: d["metadata"]["cluster_coordination"]["last_committed_config"],
                config,
            ),
        ]

    one = [["_absent_", values["absent_name"]]]
    two = sorted(one + [[values["absent_id"], "_absent_"]])
    try:
        call("add-name")
        call("state-name", state(one), ("add-name",))
        call("add-id")
        call("state-two", state(two), ("add-id",))
        call("add-duplicate")
        call("state-duplicate", state(two), ("add-duplicate",))
        call(
            "invalid-both",
            [
                (
                    "exactly one identifier mode required",
                    lambda d: (
                        d["error"]["reason"]
                        == "You must set [node_names] or [node_ids] but not both"
                        if catalog.version
                        in {
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
                        }
                        else "One and only one" in str(d["error"])
                    ),
                    True,
                )
            ],
        )
        call("state-invalid", state(two), ("invalid-both",))
        if catalog.version not in {
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
        }:
            call(
                "legacy-absent",
                [
                    (
                        "deprecated selector requires real master match",
                        lambda d: "master-eligible" in str(d["error"]),
                        True,
                    )
                ],
            )
            call("state-legacy", state(two), ("legacy-absent",))
            call(
                "legacy-path",
                [
                    (
                        "deprecated path reaches selector validation",
                        lambda d: "master-eligible" in str(d["error"]),
                        True,
                    )
                ],
            )
            call("state-legacy-path", state(two), ("legacy-path",))
        call("clear-default")
        call("state-empty", state([]), ("clear-default",))
        call("clear-again")
        call("state-empty-again", state([]), ("clear-again",))
        call(
            "health",
            [
                (
                    "one node still healthy",
                    lambda d: (
                        d["number_of_nodes"] == 1 and d["status"] != "red" and not d["timed_out"]
                    ),
                    True,
                ),
            ],
        )
    finally:
        call("cleanup")
