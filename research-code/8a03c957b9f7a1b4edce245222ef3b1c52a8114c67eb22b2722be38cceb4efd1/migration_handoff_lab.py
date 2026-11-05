"""Transfer a small real ES6 snapshot between sequential owned research labs."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from anchor_lab import ROOT, docker, owned, run_attempt, save, validate_state
from disk_checkpoint import checkpoint
from validate_attempt import validate

REMOTE = "/tmp/es-snapshots/es-cli-migration-handoff"
MAX_BYTES = 16_000_000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(folder):
    return {
        row["scenario_id"]: row
        for row in (
            json.loads(line) for line in (folder / "observations.jsonl").read_text().splitlines()
        )
    }


def body(observation):
    return observation["response"]["body"]["data"]


def validate_seed(folder):
    summary = validate(folder)
    assert summary["release"] == "6.0.1"
    assert summary["states"] == {"passed": 13}
    observed = rows(folder)
    metadata = json.loads((folder / "migration-handoff.json").read_text())
    assert re.fullmatch(r"[A-Za-z0-9_-]+:[0-9]+", metadata["task_id"])
    assert metadata["creation_version"] == 6000199
    assert body(observed["migration-state.task"])["completed"] is True
    assert body(observed["migration-state.task"])["response"]["created"] == 1
    assert body(observed["migration-state.stored"])["_source"]["completed"] is True
    settings = body(observed["migration-state.settings"])[".tasks"]["settings"]["index"]
    assert settings["version"]["created"] == "6000199"
    snapshot = body(observed["migration-state.snapshot-get"])["snapshots"][0]
    assert snapshot["state"] == "SUCCESS" and snapshot["version"] == "6.0.1"
    assert snapshot["indices"] == [".tasks"]
    return metadata, summary


def validate_restore(folder):
    summary = validate(folder)
    assert summary["release"] == "7.17.29"
    assert set(summary["states"]) == {"passed"}
    observed = rows(folder)
    before = body(observed["migration-state.settings-before"])
    assert before[".tasks"]["settings"]["index"]["version"]["created"] == "6000199"
    assert body(observed["migration-state.needed"])["migration_status"] == "MIGRATION_NEEDED"
    assert body(observed["migration-state.start"])["accepted"] is True
    assert body(observed["migration-state.completed"])["migration_status"] == "NO_MIGRATION_NEEDED"
    after = body(observed["migration-state.settings-after"])
    assert list(after) == [".tasks-reindexed-for-8"]
    assert (
        int(after[".tasks-reindexed-for-8"]["settings"]["index"]["version"]["created"]) // 1_000_000
        == 7
    )
    assert (
        ".tasks"
        in body(observed["migration-state.aliases-after"])[".tasks-reindexed-for-8"]["aliases"]
    )
    for name in ["task-before", "task-after"]:
        task = body(observed["migration-state." + name])
        assert task["completed"] is True and task["response"]["created"] == 1
        assert task["response"]["failures"] == []
    assert body(observed["migration-state.repeat"])["accepted"] is False
    assert observed["migration-state.absent"]["response"]["status"] == 404
    return summary


def local_files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Snapshot symlinks are forbidden")
        if path.is_file():
            name = str(path.relative_to(root))
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
                raise ValueError("Unexpected snapshot filename")
            result[name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    if not result or sum(item["bytes"] for item in result.values()) > MAX_BYTES:
        raise ValueError("Snapshot handoff must be nonempty and at most 16 MB")
    return result


def run(mode, state_path, handoff=None):
    path, state = validate_state(state_path)
    expected = "6.0.1" if mode == "seed" else "7.17.29"
    if state["status"] != "ready-development-anchor" or state["release"] != expected:
        raise ValueError("Wrong exact source/destination lab")
    owned(state, state["runner_id"])
    owned(state, state["node_id"])
    before = checkpoint()
    if (
        before["accounted_bytes"] + MAX_BYTES >= 24_000_000_000
        or before["host_free_bytes"] < MAX_BYTES
    ):
        raise ValueError("Snapshot handoff exceeds disk admission")

    if mode == "seed":
        attempt = run_attempt(path, ["migration-state"])
        metadata, summary = validate_seed(attempt)
        destination = path.parent / "snapshot-handoff"
        destination.mkdir(exist_ok=False)
        save(destination / "disk-before.json", before)
        # Source tmpfs has a hard 128 MiB bound; require <=16 MB before copying.
        size = int(docker("exec", state["node_id"], "du", "-sb", REMOTE).stdout.split()[0])
        if size > MAX_BYTES:
            raise ValueError("Source snapshot exceeds export budget")
        data = destination / "repository"
        data.mkdir()
        docker("cp", state["node_id"] + ":" + REMOTE + "/.", str(data))
        files = local_files(data)
        save(
            destination / "handoff.json",
            {
                "schema_version": 1,
                "kind": "actual-pre7-system-index-snapshot",
                "source_attempt": str(attempt.relative_to(ROOT)),
                "source_observations_sha256": summary["raw_observations_sha256"],
                "source_handoff_sha256": digest(attempt / "migration-handoff.json"),
                "source_image": state["image"],
                "source_release": state["release"],
                "driver_sha256": digest(Path(__file__)),
                "metadata": metadata,
                "files": files,
                "bytes": sum(item["bytes"] for item in files.values()),
                "scope": "Synthetic owned persisted task only; no external/user cluster data.",
            },
        )
        save(destination / "disk-after.json", checkpoint())
        print(json.dumps({"handoff": str(destination / "handoff.json"), "files": len(files)}))
        return

    manifest = Path(handoff).resolve()
    if not manifest.is_relative_to(ROOT / "docs/research/runs/6.0.1"):
        raise ValueError("Only owned recorded ES6 snapshots are accepted")
    transfer = json.loads(manifest.read_text())
    assert transfer["kind"] == "actual-pre7-system-index-snapshot"
    seed = ROOT / transfer["source_attempt"]
    metadata, summary = validate_seed(seed)
    assert transfer["source_observations_sha256"] == summary["raw_observations_sha256"]
    assert transfer["source_handoff_sha256"] == digest(seed / "migration-handoff.json")
    assert transfer["metadata"] == metadata
    data = manifest.parent / "repository"
    assert local_files(data) == transfer["files"]
    docker("exec", "--user", "1000:0", state["node_id"], "mkdir", "-p", REMOTE)
    docker("cp", str(data) + "/.", state["node_id"] + ":" + REMOTE)
    docker("exec", state["node_id"], "chown", "-R", "1000:0", REMOTE)
    checksums = docker(
        "exec", state["node_id"], "sha256sum", *[REMOTE + "/" + name for name in transfer["files"]]
    ).stdout
    actual = {
        line.split(None, 1)[1].strip(): line.split(None, 1)[0] for line in checksums.splitlines()
    }
    assert actual == {
        REMOTE + "/" + name: item["sha256"] for name, item in transfer["files"].items()
    }
    attempt = run_attempt(
        path,
        ["migration-state"],
        extra_env={"ES_MIGRATION_TASK_ID": metadata["task_id"]},
        fixture_context={
            "kind": "sequential-pre7-system-index-snapshot",
            "handoff": str(manifest.relative_to(ROOT)),
            "handoff_sha256": digest(manifest),
            "copied_files_sha256_verified": True,
        },
    )
    summary = validate_restore(attempt)
    save(
        attempt / "migration-validation.json",
        {
            "kind": "independently-validated-real-pre7-system-index-migration",
            "handoff": str(manifest.relative_to(ROOT)),
            "handoff_sha256": digest(manifest),
            "source_release": "6.0.1",
            "destination_release": "7.17.29",
            "summary": summary,
            "remaining": ["migration failure/restart", "other releases", "installed consumers"],
        },
    )
    print(json.dumps({"migration_validated": True, "attempt": str(attempt)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["seed", "restore"])
    parser.add_argument("state")
    parser.add_argument("--handoff")
    args = parser.parse_args()
    if args.mode == "restore" and not args.handoff:
        parser.error("restore requires --handoff")
    run(args.mode, args.state, args.handoff)


if __name__ == "__main__":
    main()
