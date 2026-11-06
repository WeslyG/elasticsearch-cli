"""ES6.4 native secure reload, real keystore read failure and byte restoration."""

import os

from evidence_runner import OMITTED
from keystore_fixture import OwnedKeystore

PREPARED_VERSIONS = {
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
}


PARSED_BODY_RELEASES = {
    "7.7.1",
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
}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    local = "/_nodes/_local/reload_secure_settings"

    def case(name, path, deps=(), expected=(200,), unsupported=(), purpose="api-contract"):
        identifier = "secure-reload." + name
        add(
            identifier,
            "nodes.reload_secure_settings",
            "POST",
            path,
            expected=expected,
            unsupported=unsupported,
            purpose=purpose,
        )
        graph[identifier] = tuple("secure-reload." + item for item in deps)

    case("all-good", "/_nodes/reload_secure_settings")
    case("local-good", local, ("all-good",))
    probes = (
        [
            ("empty-bytes", 200),
            ("parsed-empty-object", 200),
            ("parsed-empty-password", 200),
            ("parsed-wrong-password", 200),
            ("parsed-null", 400),
            ("parsed-malformed", 400),
            ("parsed-unknown", 400),
        ]
        if version in PARSED_BODY_RELEASES
        else [
            (name, 200)
            for name in ["empty-bytes", "ignored-object", "ignored-null", "ignored-malformed"]
        ]
    )
    for name, status in probes:
        case(name, local, ("local-good",), (status,), purpose="wire-body-handling")
    case("timeout-good", local + "?timeout=1s", ("local-good",))
    case("timeout-bad", local + "?timeout=garbage", ("local-good",), (400,))
    case("unknown-query", local + "?es_cli_unknown=1", ("local-good",), (400,), ("es_cli_unknown",))
    case(
        "missing-node", "/_nodes/es-cli-absent-node/reload_secure_settings", purpose="zero-targets"
    )
    for name, path in [("corrupt-local", local), ("corrupt-all", "/_nodes/reload_secure_settings")]:
        case(name, path, ("local-good",), purpose="negative-node-reload")
    case("restored-local", local, ("corrupt-local",), purpose="effect-check")
    case("restored-all", "/_nodes/reload_secure_settings", ("corrupt-all",), purpose="effect-check")
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Keystore reload fixture is not prepared for this exact release")
    lab = os.environ["ES_RESEARCH_LAB"]
    node = os.environ["ES_RESEARCH_NODE"]
    identifiers = []

    def successful(data):
        return (
            data["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
            and data["cluster_name"] == lab
            and len(data["nodes"]) == 1
            and all(
                info["name"] == "es-cli-anchor" and "reload_exception" not in info
                for info in data["nodes"].values()
            )
        )

    def call(name, body=OMITTED, assertions=(), semantic=False):
        case = catalog.cases["secure-reload." + name]
        result = catalog.execute(
            run,
            case.id,
            values={},
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    checks = [("actual owned node reload has no per-node exception", successful, True)]
    initial = call("all-good", assertions=checks, semantic=True)
    if not initial.passed:
        raise ValueError("Initial reload did not pass; keystore left untouched")
    identifiers[:] = sorted(initial.data["nodes"])
    checks = checks + [
        ("same owned Elasticsearch node", lambda data: sorted(data["nodes"]), identifiers)
    ]
    local = call("local-good", assertions=checks, semantic=True)
    if not local.passed:
        raise ValueError("Local reload did not pass; keystore left untouched")
    if catalog.version in PARSED_BODY_RELEASES:
        probes = [
            ("empty-bytes", b"", checks),
            ("parsed-empty-object", {}, checks),
            ("parsed-empty-password", {"secure_settings_password": ""}, checks),
            (
                "parsed-wrong-password",
                {"secure_settings_password": "public-fixture-incorrect-password"},
                [
                    (
                        "same node response despite per-node password failure",
                        lambda d: (
                            d["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
                            and sorted(d["nodes"]) == identifiers
                        ),
                        True,
                    ),
                    (
                        "synthetic incorrect password consumed",
                        lambda d: all(
                            v["reload_exception"]["type"] == "security_exception"
                            and "Provided keystore password was incorrect"
                            in v["reload_exception"]["reason"]
                            for v in d["nodes"].values()
                        ),
                        True,
                    ),
                ],
            ),
            (
                "parsed-null",
                None,
                [("null body rejected", lambda d: isinstance(d.get("error"), dict), True)],
            ),
            (
                "parsed-malformed",
                b"{",
                [("malformed body rejected", lambda d: isinstance(d.get("error"), dict), True)],
            ),
            (
                "parsed-unknown",
                {"es_cli_unknown": True},
                [
                    (
                        "unknown body field rejected",
                        lambda d: "es_cli_unknown" in str(d["error"]),
                        True,
                    )
                ],
            ),
        ]
    else:
        probes = [
            (name, body, checks)
            for name, body in [
                ("empty-bytes", b""),
                ("ignored-object", {"secure_settings_password": "public-fixture-not-consumed"}),
                ("ignored-null", None),
                ("ignored-malformed", b"{"),
            ]
        ]
    for name, body, assertions in probes:
        call(name, body, assertions=assertions)
    call("timeout-good", assertions=checks, semantic=True)
    for name in ["timeout-bad", "unknown-query"]:
        call(
            name,
            assertions=[
                (
                    "invalid query has structured error",
                    lambda data: (
                        isinstance(data.get("error"), dict)
                        and isinstance(data["error"].get("type"), str)
                    ),
                    True,
                )
            ],
        )
    call(
        "missing-node",
        assertions=[
            (
                "zero nodes is not a completed reload",
                lambda data: data["_nodes"],
                {"total": 0, "successful": 0, "failed": 0},
            ),
            ("no selected node response", lambda data: data["nodes"], {}),
        ],
    )

    def corrupted(data):
        return (
            data["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
            and sorted(data["nodes"]) == identifiers
            and all(
                info["reload_exception"]["type"] == "corrupt_index_exception"
                and "codec header" in info["reload_exception"]["reason"].lower()
                for info in data["nodes"].values()
            )
        )

    with OwnedKeystore(run.output, node, lab) as fixture:
        fixture.data["observed_elasticsearch_node_ids"] = identifiers
        fixture.corrupt()
        for name in ["corrupt-local", "corrupt-all"]:
            call(
                name,
                assertions=[
                    (
                        "HTTP200 transport success still carries actual keystore read error",
                        corrupted,
                        True,
                    )
                ],
            )
    recovered = [
        call(name, assertions=checks, semantic=True) for name in ["restored-local", "restored-all"]
    ]
    fixture.data["api_recovery_verified"] = all(result.passed for result in recovered)
    fixture.save()
