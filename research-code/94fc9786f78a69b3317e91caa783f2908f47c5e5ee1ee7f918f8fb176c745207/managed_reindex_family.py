"""Dedicated reindex-management API, including both cancel wait modes."""

import json

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("managed-reindex." + name, api, method, path, expected=expected, purpose=purpose)
        graph["managed-reindex." + name] = tuple("managed-reindex." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed", "bulk", "POST", "/{index}/_bulk?refresh=true", ("create",), purpose="fixture-setup"
    )
    case(
        "source-count", "count", "GET", "/{index}/_count", ("seed",), purpose="fixture-precondition"
    )
    for variant in ["wait", "no-wait"]:

        def own(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
            case(
                variant + "." + name,
                api,
                method,
                path,
                tuple(variant + "." + d for d in deps),
                expected,
                purpose,
            )

        own("target", "indices.create", "PUT", "/{target}", purpose="fixture-setup")
        case(
            variant + ".submit",
            "reindex",
            "POST",
            "/_reindex?wait_for_completion=false&requests_per_second=0.2",
            ("source-count", variant + ".target"),
        )
        own("get", "reindex_get", "GET", "/_reindex/{task_id}", ("submit",))
        own(
            "get-false",
            "reindex_get",
            "GET",
            "/_reindex/{task_id}?wait_for_completion=false",
            ("get",),
        )
        own("list-default", "reindex_list", "GET", "/_reindex", ("get",))
        own("list-detailed", "reindex_list", "GET", "/_reindex?detailed=true", ("get",))
        own(
            "cancel",
            "reindex_cancel",
            "POST",
            "/_reindex/{task_id}/_cancel?wait_for_completion="
            + ("true" if variant == "wait" else "false"),
            ("get",),
        )
        own(
            "completed",
            "reindex_get",
            "GET",
            "/_reindex/{task_id}?wait_for_completion=true&timeout=5s",
            ("cancel",),
            purpose="effect-check",
        )
        own(
            "not-listed", "reindex_list", "GET", "/_reindex", ("completed",), purpose="effect-check"
        )
        own(
            "refresh-target",
            "indices.refresh",
            "POST",
            "/{target}/_refresh",
            ("completed",),
            purpose="fixture-setup",
        )
        own(
            "cancel-effect",
            "count",
            "GET",
            "/{target}/_count",
            ("refresh-target",),
            purpose="effect-check",
        )
        own(
            "cleanup-cancel",
            "tasks.cancel",
            "POST",
            "/_tasks/{task_id}/_cancel?wait_for_completion=true",
            ("submit",),
            (200, 404),
            purpose="cleanup",
        )
        own(
            "cleanup-target",
            "indices.delete",
            "DELETE",
            "/{target}",
            expected=(200, 404),
            purpose="cleanup",
        )
    case("invalid-get", "reindex_get", "GET", "/_reindex/invalid-id", expected=(400,))
    case(
        "invalid-cancel", "reindex_cancel", "POST", "/_reindex/invalid-id/_cancel", expected=(400,)
    )
    case(
        "cleanup-source",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-managed-source",
        "target": "unavailable",
        "task_id": "unavailable",
    }
    tasks = {}

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
        case = catalog.cases["managed-reindex." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["managed-reindex." + n for n in verifies],
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    settings = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": {"n": {"type": "integer"}}},
    }
    call("create", settings, ack)
    try:
        parts = []
        for n in range(20):
            parts.extend([{"index": {"_id": str(n)}}, {"n": n}])
        call(
            "seed",
            ("\n".join(json.dumps(p) for p in parts) + "\n").encode(),
            [("seed no errors", lambda d: d["errors"], False)],
            ndjson=True,
        )
        call("source-count", assertions=[("twenty source documents", lambda d: d["count"], 20)])
        for variant in ["wait", "no-wait"]:
            values["target"] = prefix + "-managed-" + variant
            call(variant + ".target", settings, ack)
            response = call(
                variant + ".submit",
                {
                    "source": {"index": values["index"], "size": 1},
                    "dest": {"index": values["target"]},
                },
                [("async task ID", lambda d: bool(d["task"]), True)],
            )
            task_id = (response.data or {}).get("task", "unavailable")
            tasks[variant] = task_id
            values["task_id"] = task_id
            for name in ["get", "get-false"]:
                call(
                    variant + "." + name,
                    assertions=[
                        ("running reindex", lambda d: d["completed"], False),
                        ("flattened task identity", lambda d: d["id"], task_id),
                        ("twenty matching documents", lambda d: d["status"]["total"], 20),
                    ],
                )
            for name in ["list-default", "list-detailed"]:
                call(
                    variant + "." + name,
                    assertions=[
                        (
                            "running task listed",
                            lambda d: any(t["id"] == task_id for t in d["reindex"]),
                            True,
                        )
                    ],
                )
            checks = [("acknowledged without waiting", lambda d: d["acknowledged"], True)]
            if variant == "wait":
                checks = [
                    ("cancel waited for completion", lambda d: d["completed"], True),
                    ("task cancelled", lambda d: d["cancelled"], True),
                ]
            call(variant + ".cancel", assertions=checks)
            call(
                variant + ".completed",
                assertions=[
                    ("completed after cancellation", lambda d: d["completed"], True),
                    (
                        "cancellation outcome retained",
                        lambda d: bool(d["response"].get("canceled")),
                        True,
                    ),
                ],
                verifies=[variant + ".cancel"],
                semantic=True,
            )
            call(
                variant + ".not-listed",
                assertions=[
                    (
                        "finished task omitted from running list",
                        lambda d: any(t["id"] == task_id for t in d["reindex"]),
                        False,
                    )
                ],
                verifies=[variant + ".cancel"],
                semantic=True,
            )
            call(
                variant + ".refresh-target",
                assertions=[("refresh no failures", lambda d: d["_shards"]["failed"], 0)],
            )
            call(
                variant + ".cancel-effect",
                assertions=[
                    (
                        "cancellation prevented full copy after explicit refresh",
                        lambda d: d["count"] < 20,
                        True,
                    )
                ],
                verifies=[variant + ".cancel"],
                semantic=True,
            )
        call(
            "invalid-get",
            assertions=[
                (
                    "malformed task rejected",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
        call(
            "invalid-cancel",
            assertions=[
                (
                    "malformed task rejected",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                )
            ],
        )
    finally:
        for variant in ["wait", "no-wait"]:
            values["target"] = prefix + "-managed-" + variant
            values["task_id"] = tasks.get(variant, "unavailable")
            call(variant + ".cleanup-cancel")
            call(variant + ".cleanup-target")
        call("cleanup-source")
