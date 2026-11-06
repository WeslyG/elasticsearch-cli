"""Exact ES7.3 max_docs parsing, refusal effects and bounded writes."""

from evidence_runner import OMITTED

SLICED_LIMIT_RELEASES = {
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
}

PREPARED_VERSIONS = {
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
    "8.2.3",
    "8.3.3",
}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for operation in ["reindex", "update", "delete"]:
        base = "task-limit." + operation + "."
        api = {"reindex": "reindex", "update": "update_by_query", "delete": "delete_by_query"}[
            operation
        ]
        path = "/_reindex" if operation == "reindex" else "/{index}/_" + operation + "_by_query"
        for name, aid, method, route, status, deps in [
            ("create", "indices.create", "PUT", "/{index}", 200, ()),
            ("seed", "bulk", "POST", "/{index}/_bulk?refresh=true", 200, ("create",)),
            ("before", "count", "GET", "/{index}/_count", 200, ("seed",)),
            ("conflict", api, "POST", path + "?max_docs=2&refresh=true", 400, ("before",)),
            ("conflict-read", "count", "GET", "/{index}/_count", 200, ("conflict",)),
            ("invalid", api, "POST", path + "?max_docs=-2&refresh=true", 400, ("conflict-read",)),
            ("invalid-read", "count", "GET", "/{index}/_count", 200, ("invalid",)),
            ("bounded", api, "POST", path + "?max_docs=2&refresh=true", 200, ("invalid-read",)),
            ("effect", "count", "POST", "/{effect_index}/_count", 200, ("bounded",)),
            ("remaining", "count", "GET", "/{index}/_count", 200, ("bounded",)),
            ("cleanup", "indices.delete", "DELETE", "/{index}", 200, ("effect", "remaining")),
        ]:
            identifier = base + name
            add(identifier, aid, method, route, expected=(status,))
            graph[identifier] = tuple(base + d for d in deps)
        if version in SLICED_LIMIT_RELEASES:
            add(
                base + "slices",
                api,
                "POST",
                path + "?max_docs=1&slices=2&refresh=true",
                expected=(400,),
            )
            graph[base + "slices"] = (base + "invalid-read",)
            add(base + "slices-read", "count", "GET", "/{index}/_count", purpose="effect-check")
            graph[base + "slices-read"] = (base + "slices",)
            graph[base + "bounded"] += (base + "slices-read",)
        if operation == "reindex":
            for name in ["conflict", "invalid"] + (
                ["slices"] if version in SLICED_LIMIT_RELEASES else []
            ):
                identifier = base + name + "-target-absent"
                add(
                    identifier,
                    "indices.exists",
                    "HEAD",
                    "/{effect_index}",
                    expected=(404,),
                    purpose="effect-check",
                )
                graph[identifier] = (base + name,)
            graph[base + "bounded"] += (base + "invalid-target-absent",)
            if version in SLICED_LIMIT_RELEASES:
                graph[base + "bounded"] += (base + "slices-target-absent",)
            identifier = base + "cleanup-target"
            add(
                identifier,
                "indices.delete",
                "DELETE",
                "/{effect_index}",
                expected=(200,),
                purpose="fixture-cleanup",
            )
            graph[identifier] = (base + "cleanup",)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("max_docs recipe not prepared for exact release")
    for operation in ["reindex", "update", "delete"]:
        base = "task-limit." + operation + "."
        index = prefix + "-limit-" + operation
        values = {
            "index": index,
            "effect_index": index + "-target" if operation == "reindex" else index,
        }

        def call(name, body=OMITTED, assertions=(), verifies=()):
            case = catalog.cases[base + name]
            result = catalog.execute(
                run,
                case.id,
                values=values,
                body=body,
                assertions=assertions,
                depends_on=case.dependency_plan,
                semantic=bool(assertions),
                verifies=[base + d for d in verifies],
            )
            print(case.id, result.state, result.status, flush=True)
            return result

        call(
            "create",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {"properties": {"changed": {"type": "boolean"}}},
            },
        )
        lines = []
        for n in range(5):
            lines.extend(['{"index":{"_id":"' + str(n) + '"}}', '{"changed":false}'])
        call(
            "seed",
            ("\n".join(lines) + "\n").encode(),
            [("all seed items accepted", lambda d: d["errors"], False)],
        )
        call(
            "before",
            assertions=[("five real documents", lambda d: d["count"], 5)],
            verifies=("seed",),
        )

        def body(limit):
            result = {"max_docs": limit}
            if operation == "reindex":
                result.update(source={"index": index}, dest={"index": values["effect_index"]})
            else:
                result["query"] = {"match_all": {}}
                if operation == "update":
                    result["script"] = {"source": "ctx._source.changed = true"}
            return result

        call(
            "conflict",
            body(3),
            [
                (
                    "different max_docs values refused",
                    lambda d: "[max_docs] set to two different values" in str(d["error"]),
                    True,
                )
            ],
        )
        unchanged = {"query": {"term": {"changed": True}}} if operation == "update" else OMITTED
        # Count all source documents and separately query changed values for update.
        call(
            "conflict-read",
            unchanged,
            [
                (
                    "conflicting limit made no source change",
                    lambda d: d["count"],
                    0 if operation == "update" else 5,
                )
            ],
            verifies=("conflict",),
        )
        if operation == "reindex":
            call("conflict-target-absent", verifies=("conflict",))
        invalid_body = body(2)
        invalid_body.pop("max_docs")
        call(
            "invalid",
            invalid_body,
            [
                (
                    "negative limit refused",
                    lambda d: "[max_docs] parameter cannot be negative" in str(d["error"]),
                    True,
                )
            ],
        )
        call(
            "invalid-read",
            unchanged,
            [
                (
                    "invalid limit made no source change",
                    lambda d: d["count"],
                    0 if operation == "update" else 5,
                )
            ],
            verifies=("invalid",),
        )
        if operation == "reindex":
            call("invalid-target-absent", verifies=("invalid",))
        if catalog.version in SLICED_LIMIT_RELEASES:
            call(
                "slices",
                invalid_body,
                [
                    (
                        "limit smaller than slices refused",
                        lambda d: "[max_docs] should be >= [slices]" in str(d["error"]),
                        True,
                    )
                ],
            )
            call(
                "slices-read",
                unchanged,
                [
                    (
                        "sliced refusal made no source change",
                        lambda d: d["count"],
                        0 if operation == "update" else 5,
                    )
                ],
                verifies=("slices",),
            )
            if operation == "reindex":
                call("slices-target-absent", verifies=("slices",))
        key = {"reindex": "created", "update": "updated", "delete": "deleted"}[operation]
        call(
            "bounded",
            body(2),
            [
                ("exactly two processed", lambda d: d[key], 2),
                ("no operation failures", lambda d: d["failures"], []),
            ],
        )
        effect_body = {"query": {"term": {"changed": True}}} if operation == "update" else OMITTED
        call(
            "effect",
            effect_body,
            [
                (
                    "independent bounded effect",
                    lambda d: d["count"],
                    3 if operation == "delete" else 2,
                )
            ],
            verifies=("bounded",),
        )
        call(
            "remaining",
            assertions=[
                (
                    "source count after limit",
                    lambda d: d["count"],
                    3 if operation == "delete" else 5,
                )
            ],
            verifies=("bounded",),
        )
        call("cleanup")
        if operation == "reindex":
            call("cleanup-target")
