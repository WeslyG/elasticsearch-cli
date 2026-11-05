"""Live anchor recipes. Plain Python functions, explicit declared cases, no SDK."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from evidence_runner import Session
from scenario_catalog import Catalog


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

        def task_visible(data):
            return any(
                str(task["node"]) + ":" + str(task["id"]) == values["task_id"]
                for task in data["tasks"]
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
                task.get("cancelled") is True
                for node in data.get("nodes", {}).values()
                for task in node.get("tasks", {}).values()
            )

        call(
            "cancel",
            depends_on=[stem + ".submit"],
            semantic=True,
            assertions=[("cancelled task reported", cancelled, True)],
        )
        call(
            "completed",
            depends_on=[stem + ".cancel"],
            verifies=[stem + ".cancel"],
            semantic=True,
            assertions=[("cancelled task finished", lambda d: d["completed"], True)],
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
            depends_on=[stem + ".completed"],
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
            depends_on=["snapshot.clone-metadata"],
            assertions=[("source index deleted", lambda d: d["acknowledged"], True)],
        )
        call(
            "restore",
            body={"indices": values["index"], "include_global_state": False},
            depends_on=["snapshot.delete-source-index"],
            assertions=[
                ("restore has no failed shards", lambda d: d["snapshot"]["shards"]["failed"], 0)
            ],
        )
        call(
            "restored-document",
            depends_on=["snapshot.restore"],
            verifies=["snapshot.clone", "snapshot.restore"],
            semantic=True,
            assertions=[("original value restored from clone", lambda d: d["_source"]["n"], 42)],
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prefix", required=True)
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
        "recipe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with Session(
        args.output,
        base_url=os.environ["ES_URL"],
        release=version,
        run_id=args.run_id,
        provenance=provenance,
    ) as run:
        bulk_family(run, catalog, args.prefix)
        if not version.startswith("6."):
            for operation in ["reindex", "update", "delete"]:
                task_family(run, catalog, args.prefix, operation)
            snapshot_family(run, catalog, args.prefix)
        reopen_family(run, catalog, args.prefix)


if __name__ == "__main__":
    main()
