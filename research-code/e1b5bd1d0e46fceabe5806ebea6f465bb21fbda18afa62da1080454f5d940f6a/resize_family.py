"""Clone/split/shrink actual shard layouts and copy independence."""

import json

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES, LEGACY_SPLIT_RELEASES


def operations_for(version):
    if version in {
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
    }:
        return ["clone", "split", "shrink"]
    if version in EARLY_SEVEN_RELEASES:
        return ["split", "shrink"]
    if version in LEGACY_SPLIT_RELEASES:
        return ["shrink", "split"]
    return ["shrink"] if version.startswith("6.") else ["clone", "split", "shrink"]


def declare(add, version="9.5.6"):
    legacy = version.startswith("6.")
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if legacy:
            path = path.replace("/_doc/", "/fixture/")
        add("resize." + name, api, method, path, expected=expected, purpose=purpose)
        graph["resize." + name] = tuple("resize." + d for d in deps)

    for operation in operations_for(version):

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
            if operation == "split":
                own(
                    stem + ".unprefixed",
                    "indices.split",
                    method,
                    "/{index}/_split/{target}",
                    ("block",),
                    (400,),
                )
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


def execute(run, catalog, prefix, operations=None):
    legacy = catalog.version.startswith("6.")
    for operation in operations or operations_for(catalog.version):
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
        mappings = {"properties": {"n": {"type": "integer"}}}
        if legacy:
            if operation != "split":
                settings.pop("number_of_routing_shards")
            mappings = {"fixture": mappings}
        call(
            "create",
            {"settings": settings, "mappings": mappings},
            ack,
        )
        try:
            parts = []
            for n in range(12):
                parts.extend(
                    [
                        {"index": {"_id": str(n), **({"_type": "fixture"} if legacy else {})}},
                        {"n": n},
                    ]
                )
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
                if operation == "split":
                    call(
                        method + ".unprefixed",
                        {"settings": {"number_of_shards": target_shards}},
                        [
                            (
                                "split validates prefixed shard count",
                                lambda d: d["error"]["type"],
                                "action_request_validation_exception",
                            )
                        ],
                    )
                call(
                    method,
                    {
                        "settings": {
                            "index.number_of_shards": target_shards,
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
