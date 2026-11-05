"""Filesystem repository verification/status/cleanup with real orphan removal."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("repository." + name, api, method, path, expected=expected, purpose=purpose)
        graph["repository." + name] = tuple("repository." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed", "bulk", "POST", "/{index}/_bulk?refresh=true", ("create",), purpose="fixture-setup"
    )
    case(
        "put",
        "snapshot.create_repository",
        "PUT",
        "/_snapshot/{repository}",
        purpose="fixture-setup",
    )
    for scope, path in [("all", "/_snapshot"), ("named", "/_snapshot/{repository}")]:
        case(
            "get." + scope, "snapshot.get_repository", "GET", path, ("put",), purpose="effect-check"
        )
    case(
        "verify", "snapshot.verify_repository", "POST", "/_snapshot/{repository}/_verify", ("put",)
    )
    case(
        "snapshot",
        "snapshot.create",
        "PUT",
        "/_snapshot/{repository}/one?wait_for_completion=true",
        ("seed", "verify"),
        purpose="fixture-setup",
    )
    case(
        "status.named",
        "snapshot.status",
        "GET",
        "/_snapshot/{repository}/one/_status",
        ("snapshot",),
    )
    for name, path in [
        ("all-active", "/_snapshot/_status"),
        ("repository-active", "/_snapshot/{repository}/_status"),
    ]:
        case("status." + name, "snapshot.status", "GET", path, ("snapshot",))
    case(
        "orphan-precondition",
        "snapshot.get_repository",
        "GET",
        "/_snapshot/{repository}",
        ("snapshot",),
        purpose="fixture-precondition",
    )
    case(
        "cleanup",
        "snapshot.cleanup_repository",
        "POST",
        "/_snapshot/{repository}/_cleanup",
        ("orphan-precondition",),
    )
    case(
        "orphan-removed",
        "snapshot.get_repository",
        "GET",
        "/_snapshot/{repository}",
        ("cleanup",),
        purpose="effect-check",
    )
    case(
        "snapshot-preserved",
        "snapshot.status",
        "GET",
        "/_snapshot/{repository}/one/_status",
        ("cleanup",),
        purpose="effect-check",
    )
    case(
        "restore",
        "snapshot.restore",
        "POST",
        "/_snapshot/{repository}/one/_restore?wait_for_completion=true",
        ("snapshot-preserved",),
    )
    case("restored-count", "count", "GET", "/{target}/_count", ("restore",), purpose="effect-check")
    case(
        "restored-document", "get", "GET", "/{target}/_doc/3", ("restore",), purpose="effect-check"
    )
    for name, api, path in [
        ("snapshot", "snapshot.delete", "/_snapshot/{repository}/one"),
        ("repository", "snapshot.delete_repository", "/_snapshot/{repository}"),
        ("source", "indices.delete", "/{index}"),
        ("target", "indices.delete", "/{target}"),
    ]:
        case("cleanup-" + name, api, "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-repository",
        "repository": prefix + "-fs",
        "target": prefix + "-restored",
    }
    location = "/tmp/es-snapshots/" + values["repository"]
    orphan_dir = location + "/indices/research-orphan-" + run.run_id
    orphan = orphan_dir + "/garbage.bin"
    node = os.environ["ES_RESEARCH_NODE"]
    lab = os.environ["ES_RESEARCH_LAB"]
    info = json.loads(
        subprocess.check_output(["docker", "container", "inspect", node], timeout=10)
    )[0]
    if info["Config"].get("Labels", {}).get("io.es-cli.research") != lab:
        raise RuntimeError("Refusing filesystem fixture outside the owned lab")
    assert Path(orphan).is_relative_to(Path("/tmp/es-snapshots") / values["repository"])
    fixture_file = run.output / "fs-garbage-fixture.json"
    fixture = {
        "kind": "explicit-filesystem-fixture-not-rest-api",
        "node_id": node,
        "repository_location": location,
        "orphan_path": orphan,
        "prepared": False,
    }

    def save_fixture():
        fixture_file.write_text(json.dumps(fixture, indent=2) + "\n")

    def command(*args, input=None, check=True):
        return subprocess.run(
            ["docker", "exec", "-i", node, *args],
            input=input,
            capture_output=True,
            timeout=15,
            check=check,
        )

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
        case = catalog.cases["repository." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["repository." + n for n in verifies],
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def orphan_present(_data):
        size = int(command("wc", "-c", orphan).stdout.decode().split()[0])
        sha = command("sha256sum", orphan).stdout.decode().split()[0]
        fixture["verified_before"] = {"length": size, "sha256": sha}
        save_fixture()
        return size == 8192 and sha == fixture["sha256"]

    def orphan_absent(_data):
        result = command("test", "!", "-e", orphan, check=False)
        fixture["absence_test_exit_code"] = result.returncode
        save_fixture()
        return result.returncode == 0

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    save_fixture()
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {"n": {"type": "integer"}}},
        },
        ack,
    )
    try:
        parts = []
        for n in range(5):
            parts.extend([{"index": {"_id": str(n)}}, {"n": n}])
        call(
            "seed",
            ("\n".join(json.dumps(p) for p in parts) + "\n").encode(),
            [("seed no errors", lambda d: d["errors"], False)],
            ndjson=True,
        )
        call("put", {"type": "fs", "settings": {"location": location}}, ack)
        for scope in ["all", "named"]:
            call(
                "get." + scope,
                assertions=[
                    (
                        "actual filesystem repository",
                        lambda d: d[values["repository"]]["type"],
                        "fs",
                    ),
                    (
                        "location saved",
                        lambda d: d[values["repository"]]["settings"]["location"],
                        location,
                    ),
                ],
                verifies=["put"],
                semantic=True,
            )
        call("verify", assertions=[("repository usable by one node", lambda d: len(d["nodes"]), 1)])
        snapshot = call(
            "snapshot",
            {"indices": values["index"], "include_global_state": False},
            [("snapshot completed", lambda d: d["snapshot"]["state"], "SUCCESS")],
        )
        call(
            "status.named",
            assertions=[
                ("completed snapshot status", lambda d: d["snapshots"][0]["state"], "SUCCESS"),
                ("one shard done", lambda d: d["snapshots"][0]["shards_stats"]["done"], 1),
            ],
        )
        for name in ["all-active", "repository-active"]:
            call(
                "status." + name,
                assertions=[
                    ("completed snapshot is not an active operation", lambda d: d["snapshots"], [])
                ],
            )
        if snapshot.passed:
            payload = bytes(range(256)) * 32
            command("mkdir", "-p", orphan_dir)
            command("dd", "of=" + orphan, "bs=8192", "count=1", input=payload)
            fixture.update(
                prepared=True, length=len(payload), sha256=hashlib.sha256(payload).hexdigest()
            )
            save_fixture()
        call(
            "orphan-precondition",
            assertions=[("real orphan bytes exist on node", orphan_present, True)],
        )
        call(
            "cleanup",
            assertions=[
                ("actual bytes removed", lambda d: d["results"]["deleted_bytes"] >= 8192, True),
                ("at least one blob removed", lambda d: d["results"]["deleted_blobs"] >= 1, True),
            ],
            semantic=True,
        )
        call(
            "orphan-removed",
            assertions=[("orphan no longer exists on ES node", orphan_absent, True)],
            verifies=["cleanup"],
            semantic=True,
        )
        call(
            "snapshot-preserved",
            assertions=[
                ("referenced snapshot still valid", lambda d: d["snapshots"][0]["state"], "SUCCESS")
            ],
            verifies=["cleanup"],
            semantic=True,
        )
        call(
            "restore",
            {
                "indices": values["index"],
                "include_global_state": False,
                "rename_pattern": values["index"],
                "rename_replacement": values["target"],
                "index_settings": {"number_of_replicas": 0},
            },
            [("restore has no failed shards", lambda d: d["snapshot"]["shards"]["failed"], 0)],
        )
        call(
            "restored-count",
            assertions=[
                ("five snapshot documents preserved after cleanup", lambda d: d["count"], 5)
            ],
            verifies=["restore", "cleanup"],
            semantic=True,
        )
        call(
            "restored-document",
            assertions=[("original snapshot source restored", lambda d: d["_source"], {"n": 3})],
            verifies=["restore", "cleanup"],
            semantic=True,
        )
    finally:
        for name in ["snapshot", "repository", "source", "target"]:
            call("cleanup-" + name)
