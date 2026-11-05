"""ES7 feature reset with actual persisted asynchronous task results."""

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("feature." + name, api, method, path, expected=expected, purpose=purpose)
        graph["feature." + name] = tuple("feature." + dependency for dependency in deps)

    case(
        "tasks-absent",
        "indices.exists",
        "HEAD",
        "/.tasks",
        expected=(404,),
        purpose="fixture-precondition",
    )
    for name in ["source", "target"]:
        case(
            name,
            "indices.create",
            "PUT",
            "/{" + name + "}",
            ("tasks-absent",),
            purpose="fixture-setup",
        )
    case(
        "seed",
        "index",
        "PUT",
        "/{source}/_doc/one?refresh=true",
        ("source",),
        (201,),
        "fixture-setup",
    )
    case("launch", "reindex", "POST", "/_reindex?wait_for_completion=false", ("seed", "target"))
    case(
        "completed",
        "tasks.get",
        "GET",
        "/_tasks/{task}?wait_for_completion=true&timeout=30s",
        ("launch",),
        purpose="fixture-precondition",
    )
    case(
        "target-before", "get", "GET", "/{target}/_doc/one", ("completed",), purpose="effect-check"
    )
    case(
        "stored-result",
        "get",
        "GET",
        "/.tasks/_doc/{task}",
        ("completed",),
        purpose="fixture-precondition",
    )
    case(
        "migration-before",
        "migration.get_feature_upgrade_status",
        "GET",
        "/_migration/system_features",
        ("stored-result",),
    )
    case(
        "migration-noop",
        "migration.post_feature_upgrade",
        "POST",
        "/_migration/system_features",
        ("migration-before",),
    )
    case(
        "migration-after",
        "migration.get_feature_upgrade_status",
        "GET",
        "/_migration/system_features",
        ("migration-noop",),
        purpose="effect-check",
    )
    case(
        "stored-after-noop",
        "get",
        "GET",
        "/.tasks/_doc/{task}",
        ("migration-after",),
        purpose="effect-check",
    )
    case("reset", "features.reset_features", "POST", "/_features/_reset", ("stored-after-noop",))
    case(
        "tasks-index-absent",
        "indices.exists",
        "HEAD",
        "/.tasks",
        ("reset",),
        (404,),
        "effect-check",
    )
    case("task-absent", "tasks.get", "GET", "/_tasks/{task}", ("reset",), (404,), "effect-check")
    case("target-after", "get", "GET", "/{target}/_doc/one", ("reset",), purpose="effect-check")
    case("source-after", "get", "GET", "/{source}/_doc/one", ("reset",), purpose="effect-check")
    case(
        "descriptor-remains",
        "features.get_features",
        "GET",
        "/_features",
        ("reset",),
        purpose="effect-check",
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
    return graph


def execute(run, catalog, prefix):
    values = {
        "source": prefix + "-feature-source",
        "target": prefix + "-feature-target",
        "task": "not-launched",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["feature." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["feature." + item for item in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def tasks_feature(data):
        return next(item for item in data["features"] if item["feature_name"] == "tasks")

    def stored_value(data):
        return data["_source"]["n"]

    def persisted(data):
        return data["_source"]["completed"]

    call("tasks-absent")
    try:
        for name in ["source", "target"]:
            call(
                name,
                {"settings": {"number_of_shards": 1, "number_of_replicas": 0}},
                assertions=[("acknowledged", lambda data: data["acknowledged"], True)],
            )
        call(
            "seed",
            {"n": 17},
            assertions=[("document created", lambda data: data["result"], "created")],
        )
        launched = call(
            "launch",
            {"source": {"index": values["source"]}, "dest": {"index": values["target"]}},
            assertions=[("task ID returned", lambda data: isinstance(data.get("task"), str), True)],
        )
        if launched.state == "passed":
            values["task"] = launched.data["task"]
        call(
            "completed",
            assertions=[
                ("task completed", lambda data: data["completed"], True),
                ("one document copied", lambda data: data["response"]["created"], 1),
                ("no failures", lambda data: data["response"]["failures"], []),
            ],
        )
        call(
            "target-before",
            assertions=[("actual copied document", stored_value, 17)],
            verifies=["launch"],
            semantic=True,
        )
        call("stored-result", assertions=[("persisted completed task", persisted, True)])
        call(
            "migration-before",
            assertions=[
                (
                    "no upgrade required",
                    lambda data: data["migration_status"],
                    "NO_MIGRATION_NEEDED",
                ),
                (
                    "tasks feature does not need migration",
                    lambda data: tasks_feature(data)["migration_status"],
                    "NO_MIGRATION_NEEDED",
                ),
                (
                    "actual tasks index listed",
                    lambda data: any(
                        item["index"] == ".tasks" for item in tasks_feature(data)["indices"]
                    ),
                    True,
                ),
            ],
        )
        call(
            "migration-noop",
            assertions=[("no migration accepted", lambda data: data["accepted"], False)],
        )
        call(
            "migration-after",
            assertions=[
                (
                    "migration remains unnecessary",
                    lambda data: data["migration_status"],
                    "NO_MIGRATION_NEEDED",
                )
            ],
            verifies=["migration-noop"],
            semantic=True,
        )
        call(
            "stored-after-noop",
            assertions=[("no-op preserves task state", persisted, True)],
            verifies=["migration-noop"],
            semantic=True,
        )
        call(
            "reset",
            assertions=[
                (
                    "tasks feature reset succeeded",
                    lambda data: tasks_feature(data)["status"],
                    "SUCCESS",
                )
            ],
        )
        call("tasks-index-absent", verifies=["reset"])
        call("task-absent", verifies=["reset"], semantic=True)
        call(
            "target-after",
            assertions=[("reset preserves target user data", stored_value, 17)],
            verifies=["reset"],
            semantic=True,
        )
        call(
            "source-after",
            assertions=[("reset preserves source user data", stored_value, 17)],
            verifies=["reset"],
            semantic=True,
        )
        call(
            "descriptor-remains",
            assertions=[
                (
                    "tasks descriptor remains available",
                    lambda data: any(item["name"] == "tasks" for item in data["features"]),
                    True,
                )
            ],
            verifies=["reset"],
            semantic=True,
        )
    finally:
        for name in ["source", "target"]:
            call("cleanup-" + name)
