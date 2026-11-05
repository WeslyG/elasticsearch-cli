"""Clone/split/shrink actual shard layouts and copy independence."""

import json

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("resize." + name, api, method, path, expected=expected, purpose=purpose)
        graph["resize." + name] = tuple("resize." + d for d in deps)

    for operation in ["clone", "split", "shrink"]:

        def own(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
            case(
                operation + "." + name,
                api,
                method,
                path,
                tuple(operation + "." + d for d in deps),
                expected,
                purpose,
            )

        own("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
        own(
            "seed",
            "bulk",
            "POST",
            "/{index}/_bulk?refresh=true",
            ("create",),
            purpose="fixture-setup",
        )
        own(
            "seed-count",
            "count",
            "GET",
            "/{index}/_count",
            ("seed",),
            purpose="fixture-precondition",
        )
        own(
            "block",
            "indices.put_settings",
            "PUT",
            "/{index}/_settings",
            ("seed-count",),
            purpose="fixture-setup",
        )
        for method in ["PUT", "POST"]:
            stem = method.lower()
            own(
                stem,
                "indices." + operation,
                method,
                "/{index}/_" + operation + "/{target}?wait_for_active_shards=all",
                ("block",),
            )
            own(
                stem + ".ready",
                "cluster.health",
                "GET",
                "/_cluster/health/{target}?wait_for_status=green&timeout=10s",
                (stem,),
            )
            own(
                stem + ".count",
                "count",
                "GET",
                "/{target}/_count",
                (stem + ".ready",),
                purpose="effect-check",
            )
            own(
                stem + ".settings",
                "indices.get_settings",
                "GET",
                "/{target}/_settings?flat_settings=true",
                (stem + ".ready",),
                purpose="effect-check",
            )
            own(
                stem + ".write",
                "index",
                "PUT",
                "/{target}/_doc/new?refresh=true",
                (stem + ".count",),
                (201,),
            )
            own(
                stem + ".readback",
                "get",
                "GET",
                "/{target}/_doc/new",
                (stem + ".write",),
                purpose="effect-check",
            )
            own(
                stem + ".count-after",
                "count",
                "GET",
                "/{target}/_count",
                (stem + ".write",),
                purpose="effect-check",
            )
        own(
            "source-count",
            "count",
            "GET",
            "/{index}/_count",
            ("put.count-after", "post.count-after"),
            purpose="effect-check",
        )
        own("source-blocked", "index", "PUT", "/{index}/_doc/new", ("block",), (403,))
        own(
            "source-absent",
            "get",
            "GET",
            "/{index}/_doc/new",
            ("source-blocked",),
            (404,),
            purpose="effect-check",
        )
        for name, path in [
            ("cleanup-source", "/{index}"),
            ("cleanup-put", "/{targetput}"),
            ("cleanup-post", "/{targetpost}"),
        ]:
            own(name, "indices.delete", "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    for operation in ["clone", "split", "shrink"]:
        values = {
            "index": prefix + "-" + operation,
            "targetput": prefix + "-" + operation + "-put",
            "targetpost": prefix + "-" + operation + "-post",
        }
        source_shards = 2 if operation == "shrink" else 1
        target_shards = 2 if operation == "split" else 1

        def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
            case = catalog.cases["resize." + operation + "." + name]
            result = catalog.execute(
                run,
                case.id,
                values=values,
                body=body,
                assertions=assertions,
                depends_on=case.dependency_plan,
                semantic=semantic,
                verifies=["resize." + operation + "." + n for n in verifies],
                content_type="application/x-ndjson" if ndjson else "application/json",
            )
            print(case.id, result.state, result.status, flush=True)
            return result

        ack = [("acknowledged", lambda d: d["acknowledged"], True)]
        settings = {
            "number_of_shards": source_shards,
            "number_of_replicas": 0,
            "number_of_routing_shards": 2,
        }
        call(
            "create",
            {"settings": settings, "mappings": {"properties": {"n": {"type": "integer"}}}},
            ack,
        )
        try:
            parts = []
            for n in range(12):
                parts.extend([{"index": {"_id": str(n)}}, {"n": n}])
            call(
                "seed",
                ("\n".join(json.dumps(p) for p in parts) + "\n").encode(),
                [("bulk no errors", lambda d: d["errors"], False)],
                ndjson=True,
            )
            call("seed-count", assertions=[("twelve source documents", lambda d: d["count"], 12)])
            call("block", {"index.blocks.write": True}, ack)
            for method in ["put", "post"]:
                values["target"] = values["target" + method]
                target = values["target"]
                call(
                    method,
                    {
                        "settings": {
                            "number_of_shards": target_shards,
                            "number_of_replicas": 0,
                            "index.blocks.write": False,
                        }
                    },
                    ack,
                )
                call(
                    method + ".ready",
                    assertions=[
                        ("target green", lambda d: d["status"], "green"),
                        ("wait completed", lambda d: d["timed_out"], False),
                    ],
                )
                call(
                    method + ".count",
                    assertions=[("all source documents copied", lambda d: d["count"], 12)],
                    verifies=[method],
                    semantic=True,
                )
                call(
                    method + ".settings",
                    assertions=[
                        (
                            "target shard count",
                            lambda d, t=target: d[t]["settings"]["index.number_of_shards"],
                            str(target_shards),
                        ),
                        (
                            "target writes enabled",
                            lambda d, t=target: d[t]["settings"]["index.blocks.write"],
                            "false",
                        ),
                    ],
                    verifies=[method],
                    semantic=True,
                )
                call(method + ".write", {"n": 99})
                call(
                    method + ".readback",
                    assertions=[("target write persisted", lambda d: d["_source"]["n"], 99)],
                    verifies=[method + ".write"],
                    semantic=True,
                )
                call(
                    method + ".count-after",
                    assertions=[
                        ("target independently has thirteen documents", lambda d: d["count"], 13)
                    ],
                    verifies=[method + ".write"],
                    semantic=True,
                )
            call(
                "source-count",
                assertions=[("source still has twelve documents", lambda d: d["count"], 12)],
                verifies=["put.write", "post.write"],
                semantic=True,
            )
            call(
                "source-blocked",
                {"n": 99},
                [
                    (
                        "source remains blocked",
                        lambda d: d["error"]["type"],
                        "cluster_block_exception",
                    )
                ],
            )
            call(
                "source-absent",
                assertions=[("failed source write absent", lambda d: d["found"], False)],
                verifies=["source-blocked"],
            )
        finally:
            call("cleanup-source")
            call("cleanup-put")
            call("cleanup-post")
