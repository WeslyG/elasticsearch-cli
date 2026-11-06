"""Final owned-lab system-feature reset and disabled GeoIP metadata; never a pilot mix-in."""

import os

from evidence_runner import OMITTED

PREPARED_VERSIONS = {
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
}
COUNTERS = (
    "successful_downloads",
    "failed_downloads",
    "total_download_time",
    "databases_count",
    "skipped_updates",
)


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    specs = [
        ("identity", "info", "GET", "/", (), (200,), "fixture-precondition"),
        (
            "geoip-config",
            "cluster.get_settings",
            "GET",
            "/_cluster/settings?include_defaults=true&flat_settings=true&filter_path=defaults.*geoip*",
            ("identity",),
            (200,),
            "fixture-precondition",
        ),
        (
            "geoip-stats",
            "ingest.geo_ip_stats",
            "GET",
            "/_ingest/geoip/stats",
            ("geoip-config",),
            (200,),
            "api-contract",
        ),
        (
            "geoip-body",
            "ingest.geo_ip_stats",
            "GET",
            "/_ingest/geoip/stats",
            ("geoip-stats",),
            (400,),
            "api-contract",
        ),
        ("create", "indices.create", "PUT", "/{index}", ("identity",), (200,), "fixture-setup"),
        (
            "write",
            "index",
            "PUT",
            "/{index}/_doc/one?refresh=true",
            ("create",),
            (201,),
            "fixture-setup",
        ),
        ("read", "get", "GET", "/{index}/_doc/one", ("write",), (200,), "fixture-precondition"),
        (
            "tasks-before",
            "indices.exists",
            "HEAD",
            "/.tasks",
            ("read",),
            (200,),
            "fixture-precondition",
        ),
        (
            "registry-before",
            "features.get_features",
            "GET",
            "/_features",
            ("tasks-before",),
            (200,),
            "fixture-precondition",
        ),
        (
            "reset-body",
            "features.reset_features",
            "POST",
            "/_features/_reset",
            ("registry-before", "geoip-body"),
            (400,),
            "api-contract",
        ),
        (
            "tasks-body-preserved",
            "indices.exists",
            "HEAD",
            "/.tasks",
            ("reset-body",),
            (200,),
            "effect-check",
        ),
        (
            "protected-body",
            "get",
            "GET",
            "/{index}/_doc/one",
            ("tasks-body-preserved",),
            (200,),
            "effect-check",
        ),
        (
            "reset",
            "features.reset_features",
            "POST",
            "/_features/_reset",
            ("protected-body",),
            (200,),
            "api-contract",
        ),
        ("tasks-after", "indices.exists", "HEAD", "/.tasks", ("reset",), (404,), "effect-check"),
        (
            "protected-after",
            "get",
            "GET",
            "/{index}/_doc/one",
            ("tasks-after",),
            (200,),
            "effect-check",
        ),
        (
            "registry-after",
            "features.get_features",
            "GET",
            "/_features",
            ("protected-after",),
            (200,),
            "effect-check",
        ),
        (
            "health",
            "cluster.health",
            "GET",
            "/_cluster/health?timeout=1s",
            ("registry-after",),
            (200,),
            "effect-check",
        ),
        ("cleanup", "indices.delete", "DELETE", "/{index}", (), (200, 404), "fixture-cleanup"),
    ]
    if version in {
        "8.9.2",
        "8.0.1",
        "7.16.3",
        "8.14.3",
        "8.15.5",
        "8.17.10",
        "8.1.3",
        "8.6.2",
        "8.7.1",
        "8.4.3",
        "8.10.4",
        "8.3.3",
        "8.12.2",
        "8.8.2",
        "8.13.4",
        "8.16.6",
        "8.11.4",
        "8.5.3",
        "8.2.3",
    }:
        specs.extend(
            [
                (
                    "migration-before",
                    "migration.get_feature_upgrade_status",
                    "GET",
                    "/_migration/system_features",
                    ("registry-before",),
                    (200,),
                    "fixture-precondition",
                ),
                (
                    "migration-body",
                    "migration.post_feature_upgrade",
                    "POST",
                    "/_migration/system_features",
                    ("migration-before",),
                    (400,),
                    "api-contract",
                ),
                (
                    "migration-noop",
                    "migration.post_feature_upgrade",
                    "POST",
                    "/_migration/system_features",
                    ("migration-before", "migration-body"),
                    (200,),
                    "api-contract",
                ),
                (
                    "migration-after",
                    "migration.get_feature_upgrade_status",
                    "GET",
                    "/_migration/system_features",
                    ("migration-noop",),
                    (200,),
                    "effect-check",
                ),
                (
                    "migration-tasks-preserved",
                    "indices.exists",
                    "HEAD",
                    "/.tasks",
                    ("migration-after",),
                    (200,),
                    "effect-check",
                ),
                (
                    "migration-ordinary-preserved",
                    "get",
                    "GET",
                    "/{index}/_doc/one",
                    ("migration-tasks-preserved",),
                    (200,),
                    "effect-check",
                ),
            ]
        )
    graph = {}
    for name, api, method, path, deps, expected, purpose in specs:
        identifier = "system-features." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("system-features." + d for d in deps)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Final feature reset not prepared for exact release")
    lab = os.environ.get("ES_RESEARCH_LAB")
    if not lab or not lab.startswith("deep-"):
        raise ValueError("Owned research lab identity required before any request")
    values = {"index": prefix + "-ordinary-protected"}
    original = {"n": 71, "purpose": "ordinary-index-must-survive-feature-reset"}

    def call(name, body=OMITTED, assertions=(), verifies=(), **kwargs):
        case = catalog.cases["system-features." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["system-features." + d for d in verifies],
            semantic=bool(assertions or verifies),
            **kwargs,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    identity = call(
        "identity",
        assertions=[
            ("exact owned cluster", lambda d: d["cluster_name"], lab),
            ("pinned release", lambda d: d["version"]["number"], catalog.version),
            ("not a snapshot", lambda d: d["version"]["build_snapshot"], False),
            (
                "pinned build source",
                lambda d: (
                    isinstance(d["version"]["build_hash"], str)
                    and len(d["version"]["build_hash"]) >= 7
                    and catalog.inventory["source_commit"].startswith(d["version"]["build_hash"])
                ),
                True,
            ),
        ],
    )
    if not identity.passed:
        raise ValueError("Owned cluster identity differs; no reset or fixture mutation attempted")
    protected = [("ordinary document intact", lambda d: d["_source"], original)]
    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    try:
        call(
            "geoip-config",
            assertions=[
                (
                    "downloader explicitly disabled",
                    lambda d: d["defaults"]["ingest.geoip.downloader.enabled"],
                    "false",
                )
            ],
        )
        call(
            "geoip-stats",
            assertions=[
                (
                    "fresh disabled counters",
                    lambda d: {
                        k: d["stats"][k]
                        for k in (
                            COUNTERS
                            + (
                                ("expired_databases",)
                                if catalog.version
                                in {
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
                                }
                                else ()
                            )
                        )
                    },
                    {
                        k: 0
                        for k in (
                            COUNTERS
                            + (
                                ("expired_databases",)
                                if catalog.version
                                in {
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
                                }
                                else ()
                            )
                        )
                    },
                ),
                ("node metadata is a map", lambda d: isinstance(d["nodes"], dict), True),
            ],
        )
        call(
            "geoip-body",
            {"unused": True},
            [
                (
                    "GeoIP metadata body refused",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                ),
                (
                    "specific body refusal",
                    lambda d: d["error"]["reason"],
                    "request [GET /_ingest/geoip/stats] does not support having a body",
                ),
            ],
        )
        call("create", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}}, ack)
        call("write", original)
        call("read", assertions=protected, verifies=("write",))
        call("tasks-before")
        before = call(
            "registry-before",
            assertions=[
                (
                    "core tasks feature registered",
                    lambda d: "tasks" in {f["name"] for f in d["features"]},
                    True,
                )
            ],
        )
        if catalog.version in {
            "8.9.2",
            "8.0.1",
            "7.16.3",
            "8.14.3",
            "8.15.5",
            "8.17.10",
            "8.1.3",
            "8.6.2",
            "8.7.1",
            "8.4.3",
            "8.10.4",
            "8.3.3",
            "8.12.2",
            "8.8.2",
            "8.13.4",
            "8.16.6",
            "8.11.4",
            "8.5.3",
            "8.2.3",
        }:
            status_checks = [
                (
                    "fresh system indices need no migration",
                    lambda d: d["migration_status"],
                    "NO_MIGRATION_NEEDED",
                ),
                (
                    "tasks feature present",
                    lambda d: any(f["feature_name"] == "tasks" for f in d["features"]),
                    True,
                ),
            ]
            call("migration-before", assertions=status_checks)
            call(
                "migration-body",
                {"unused": True},
                [
                    (
                        "unused migration body refused",
                        lambda d: d["error"]["type"],
                        "illegal_argument_exception",
                    )
                ],
            )
            call(
                "migration-noop",
                assertions=[
                    ("no upgrade started", lambda d: d["accepted"], False),
                    (
                        "exact noop reason",
                        lambda d: d["reason"],
                        "No system indices require migration",
                    ),
                ],
            )
            call("migration-after", assertions=status_checks, verifies=("migration-noop",))
            call("migration-tasks-preserved", verifies=("migration-noop",))
            call("migration-ordinary-preserved", assertions=protected, verifies=("migration-noop",))
        call(
            "reset-body",
            {"unused": True},
            [
                (
                    "unused reset body refused before action",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                ),
                (
                    "specific reset body refusal",
                    lambda d: d["error"]["reason"],
                    "request [POST /_features/_reset] does not support having a body",
                ),
            ],
        )
        call("tasks-body-preserved", verifies=("reset-body",))
        call("protected-body", assertions=protected, verifies=("reset-body",))
        call(
            "reset",
            assertions=[
                (
                    "tasks reset succeeded",
                    lambda d: next(
                        f["status"] for f in d["features"] if f["feature_name"] == "tasks"
                    ),
                    "SUCCESS",
                ),
                (
                    "fresh-lab reset reports all-success",
                    lambda d: all(f["status"] == "SUCCESS" for f in d["features"]),
                    True,
                ),
                (
                    "distinct reset feature names",
                    lambda d: (
                        len({f["feature_name"] for f in d["features"]}) == len(d["features"]) > 0
                    ),
                    True,
                ),
            ],
            deadline=45,
            socket_timeout=30,
        )
        call("tasks-after", verifies=("reset",))
        call("protected-after", assertions=protected, verifies=("reset",))
        names = sorted(f["name"] for f in before.data["features"]) if before.passed else None
        call(
            "registry-after",
            assertions=[
                (
                    "registration survives state deletion",
                    lambda d: sorted(f["name"] for f in d["features"]),
                    names,
                )
            ],
            verifies=("reset",),
        )
        call("health", assertions=[("cluster responsive", lambda d: d["timed_out"], False)])
    finally:
        call("cleanup")
