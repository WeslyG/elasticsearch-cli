"""Live anchor recipes. Plain Python functions, explicit declared cases, no SDK."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from alias_guard_family import execute as alias_guard_family
from cat_family import execute as cat_family
from cluster_family import execute as cluster_family
from compat8_family import execute as compat8_family
from composable_template_family import execute as composable_template_family
from core79_family import execute as core79_family
from document_family import execute as document_family
from evidence_runner import Session
from feature_family import execute as feature_family
from feature_gate_family import execute as feature_gates_family
from ingest_state_family import execute as ingest_state_family
from legacy_document_family import execute as legacy_document_family
from legacy_index_family import execute as legacy_index_family
from legacy_metadata_family import execute as legacy_metadata_family
from legacy_parameter_family import execute as legacy_parameter_family
from legacy_query_family import execute as legacy_query_family
from legacy_release_selection import (
    CANCEL_RESPONSE_WITHOUT_CANCELLED_RELEASES,
    CANCEL_WITHOUT_WAIT_RELEASES,
    EARLY_SEVEN_PILOTS,
    FLAT_TASK_LIST_RELEASES,
    RETHROTTLE_NEGATIVE_RELEASES,
    SNAPSHOT_CLONE_RELEASES,
    SYNCHRONOUS_MERGE_RELEASES,
)
from legacy_route_family import execute as legacy_route_family
from legacy_type_family import execute as legacy_type_family
from managed_reindex_family import execute as managed_reindex_family
from metadata_family import execute as metadata_family
from migration_state_family import execute as migration_state_family
from module_family import execute as module_family
from painless_context_family import execute as painless_context_family
from painless_execute_family import execute as painless_execute_family
from parameter_state_family import execute as parameter_state_family
from pit_empty_family import execute as pit_empty_family
from query_family import execute as query_family
from rank_eval_family import execute as rank_eval_family
from reload_analyzers_family import execute as reload_analyzers_family
from repository_family import execute as repository_family
from resize_family import execute as resize_family
from route_variant_family import execute as route_variant_family
from scenario_catalog import Catalog, validate_family_selection
from script_info_family import execute as script_info_family
from secure_reload_family import execute as secure_reload_family
from stream_family import execute as stream_family
from synonym_family import execute as synonym_family
from system_feature_family import execute as system_feature_family
from system_wire_family import execute as system_wire_family
from task_limit_family import execute as task_limit_family
from template_family import execute as template_family
from topology_family import execute as topology_family
from transform_family import execute as transform_family
from type_transition_family import execute as type_transition_family
from voting_state_family import execute as voting_state_family
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
    legacy_cancel = version in CANCEL_WITHOUT_WAIT_RELEASES
    identity_only = version in CANCEL_RESPONSE_WITHOUT_CANCELLED_RELEASES
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
        if legacy_cancel and operation == "reindex":
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

        if legacy_cancel and operation == "reindex":
            call(
                "list-group-probe",
                depends_on=[stem + ".get-running"],
                semantic=version in FLAT_TASK_LIST_RELEASES,
                assertions=[
                    (
                        "flat group_by response contains real running task"
                        if version in FLAT_TASK_LIST_RELEASES
                        else "legacy group_by choices enforced",
                        (
                            lambda data: (
                                isinstance(data.get("tasks"), list)
                                and "nodes" not in data
                                and any(
                                    str(task.get("node")) + ":" + str(task.get("id"))
                                    == values["task_id"]
                                    and task.get("cancellable") is True
                                    for task in data["tasks"]
                                )
                            )
                        )
                        if version in FLAT_TASK_LIST_RELEASES
                        else (lambda data: "group_by" in data["error"]["reason"]),
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
        if version in RETHROTTLE_NEGATIVE_RELEASES:
            for suffix in ["missing", "garbage", "zero", "negative"]:
                call(
                    "rate-" + suffix,
                    depends_on=[stem + ".get-running"],
                    assertions=[
                        (
                            "native error identifies requests_per_second",
                            lambda d: "requests_per_second" in d["error"]["reason"],
                            True,
                        )
                    ],
                )
            call(
                "rate-unchanged",
                depends_on=[
                    stem + ".rate-" + suffix
                    for suffix in ["missing", "garbage", "zero", "negative"]
                ],
                semantic=True,
                assertions=[
                    (
                        "invalid rethrottles preserve original0.2 rate",
                        lambda d: d["task"]["status"]["requests_per_second"],
                        0.2,
                    )
                ],
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
                str(task.get("node")) + ":" + str(task.get("id")) == values["task_id"]
                and task.get("cancellable") is True
                and (identity_only or task.get("cancelled") is True)
                for node in data.get("nodes", {}).values()
                for task in node.get("tasks", {}).values()
            )

        call(
            "cancel",
            depends_on=[stem + ".submit"],
            semantic=not identity_only,
            assertions=[
                (
                    "requested task returned by cancellation"
                    if identity_only
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
                if identity_only
                else []
            ),
        )
        if identity_only:
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
            depends_on=[stem + (".refresh-remaining" if identity_only else ".completed")],
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
    snapshot_metadata = catalog.version.startswith("6.") or catalog.version in EARLY_SEVEN_PILOTS
    legacy = snapshot_metadata and catalog.version not in SNAPSHOT_CLONE_RELEASES
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
        if snapshot_metadata:
            for name in ["repo-get", "repo-get-all"]:
                call(
                    name,
                    depends_on=["snapshot.repository"],
                    assertions=[
                        (
                            "registered fs repository",
                            lambda d: d[values["repository"]]["type"],
                            "fs",
                        )
                    ],
                )
            call(
                "repo-verify",
                depends_on=["snapshot.repository"],
                assertions=[("one actual repository node", lambda d: len(d["nodes"]), 1)],
            )
            call(
                "source-get",
                depends_on=["snapshot.create"],
                verifies=["snapshot.create"],
                semantic=True,
                assertions=[
                    ("successful stored snapshot", lambda d: d["snapshots"][0]["state"], "SUCCESS"),
                    (
                        "exact stored index",
                        lambda d: d["snapshots"][0]["indices"],
                        [values["index"]],
                    ),
                ],
            )
            call(
                "source-status",
                depends_on=["snapshot.create"],
                assertions=[
                    ("snapshot stage complete", lambda d: d["snapshots"][0]["state"], "SUCCESS"),
                    ("one completed shard", lambda d: d["snapshots"][0]["shards_stats"]["done"], 1),
                ],
            )
            for name in ["repo-status", "global-status"]:
                call(
                    name,
                    depends_on=["snapshot.create"],
                    assertions=[
                        (
                            "completed snapshots absent from running list",
                            lambda d: d["snapshots"],
                            [],
                        )
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
    values = {"index": prefix + "-maintenance", "merge_task": "not-launched"}
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
        if catalog.version in SYNCHRONOUS_MERGE_RELEASES:
            call(
                "merge-parameter-probe",
                depends_on=["maintenance.segments-before", "maintenance.block-readback"],
                assertions=[
                    (
                        "wait_for_completion response identifies parameter",
                        lambda d: "wait_for_completion" in str(d["error"]),
                        True,
                    )
                ],
            )
        if catalog.version in {
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
        }:
            launched = call(
                "async-merge",
                depends_on=["maintenance.segments-before", "maintenance.block-readback"],
                assertions=[
                    (
                        "async merge returns task identity",
                        lambda d: isinstance(d["task"], str) and ":" in d["task"],
                        True,
                    )
                ],
            )
            values["merge_task"] = (launched.data or {}).get("task", "not-launched")
            call(
                "async-merge-wait",
                depends_on=["maintenance.async-merge"],
                assertions=[
                    ("async merge completed", lambda d: d["completed"], True),
                    (
                        "actual merge task action",
                        lambda d: d["task"]["action"],
                        "indices:admin/forcemerge",
                    ),
                    (
                        "async merge shards succeeded",
                        lambda d: d["response"]["_shards"]["failed"],
                        0,
                    ),
                ],
            )
            call(
                "async-merge-segments",
                depends_on=["maintenance.async-merge-wait"],
                verifies=["maintenance.async-merge"],
                semantic=True,
                assertions=[("async merge reduced actual segments to one", segments, 1)],
            )
            call(
                "async-merge-source",
                depends_on=["maintenance.async-merge-wait"],
                assertions=[
                    (
                        "same persisted task identity",
                        lambda d: (
                            str(d["_source"]["task"]["node"])
                            + ":"
                            + str(d["_source"]["task"]["id"])
                        ),
                        values["merge_task"],
                    ),
                    (
                        "stored shard result succeeded",
                        lambda d: d["_source"]["response"]["_shards"]["failed"],
                        0,
                    ),
                    ("native typeless response", lambda d: "_type" in d, False),
                ],
            )
        call(
            "forcemerge",
            depends_on=["maintenance.segments-before", "maintenance.block-readback"]
            + (
                ["maintenance.async-merge-segments"]
                if catalog.version
                in {
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
                }
                else []
            ),
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
        if catalog.version in {"7.15.2", "7.16.3"}:
            call(
                "disk-no-opt-in",
                depends_on=["maintenance.forcemerge"],
                assertions=[
                    (
                        "expensive analysis requires explicit opt-in",
                        lambda d: "run_expensive_tasks" in str(d["error"]),
                        True,
                    )
                ],
            )
        if catalog.version in {"7.15.2", "7.16.3"} or (
            not catalog.version.startswith("6.") and catalog.version not in EARLY_SEVEN_PILOTS
        ):
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
        if catalog.version in {
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
        }:
            call(
                "async-merge-result-delete",
                depends_on=["maintenance.async-merge-source"],
                assertions=[("owned async result deleted", lambda d: d["result"], "deleted")],
            )
            call(
                "async-merge-result-absent",
                depends_on=["maintenance.async-merge-result-delete"],
                verifies=["maintenance.async-merge-result-delete"],
                semantic=True,
                assertions=[("deleted task result absent", lambda d: d["found"], False)],
            )
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
            "legacy-query",
            "legacy-index",
            "compat8",
            "analyzer-reload",
            "pit-empty",
            "migration-state",
            "system-wire",
            "system-features",
            "route-variants",
            "type-transition",
            "secure-reload",
            "painless-execute",
            "painless-context",
            "task-limit",
            "ingest-state",
            "script-info",
            "feature-gates",
            "composable-template",
            "voting-state",
            "core79",
            "alias-guard",
            "rank-eval",
            "legacy-parameter",
            "legacy-route",
            "legacy-type",
            "parameter-state",
        ],
        default=["bulk", "tasks", "snapshot", "reopen"],
    )
    args = parser.parse_args()
    inventory = json.loads(Path(args.inventory).read_text())
    version = inventory["release"]
    try:
        validate_family_selection(version, args.families)
    except ValueError as error:
        raise SystemExit(str(error)) from error
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
        if "parameter-state" in args.families:
            parameter_state_family(run, catalog, args.prefix)
        # ES7 reset must precede other async families: its .tasks absence
        # precondition ensures that it only removes state created by this fixture.
        if version == "7.17.29" and "feature" in args.families:
            feature_family(run, catalog, args.prefix)
        # Early typed-global conflict fixtures require actual persisted task results.
        if version in EARLY_SEVEN_PILOTS and "tasks" in args.families:
            for operation in ["reindex", "update", "delete"]:
                task_family(run, catalog, args.prefix, operation)
        if "type-transition" in args.families:
            type_transition_family(run, catalog, args.prefix)
        if "secure-reload" in args.families:
            secure_reload_family(run, catalog, args.prefix)
        if "painless-execute" in args.families:
            painless_execute_family(run, catalog, args.prefix)
        if "painless-context" in args.families:
            painless_context_family(run, catalog, args.prefix)
        if "task-limit" in args.families:
            task_limit_family(run, catalog, args.prefix)
        if "ingest-state" in args.families:
            ingest_state_family(run, catalog, args.prefix)
        if "script-info" in args.families:
            script_info_family(run, catalog, args.prefix)
        if "feature-gates" in args.families:
            feature_gates_family(run, catalog, args.prefix)
        if "alias-guard" in args.families:
            alias_guard_family(run, catalog, args.prefix)
        if "core79" in args.families:
            core79_family(run, catalog, args.prefix)
        if "voting-state" in args.families:
            voting_state_family(run, catalog, args.prefix)
        if "composable-template" in args.families:
            composable_template_family(run, catalog, args.prefix)
        if "rank-eval" in args.families:
            rank_eval_family(run, catalog, args.prefix)
        if "legacy-parameter" in args.families:
            legacy_parameter_family(run, catalog, args.prefix)
        if "legacy-route" in args.families:
            legacy_route_family(run, catalog, args.prefix)
        if "legacy-type" in args.families:
            legacy_type_family(run, catalog, args.prefix)
        if "route-variants" in args.families:
            route_variant_family(run, catalog, args.prefix)
        if "system-wire" in args.families:
            system_wire_family(run, catalog, args.prefix)
        if "migration-state" in args.families:
            migration_state_family(run, catalog, args.prefix)
        if "pit-empty" in args.families:
            pit_empty_family(run, catalog, args.prefix)
        if "analyzer-reload" in args.families:
            reload_analyzers_family(run, catalog, args.prefix)
        if "compat8" in args.families:
            compat8_family(run, catalog, args.prefix)
        if "bulk" in args.families:
            bulk_family(run, catalog, args.prefix)
        if "tasks" in args.families and version not in EARLY_SEVEN_PILOTS:
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
        if "feature" in args.families and version != "7.17.29":
            feature_family(run, catalog, args.prefix)
        if "managed-reindex" in args.families:
            managed_reindex_family(run, catalog, args.prefix)
        if "topology" in args.families or "topology-dangling" in args.families:
            topology_family(
                run, catalog, args.prefix, dangling_only="topology-dangling" in args.families
            )
        if "wire" in args.families:
            wire_family(run, catalog, args.prefix)
        if "legacy-index" in args.families:
            legacy_index_family(run, catalog, args.prefix)
        if "legacy-document" in args.families:
            legacy_document_family(run, catalog, args.prefix)
        if "legacy-metadata" in args.families:
            legacy_metadata_family(run, catalog, args.prefix)
        if "legacy-query" in args.families:
            legacy_query_family(run, catalog, args.prefix)
        if "system-features" in args.families:
            system_feature_family(run, catalog, args.prefix)


if __name__ == "__main__":
    main()
