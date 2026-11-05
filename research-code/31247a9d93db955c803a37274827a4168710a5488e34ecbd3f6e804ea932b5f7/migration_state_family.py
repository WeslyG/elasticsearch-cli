"""A real pre-7 persisted task snapshot, restored and migrated sequentially."""

import json
import os
import time

from evidence_runner import OMITTED


def declare(add, version):
    if version not in {"6.0.1", "7.17.29"}:
        return {}
    legacy = version == "6.0.1"
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("migration-state." + name, api, method, path, expected=expected, purpose=purpose)
        graph["migration-state." + name] = tuple("migration-state." + item for item in deps)

    case(
        "empty",
        "indices.exists",
        "HEAD",
        "/.tasks",
        expected=(404,),
        purpose="fixture-precondition",
    )
    if legacy:
        for name in ["source", "target"]:
            case(
                name,
                "indices.create",
                "PUT",
                "/{" + name + "}",
                ("empty",),
                purpose="fixture-setup",
            )
        case(
            "seed",
            "index",
            "PUT",
            "/{source}/fixture/one?refresh=true",
            ("source",),
            (201,),
            "fixture-setup",
        )
        case("launch", "reindex", "POST", "/_reindex?wait_for_completion=false", ("seed", "target"))
        case(
            "task",
            "tasks.get",
            "GET",
            "/_tasks/{task}?wait_for_completion=true&timeout=30s",
            ("launch",),
            purpose="fixture-precondition",
        )
        case(
            "stored", "get", "GET", "/.tasks/task/{task}", ("task",), purpose="fixture-precondition"
        )
        case(
            "settings",
            "indices.get_settings",
            "GET",
            "/.tasks/_settings",
            ("stored",),
            purpose="fixture-precondition",
        )
        case(
            "repository",
            "snapshot.create_repository",
            "PUT",
            "/_snapshot/{repo}",
            ("settings",),
            purpose="fixture-setup",
        )
        case(
            "snapshot",
            "snapshot.create",
            "PUT",
            "/_snapshot/{repo}/fixture?wait_for_completion=true",
            ("repository",),
        )
        case(
            "snapshot-get",
            "snapshot.get",
            "GET",
            "/_snapshot/{repo}/fixture",
            ("snapshot",),
            purpose="fixture-precondition",
        )
        for name in ["source", "target"]:
            case(
                "cleanup-" + name,
                "indices.delete",
                "DELETE",
                "/{" + name + "}",
                expected=(200, 404),
                purpose="cleanup",
            )
    else:
        case(
            "repository",
            "snapshot.create_repository",
            "PUT",
            "/_snapshot/{repo}",
            ("empty",),
            purpose="fixture-setup",
        )
        case(
            "snapshot-get",
            "snapshot.get",
            "GET",
            "/_snapshot/{repo}/fixture",
            ("repository",),
            purpose="fixture-precondition",
        )
        case(
            "restore",
            "snapshot.restore",
            "POST",
            "/_snapshot/{repo}/fixture/_restore?wait_for_completion=true",
            ("snapshot-get",),
            purpose="fixture-setup",
        )
        case(
            "settings-before",
            "indices.get_settings",
            "GET",
            "/.tasks/_settings",
            ("restore",),
            purpose="fixture-precondition",
        )
        case(
            "task-before",
            "tasks.get",
            "GET",
            "/_tasks/{task}",
            ("settings-before",),
            purpose="fixture-precondition",
        )
        case(
            "needed",
            "migration.get_feature_upgrade_status",
            "GET",
            "/_migration/system_features",
            ("task-before",),
        )
        case(
            "start",
            "migration.post_feature_upgrade",
            "POST",
            "/_migration/system_features",
            ("needed",),
        )
        for number in range(40):
            case(
                "poll-" + str(number),
                "migration.get_feature_upgrade_status",
                "GET",
                "/_migration/system_features",
                ("start",),
                purpose="effect-check",
            )
        case(
            "completed",
            "migration.get_feature_upgrade_status",
            "GET",
            "/_migration/system_features",
            ("start",),
            purpose="effect-check",
        )
        case(
            "settings-after",
            "indices.get_settings",
            "GET",
            "/.tasks/_settings",
            ("completed",),
            purpose="effect-check",
        )
        case(
            "aliases-after",
            "indices.get_alias",
            "GET",
            "/.tasks/_alias",
            ("completed",),
            purpose="effect-check",
        )
        case(
            "task-after",
            "tasks.get",
            "GET",
            "/_tasks/{task}",
            ("completed",),
            purpose="effect-check",
        )
        case(
            "repeat",
            "migration.post_feature_upgrade",
            "POST",
            "/_migration/system_features",
            ("task-after",),
        )
        case("reset", "features.reset_features", "POST", "/_features/_reset", purpose="cleanup")
        case("absent", "indices.exists", "HEAD", "/.tasks", ("reset",), (404,), "effect-check")
        case(
            "detach",
            "snapshot.delete_repository",
            "DELETE",
            "/_snapshot/{repo}",
            expected=(200, 404),
            purpose="cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    legacy = catalog.version == "6.0.1"
    values = {
        "source": prefix + "-migration-source",
        "target": prefix + "-migration-target",
        "repo": prefix + "-migration",
        "task": os.environ.get("ES_MIGRATION_TASK_ID", "not-launched"),
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["migration-state." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["migration-state." + item for item in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def created_version(data):
        return int(next(iter(data.values()))["settings"]["index"]["version"]["created"])

    def task_feature(data):
        return next(item for item in data["features"] if item["feature_name"] == "tasks")

    task_checks = [
        ("completed persisted task", lambda data: data["completed"], True),
        ("original reindex result preserved", lambda data: data["response"]["created"], 1),
        ("no original reindex failures", lambda data: data["response"]["failures"], []),
    ]
    call("empty")
    if legacy:
        try:
            for name in ["source", "target"]:
                call(name, {"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
            call("seed", {"n": 73})
            launched = call(
                "launch",
                {"source": {"index": values["source"]}, "dest": {"index": values["target"]}},
                assertions=[
                    ("real task identifier", lambda data: isinstance(data.get("task"), str), True)
                ],
            )
            if launched.state == "passed":
                values["task"] = launched.data["task"]
            call("task", assertions=task_checks)
            call(
                "stored",
                assertions=[
                    (
                        "completed task stored in actual system index",
                        lambda data: data["_source"]["completed"],
                        True,
                    )
                ],
            )
            call("settings", assertions=[("actual ES6 creation version", created_version, 6000199)])
            call(
                "repository",
                {
                    "type": "fs",
                    "settings": {"location": "/tmp/es-snapshots/es-cli-migration-handoff"},
                },
            )
            call(
                "snapshot",
                {"indices": ".tasks", "include_global_state": False},
                assertions=[
                    ("snapshot completed", lambda data: data["snapshot"]["state"], "SUCCESS"),
                    (
                        "only actual task index captured",
                        lambda data: data["snapshot"]["indices"],
                        [".tasks"],
                    ),
                ],
            )
            saved = call(
                "snapshot-get",
                assertions=[
                    (
                        "source version is exact 6.0.1",
                        lambda data: data["snapshots"][0]["version"],
                        "6.0.1",
                    ),
                    ("snapshot success", lambda data: data["snapshots"][0]["state"], "SUCCESS"),
                ],
            )
            if saved.state == "passed":
                (run.output / "migration-handoff.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "source_release": catalog.version,
                            "task_id": values["task"],
                            "snapshot": "fixture",
                            "repository_path": "/tmp/es-snapshots/es-cli-migration-handoff",
                            "creation_version": 6000199,
                        },
                        indent=2,
                    )
                    + "\n"
                )
        finally:
            for name in ["source", "target"]:
                call("cleanup-" + name)
        return

    try:
        call(
            "repository",
            {
                "type": "fs",
                "settings": {
                    "location": "/tmp/es-snapshots/es-cli-migration-handoff",
                    "readonly": True,
                },
            },
        )
        call(
            "snapshot-get",
            assertions=[
                ("actual old snapshot", lambda data: data["snapshots"][0]["version"], "6.0.1")
            ],
        )
        call(
            "restore",
            {"indices": ".tasks", "include_global_state": False},
            assertions=[
                (
                    "all restore shards succeeded",
                    lambda data: data["snapshot"]["shards"]["failed"],
                    0,
                ),
                (
                    "one task shard restored",
                    lambda data: data["snapshot"]["shards"]["successful"],
                    1,
                ),
            ],
        )
        call(
            "settings-before",
            assertions=[("real old index creation version", created_version, 6000199)],
        )
        call("task-before", assertions=task_checks)
        call(
            "needed",
            assertions=[
                (
                    "migration genuinely needed",
                    lambda data: data["migration_status"],
                    "MIGRATION_NEEDED",
                ),
                (
                    "tasks feature needs migration",
                    lambda data: task_feature(data)["migration_status"],
                    "MIGRATION_NEEDED",
                ),
            ],
        )
        call(
            "start",
            assertions=[
                ("real migration accepted", lambda data: data["accepted"], True),
                (
                    "tasks included",
                    lambda data: any(item["feature_name"] == "tasks" for item in data["features"]),
                    True,
                ),
            ],
        )
        for number in range(40):
            result = call(
                "poll-" + str(number),
                assertions=[
                    (
                        "migration has no reported error",
                        lambda data: data["migration_status"] != "ERROR",
                        True,
                    ),
                ],
            )
            if (
                result.state != "passed"
                or result.data.get("migration_status") == "NO_MIGRATION_NEEDED"
            ):
                break
            time.sleep(0.5)
        call(
            "completed",
            assertions=[
                (
                    "migration completed",
                    lambda data: data["migration_status"],
                    "NO_MIGRATION_NEEDED",
                )
            ],
            verifies=["start"],
            semantic=True,
        )
        call(
            "settings-after",
            assertions=[
                (
                    "migrated index belongs to ES7",
                    lambda data: created_version(data) // 1_000_000,
                    7,
                ),
                ("new concrete index name", lambda data: list(data), [".tasks-reindexed-for-8"]),
            ],
            verifies=["start"],
            semantic=True,
        )
        call(
            "aliases-after",
            assertions=[
                (
                    "old name now resolves through alias",
                    lambda data: ".tasks" in data[".tasks-reindexed-for-8"]["aliases"],
                    True,
                )
            ],
            verifies=["start"],
            semantic=True,
        )
        call("task-after", assertions=task_checks, verifies=["start"], semantic=True)
        call("repeat", assertions=[("repeat is a no-op", lambda data: data["accepted"], False)])
    finally:
        call("reset")
        call("absent")
        call("detach")
