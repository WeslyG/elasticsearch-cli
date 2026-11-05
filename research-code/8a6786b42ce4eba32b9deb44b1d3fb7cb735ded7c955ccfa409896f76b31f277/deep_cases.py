"""Live anchor recipes. Plain Python functions, explicit declared cases, no SDK."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from cat_family import execute as cat_family
from cluster_family import execute as cluster_family
from document_family import execute as document_family
from evidence_runner import Session
from feature_family import execute as feature_family
from legacy_document_family import execute as legacy_document_family
from legacy_metadata_family import execute as legacy_metadata_family
from managed_reindex_family import execute as managed_reindex_family
from metadata_family import execute as metadata_family
from module_family import execute as module_family
from query_family import execute as query_family
from repository_family import execute as repository_family
from resize_family import execute as resize_family
from scenario_catalog import Catalog
from stream_family import execute as stream_family
from synonym_family import execute as synonym_family
from template_family import execute as template_family
from topology_family import execute as topology_family
from transform_family import execute as transform_family
from wire_family import execute as wire_family


def index_body(version):
    mapping = {"properties": {"n": {"type": "integer"}, "group": {"type": "keyword"}}}
    if version.startswith("6."):
        mapping = {"fixture": mapping}
    return {"settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": mapping}


def ndjson(version, index, documents, *, include_index=True):
    lines = []
    for identifier, source in documents:
        metadata = {"_id": identifier}
        if include_index:
            metadata["_index"] = index
        if version.startswith("6."):
            metadata["_type"] = "fixture"
        lines.extend([json.dumps({"index": metadata}), json.dumps(source)])
    return ("\n".join(lines) + "\n").encode()


def total_hits(data):
    total = data["hits"]["total"]
    return total["value"] if isinstance(total, dict) else total


def bulk_family(run, catalog, prefix):
    version = catalog.version
    values = {
        "index": prefix + "-bulk",
        "doc_type": "fixture" if version.startswith("6.") else "_doc",
    }

    def call(identifier, **kwargs):
        result = catalog.execute(run, identifier, values=values, **kwargs)
        print(identifier, result.state, result.status, flush=True)
        return result

    call(
        "fixture.create",
        body=index_body(version),
        assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        number = 0
        for method in ["POST", "PUT"]:
            for variant in ["global", "index"]:
                number += 1
                stem = "bulk." + method.lower() + "." + variant
                values["id"] = stem
                payload = ndjson(
                    version,
                    values["index"],
                    [(stem, {"n": number, "group": "bulk"})],
                    include_index=variant == "global",
                )
                call(
                    stem,
                    body=payload,
                    content_type="application/x-ndjson",
                    depends_on=["fixture.create"],
                    assertions=[
                        ("no per-item errors", lambda d: d["errors"], False),
                        ("one successful item", lambda d: d["items"][0]["index"]["status"], 201),
                    ],
                    semantic=True,
                )
                call(
                    stem + ".readback",
                    depends_on=[stem],
                    verifies=[stem],
                    semantic=True,
                    assertions=[("persisted n", lambda d: d["_source"]["n"], number)],
                )
                call(
                    stem + ".search-visible",
                    depends_on=[stem],
                    verifies=[stem],
                    semantic=True,
                    body={"query": {"ids": {"values": [stem]}}},
                    assertions=[("visible after refresh=true", total_hits, 1)],
                )
        call(
            "bulk.partial",
            depends_on=["fixture.create"],
            semantic=True,
            body=ndjson(
                version,
                values["index"],
                [("partial-valid", {"n": 99}), ("partial-invalid", {"n": "not-an-integer"})],
            ),
            content_type="application/x-ndjson",
            assertions=[
                ("partial errors flag", lambda d: d["errors"], True),
                ("valid item created", lambda d: d["items"][0]["index"]["status"], 201),
                ("invalid item rejected", lambda d: d["items"][1]["index"]["status"], 400),
            ],
        )
        for suffix in ["valid", "invalid"]:
            values["id"] = "partial-" + suffix
            call(
                "bulk.partial." + suffix,
                depends_on=["bulk.partial"],
                verifies=["bulk.partial"],
                semantic=True,
                assertions=[
                    (
                        "independent partial item state",
                        lambda d: (
                            d.get("_source", {}).get("n") if suffix == "valid" else d["found"]
                        ),
                        99 if suffix == "valid" else False,
                    )
                ],
            )
        missing = ndjson(version, values["index"], [("no-newline", {"n": 1})])[:-1]
        call(
            "bulk.missing-newline",
            depends_on=["fixture.create"],
            body=missing,
            content_type="application/x-ndjson",
            semantic=True,
            assertions=[
                ("malformed request has structured error", lambda d: bool(d.get("error")), True)
            ],
        )
    finally:
        call("bulk.cleanup")


def task_family(run, catalog, prefix, operation):
    version = catalog.version
    legacy = version.startswith("6.")
    stem = "task." + operation
    values = {
        "index": prefix + "-" + operation,
        "target": prefix + "-" + operation + "-target",
        "task_id": "not-created",
    }

    def call(suffix, **kwargs):
        identifier = stem + "." + suffix
        result = catalog.execute(run, identifier, values=values, **kwargs)
        print(identifier, result.state, result.status, flush=True)
        return result

    call(
        "create",
        body=index_body(version),
        assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
    )
    submit = None
    try:
        if legacy and operation == "reindex":
            call(
                "cancel-parameter-probe",
                depends_on=[stem + ".create"],
                assertions=[
                    (
                        "wait_for_completion rejected by legacy cancel",
                        lambda d: "wait_for_completion" in d["error"]["reason"],
                        True,
                    )
                ],
            )
        call(
            "seed",
            depends_on=[stem + ".create"],
            body=ndjson(
                version,
                values["index"],
                [(str(i), {"n": 0}) for i in range(40)],
                include_index=False,
            ),
            content_type="application/x-ndjson",
            assertions=[
                ("seed has no bulk errors", lambda d: d["errors"], False),
                ("40 seed responses", lambda d: len(d["items"]), 40),
            ],
        )
        call(
            "count",
            depends_on=[stem + ".seed"],
            assertions=[("40 visible documents before task", lambda d: d["count"], 40)],
        )
        if operation == "reindex":
            body = {
                "source": {"index": values["index"], "size": 1},
                "dest": {"index": values["target"]},
            }
        elif operation == "update":
            body = {
                "query": {"match_all": {}},
                "script": {"source": "ctx._source.n = 1", "lang": "painless"},
            }
        else:
            body = {"query": {"match_all": {}}}
        submit = call(
            "submit",
            body=body,
            depends_on=[stem + ".count"],
            assertions=[
                (
                    "task id returned",
                    lambda d: isinstance(d.get("task"), str) and ":" in d["task"],
                    True,
                )
            ],
        )
        if isinstance(submit.data, dict) and isinstance(submit.data.get("task"), str):
            values["task_id"] = submit.data["task"]
        call(
            "get-running",
            depends_on=[stem + ".submit"],
            assertions=[
                ("task still running", lambda d: d["completed"], False),
                ("task cancellable", lambda d: d["task"]["cancellable"], True),
            ],
        )

        if legacy and operation == "reindex":
            call(
                "list-group-probe",
                depends_on=[stem + ".get-running"],
                assertions=[
                    (
                        "legacy group_by choices enforced",
                        lambda d: "group_by" in d["error"]["reason"],
                        True,
                    )
                ],
            )

        def task_visible(data):
            return any(
                str(task["node"]) + ":" + str(task["id"]) == values["task_id"]
                for task in (
                    [
                        task
                        for node in data.get("nodes", {}).values()
                        for task in node.get("tasks", {}).values()
                    ]
                    if legacy
                    else data["tasks"]
                )
            )

        call(
            "list",
            depends_on=[stem + ".get-running"],
            semantic=True,
            assertions=[("submitted task visible in group_by=none", task_visible, True)],
        )
        call(
            "rethrottle",
            depends_on=[stem + ".get-running"],
            assertions=[
                ("no node failures", lambda d: d.get("node_failures", []), []),
                ("has node task response", lambda d: bool(d.get("nodes")), True),
            ],
        )
        call(
            "rate-readback",
            depends_on=[stem + ".rethrottle"],
            verifies=[stem + ".rethrottle"],
            semantic=True,
            assertions=[
                (
                    "requests_per_second changed to 1",
                    lambda d: d["task"]["status"]["requests_per_second"],
                    1,
                )
            ],
        )

        def cancelled(data):
            return any(
                (
                    str(task.get("node")) + ":" + str(task.get("id")) == values["task_id"]
                    and task.get("cancellable") is True
                    if legacy
                    else task.get("cancelled") is True
                )
                for node in data.get("nodes", {}).values()
                for task in node.get("tasks", {}).values()
            )

        call(
            "cancel",
            depends_on=[stem + ".submit"],
            semantic=not legacy,
            assertions=[
                (
                    "requested task returned by cancellation"
                    if legacy
                    else "cancelled task reported",
                    cancelled,
                    True,
                )
            ],
        )
        call(
            "completed",
            depends_on=[stem + ".cancel"],
            verifies=[stem + ".cancel"],
            semantic=True,
            assertions=[("cancelled task finished", lambda d: d["completed"], True)]
            + (
                [
                    (
                        "stored result carries cancellation",
                        lambda d: bool(
                            d.get("response", {}).get("canceled")
                            or d.get("task", {}).get("status", {}).get("canceled")
                            or d.get("error", {}).get("type") == "task_cancelled_exception"
                        ),
                        True,
                    )
                ]
                if legacy
                else []
            ),
        )
        if legacy:
            call(
                "refresh-remaining",
                depends_on=[stem + ".completed"],
                assertions=[
                    (
                        "refresh successful or target not created",
                        lambda d: (
                            d.get("_shards", {}).get("failed") == 0
                            or d.get("error", {}).get("type") == "index_not_found_exception"
                        ),
                        True,
                    )
                ],
            )

        def remaining(data):
            if operation == "reindex":
                return (
                    data["count"] < 40
                    if "count" in data
                    else data.get("error", {}).get("type") == "index_not_found_exception"
                )
            return data["count"] > 0

        body = {"query": {"term": {"n": 0}}} if operation == "update" else None
        kwargs = {"body": body} if body is not None else {}
        call(
            "remaining",
            depends_on=[stem + (".refresh-remaining" if legacy else ".completed")],
            verifies=[stem + ".cancel"],
            semantic=True,
            assertions=[("operation did not consume all 40 documents", remaining, True)],
            **kwargs,
        )
    finally:
        if submit is not None:
            call("cleanup-cancel", depends_on=[stem + ".submit"])
            call(
                "cleanup-wait",
                depends_on=[stem + ".submit"],
                assertions=[
                    (
                        "task finished or result gone",
                        lambda d: (
                            d.get("completed") is True
                            or d.get("error", {}).get("type") == "resource_not_found_exception"
                        ),
                        True,
                    )
                ],
            )
            prerequisites = [stem + ".cleanup-wait"]
        else:
            prerequisites = []
        call("cleanup-source", depends_on=prerequisites)
        if operation == "reindex":
            call("cleanup-target", depends_on=prerequisites)


def snapshot_family(run, catalog, prefix):
    legacy = catalog.version.startswith("6.")
    values = {
        "index": prefix + "-snapshot",
        "repository": prefix + "-repo",
        "doc_type": "fixture" if catalog.version.startswith("6.") else "_doc",
    }

    def call(suffix, **kwargs):
        identifier = "snapshot." + suffix
        result = catalog.execute(run, identifier, values=values, **kwargs)
        print(identifier, result.state, result.status, flush=True)
        return result

    call(
        "create-index",
        body=index_body(catalog.version),
        assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        call(
            "seed",
            body={"n": 42},
            depends_on=["snapshot.create-index"],
            assertions=[("created", lambda d: d["result"], "created")],
        )
        call(
            "repository",
            body={"type": "fs", "settings": {"location": "/tmp/es-snapshots/" + prefix}},
            assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
        )
        call(
            "create",
            body={"indices": values["index"], "include_global_state": False},
            depends_on=["snapshot.seed", "snapshot.repository"],
            assertions=[
                ("source snapshot successful", lambda d: d["snapshot"]["state"], "SUCCESS")
            ],
        )
        if not legacy:
            call(
                "clone",
                body={"indices": values["index"]},
                depends_on=["snapshot.create"],
                assertions=[("clone acknowledged", lambda d: d["acknowledged"], True)],
            )
            deadline = time.monotonic() + 10
            last_poll = "snapshot.clone"
            for attempt in range(20):
                result = call(
                    "clone-poll." + str(attempt),
                    depends_on=["snapshot.clone"],
                    deadline=max(0.1, deadline - time.monotonic()),
                    assertions=[("clone record exists", lambda d: len(d["snapshots"]), 1)],
                )
                last_poll = result.scenario_id
                if not result.passed or result.data["snapshots"][0]["state"] == "SUCCESS":
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
            call(
                "clone-metadata",
                depends_on=[last_poll],
                verifies=["snapshot.clone"],
                semantic=True,
                assertions=[
                    ("cloned snapshot successful", lambda d: d["snapshots"][0]["state"], "SUCCESS"),
                    (
                        "cloned index membership",
                        lambda d: d["snapshots"][0]["indices"],
                        [values["index"]],
                    ),
                ],
            )
        call(
            "delete-source-index",
            depends_on=["snapshot.create"] if legacy else ["snapshot.clone-metadata"],
            assertions=[("source index deleted", lambda d: d["acknowledged"], True)],
        )
        call(
            "source-absent",
            depends_on=["snapshot.delete-source-index"],
            verifies=["snapshot.delete-source-index"],
            semantic=True,
        )
        call(
            "restore",
            body={"indices": values["index"], "include_global_state": False},
            depends_on=["snapshot.source-absent"],
            assertions=[
                ("restore has no failed shards", lambda d: d["snapshot"]["shards"]["failed"], 0)
            ],
        )
        call(
            "restored-document",
            depends_on=["snapshot.restore"],
            verifies=["snapshot.restore"] if legacy else ["snapshot.clone", "snapshot.restore"],
            semantic=True,
            assertions=[("original value restored from snapshot", lambda d: d["_source"]["n"], 42)],
        )
    finally:
        call("cleanup-index")
        call("cleanup-snapshots")
        call("cleanup-repository")


def reopen_family(run, catalog, prefix):
    values = {
        "index": prefix + "-reopen",
        "target": prefix + "-reindexed",
        "doc_type": "fixture" if catalog.version.startswith("6.") else "_doc",
    }

    def call(suffix, **kwargs):
        identifier = "reopen." + suffix
        result = catalog.execute(run, identifier, values=values, **kwargs)
        print(identifier, result.state, result.status, flush=True)
        return result

    call(
        "create",
        body=index_body(catalog.version),
        assertions=[("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        call(
            "seed",
            body={"n": 42},
            depends_on=["reopen.create"],
            assertions=[("created", lambda d: d["result"], "created")],
        )
        call(
            "close",
            depends_on=["reopen.seed"],
            assertions=[("closed acknowledged", lambda d: d["acknowledged"], True)],
        )
        checks = [("acknowledged", lambda d: d["acknowledged"], True)]
        if catalog.version.startswith("6.0."):
            checks = [
                (
                    "unsupported query parameter",
                    lambda d: "unrecognized parameter" in d["error"]["reason"],
                    True,
                )
            ]
        call("parameter-probe", depends_on=["reopen.close"], assertions=checks, semantic=True)
        call(
            "open-without-parameter",
            depends_on=["reopen.close"],
            assertions=[("reopen acknowledged", lambda d: d["acknowledged"], True)],
        )
        call(
            "readback",
            depends_on=["reopen.open-without-parameter"],
            verifies=["reopen.open-without-parameter"],
            semantic=True,
            assertions=[("original document retained", lambda d: d["_source"]["n"], 42)],
        )
        call(
            "analyze",
            depends_on=["reopen.open-without-parameter"],
            body={"analyzer": "standard", "text": "Hello World"},
            assertions=[
                ("analyzer tokens", lambda d: [x["token"] for x in d["tokens"]], ["hello", "world"])
            ],
            semantic=True,
        )
        call(
            "refresh",
            depends_on=["reopen.open-without-parameter"],
            assertions=[("no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call(
            "reindex",
            depends_on=["reopen.open-without-parameter"],
            body={"source": {"index": values["index"]}, "dest": {"index": values["target"]}},
            assertions=[
                ("one document copied", lambda d: d["created"], 1),
                ("no bulk failures", lambda d: d["failures"], []),
            ],
        )
        call(
            "reindex-count",
            depends_on=["reopen.reindex"],
            verifies=["reopen.reindex"],
            semantic=True,
            assertions=[("target has original document", lambda d: d["count"], 1)],
        )
        call(
            "update-query",
            depends_on=["reopen.open-without-parameter"],
            body={
                "query": {"match_all": {}},
                "script": {"source": "ctx._source.n = 43", "lang": "painless"},
            },
            assertions=[("one document updated", lambda d: d["updated"], 1)],
        )
        call(
            "updated-document",
            depends_on=["reopen.update-query"],
            verifies=["reopen.update-query"],
            semantic=True,
            assertions=[("new source value", lambda d: d["_source"]["n"], 43)],
        )
        call(
            "delete-query",
            depends_on=["reopen.updated-document"],
            body={"query": {"match_all": {}}},
            assertions=[("one document deleted", lambda d: d["deleted"], 1)],
        )
        call(
            "empty-count",
            depends_on=["reopen.delete-query"],
            verifies=["reopen.delete-query"],
            semantic=True,
            assertions=[("index empty", lambda d: d["count"], 0)],
        )
    finally:
        call("cleanup-source")
        call("cleanup-target")


def maintenance_family(run, catalog, prefix):
    values = {"index": prefix + "-maintenance"}
    index = values["index"]

    def call(suffix, **kwargs):
        identifier = "maintenance." + suffix
        result = catalog.execute(run, identifier, values=values, **kwargs)
        print(identifier, result.state, result.status, flush=True)
        return result

    def request_cache(data):
        return data["indices"][index]["primaries"]["request_cache"]

    def segments(data):
        return sum(
            len(shard["segments"])
            for group in data["indices"][index]["shards"].values()
            for shard in group
            if shard["routing"]["primary"]
        )

    body = index_body(catalog.version)
    body["settings"]["refresh_interval"] = "-1"
    body["settings"]["index.requests.cache.enable"] = True
    call("create", body=body, assertions=[("acknowledged", lambda d: d["acknowledged"], True)])
    try:
        for batch in range(3):
            call(
                "seed." + str(batch),
                depends_on=["maintenance.create"],
                body=ndjson(
                    catalog.version,
                    index,
                    [
                        (str(i), {"n": i, "group": "g" + str(i % 3)})
                        for i in range(batch * 30, (batch + 1) * 30)
                    ],
                    include_index=False,
                ),
                content_type="application/x-ndjson",
                assertions=[("bulk has no errors", lambda d: d["errors"], False)],
            )
            call(
                "flush." + str(batch),
                depends_on=["maintenance.seed." + str(batch)],
                assertions=[("no failed shards", lambda d: d["_shards"]["failed"], 0)],
            )
        call(
            "seed-count",
            depends_on=[
                "maintenance.seed.0",
                "maintenance.seed.1",
                "maintenance.seed.2",
                "maintenance.flush.0",
                "maintenance.flush.1",
                "maintenance.flush.2",
            ],
            assertions=[("90 fixture documents visible", lambda d: d["count"], 90)],
        )
        query = {"size": 0, "aggs": {"sum": {"sum": {"field": "n"}}}}
        checks = [("correct aggregation", lambda d: d["aggregations"]["sum"]["value"], 4005)]
        call("warm1", depends_on=["maintenance.seed-count"], body=query, assertions=checks)
        call("warm2", depends_on=["maintenance.warm1"], body=query, assertions=checks)
        call(
            "cache-before",
            depends_on=["maintenance.warm2"],
            assertions=[
                ("nonempty cache", lambda d: request_cache(d)["memory_size_in_bytes"] > 0, True),
                ("cache hit observed", lambda d: request_cache(d)["hit_count"] > 0, True),
            ],
        )
        call(
            "clear-cache",
            depends_on=["maintenance.cache-before"],
            assertions=[("no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call(
            "cache-after",
            depends_on=["maintenance.clear-cache"],
            verifies=["maintenance.clear-cache"],
            semantic=True,
            assertions=[
                ("request cache empty", lambda d: request_cache(d)["memory_size_in_bytes"], 0)
            ],
        )
        call("rewarm", depends_on=["maintenance.cache-after"], body=query, assertions=checks)
        call(
            "global-cache-before",
            depends_on=["maintenance.rewarm"],
            assertions=[
                (
                    "cache refilled before global clear",
                    lambda d: request_cache(d)["memory_size_in_bytes"] > 0,
                    True,
                )
            ],
        )
        call(
            "clear-cache-global",
            depends_on=["maintenance.global-cache-before"],
            assertions=[("global clear has no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call(
            "global-cache-after",
            depends_on=["maintenance.clear-cache-global"],
            verifies=["maintenance.clear-cache-global"],
            semantic=True,
            assertions=[
                (
                    "global clear emptied fixture cache",
                    lambda d: request_cache(d)["memory_size_in_bytes"],
                    0,
                )
            ],
        )
        call(
            "segments-before",
            depends_on=["maintenance.seed-count"],
            assertions=[("multiple primary segments", lambda d: segments(d) >= 2, True)],
        )
        call(
            "block-writes",
            depends_on=["maintenance.seed-count"],
            body={"index": {"blocks": {"write": True}}},
            assertions=[("write block acknowledged", lambda d: d["acknowledged"], True)],
        )
        call(
            "block-readback",
            depends_on=["maintenance.block-writes"],
            assertions=[
                (
                    "write block read back",
                    lambda d: d[index]["settings"]["index"]["blocks"]["write"],
                    "true",
                )
            ],
        )
        call(
            "forcemerge",
            depends_on=["maintenance.segments-before", "maintenance.block-readback"],
            assertions=[("merge has no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call(
            "refresh",
            depends_on=["maintenance.forcemerge"],
            assertions=[("refresh has no failed shards", lambda d: d["_shards"]["failed"], 0)],
        )
        call(
            "segments-after",
            depends_on=["maintenance.refresh"],
            verifies=["maintenance.forcemerge"],
            semantic=True,
            assertions=[("one primary segment after merge", segments, 1)],
        )
        call(
            "preserved-count",
            depends_on=["maintenance.forcemerge"],
            verifies=["maintenance.forcemerge"],
            semantic=True,
            assertions=[("all 90 documents preserved", lambda d: d["count"], 90)],
        )
        call(
            "recovery",
            depends_on=["maintenance.create"],
            semantic=True,
            assertions=[
                (
                    "primary recovery DONE",
                    lambda d: any(
                        s["primary"] and s["stage"] == "DONE" for s in d[index]["shards"]
                    ),
                    True,
                )
            ],
        )
        call(
            "active-recovery",
            depends_on=["maintenance.recovery"],
            semantic=True,
            assertions=[
                ("no active recoveries", lambda d: sum(len(v["shards"]) for v in d.values()), 0)
            ],
        )
        call(
            "shard-stores",
            depends_on=["maintenance.create"],
            semantic=True,
            assertions=[
                (
                    "primary store present",
                    lambda d: any(
                        s["allocation"] == "primary"
                        for s in d["indices"][index]["shards"]["0"]["stores"]
                    ),
                    True,
                )
            ],
        )
        if not catalog.version.startswith("6."):
            call(
                "disk-usage",
                depends_on=["maintenance.forcemerge"],
                semantic=True,
                assertions=[
                    ("no failed analysis shards", lambda d: d["_shards"]["failed"], 0),
                    (
                        "measured nonempty fields",
                        lambda d: d[index]["all_fields"]["total_in_bytes"] > 0,
                        True,
                    ),
                    ("n field included", lambda d: "n" in d[index]["fields"], True),
                ],
            )
    finally:
        call("cleanup")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument(
        "--families",
        nargs="+",
        choices=[
            "bulk",
            "tasks",
            "snapshot",
            "reopen",
            "maintenance",
            "metadata",
            "query",
            "template",
            "transform",
            "document",
            "cluster",
            "synonym",
            "resize",
            "resize-split",
            "cat",
            "stream",
            "stream-options",
            "module",
            "module-config",
            "repository",
            "feature",
            "managed-reindex",
            "topology",
            "topology-dangling",
            "wire",
            "legacy-document",
            "legacy-metadata",
        ],
        default=["bulk", "tasks", "snapshot", "reopen"],
    )
    args = parser.parse_args()
    inventory = json.loads(Path(args.inventory).read_text())
    version = inventory["release"]
    catalog = Catalog(version, inventory)
    errors = catalog.validate()
    if errors:
        raise SystemExit("\n".join(errors))
    provenance = {
        "source_commit": inventory["source_commit"],
        "scenario_plan": catalog.manifest(),
        "selected_families": args.families,
        "recipe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with Session(
        args.output,
        base_url=os.environ["ES_URL"],
        release=version,
        run_id=args.run_id,
        provenance=provenance,
    ) as run:
        if "bulk" in args.families:
            bulk_family(run, catalog, args.prefix)
        if "tasks" in args.families:
            for operation in ["reindex", "update", "delete"]:
                task_family(run, catalog, args.prefix, operation)
        if "snapshot" in args.families:
            snapshot_family(run, catalog, args.prefix)
        if "reopen" in args.families:
            reopen_family(run, catalog, args.prefix)
        if "maintenance" in args.families:
            maintenance_family(run, catalog, args.prefix)
        if "metadata" in args.families:
            metadata_family(run, catalog, args.prefix)
        if "query" in args.families:
            query_family(run, catalog, args.prefix)
        if "template" in args.families:
            template_family(run, catalog, args.prefix)
        if "transform" in args.families:
            transform_family(run, catalog, args.prefix)
        if "document" in args.families:
            document_family(run, catalog, args.prefix)
        if "cluster" in args.families:
            cluster_family(run, catalog, args.prefix)
        if "synonym" in args.families:
            synonym_family(run, catalog, args.prefix)
        if "resize" in args.families:
            resize_family(run, catalog, args.prefix)
        elif "resize-split" in args.families:
            resize_family(run, catalog, args.prefix, operations=["split"])
        if "cat" in args.families:
            cat_family(run, catalog, args.prefix)
        if "stream" in args.families:
            stream_family(run, catalog, args.prefix)
        elif "stream-options" in args.families:
            stream_family(run, catalog, args.prefix, focused=True)
        if "module" in args.families:
            module_family(run, catalog, args.prefix)
        elif "module-config" in args.families:
            module_family(run, catalog, args.prefix, focused=True)
        if "repository" in args.families:
            repository_family(run, catalog, args.prefix)
        if "feature" in args.families:
            feature_family(run, catalog, args.prefix)
        if "managed-reindex" in args.families:
            managed_reindex_family(run, catalog, args.prefix)
        if "topology" in args.families or "topology-dangling" in args.families:
            topology_family(
                run, catalog, args.prefix, dangling_only="topology-dangling" in args.families
            )
        if "wire" in args.families:
            wire_family(run, catalog, args.prefix)
        if "legacy-document" in args.families:
            legacy_document_family(run, catalog, args.prefix)
        if "legacy-metadata" in args.families:
            legacy_metadata_family(run, catalog, args.prefix)


if __name__ == "__main__":
    main()
