"""Append a conservative task-owned disk checkpoint; never prune Docker resources."""

import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from guarded_pull import free_bytes

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 30_000_000_000
WORKING = 24_000_000_000
BASE = (
    "weslyg/ansible-infra@sha256:86781ccdc5038239faefcd64bee767206ac74b056b86bb6e889f8a2a87403969"
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=30)


def tree_bytes(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def checkpoint():
    references = {BASE}
    for path in (ROOT / "docs/research/runs").glob("*/*/lab.json"):
        state = json.loads(path.read_text())
        references.add(state["image"])
    images = {}
    for reference in sorted(references):
        result = subprocess.run(
            ["docker", "image", "inspect", reference], capture_output=True, text=True, timeout=30
        )
        if result.returncode:
            if "No such image" in result.stderr:
                continue
            raise RuntimeError("Cannot account for task image: " + result.stderr)
        info = json.loads(result.stdout)[0]
        images[info["Id"]] = {"reference": reference, "bytes": info["Size"]}
    identifiers = docker("ps", "-aq", "--filter", "label=io.es-cli.research").split()
    containers = []
    for identifier in identifiers:
        info = json.loads(docker("container", "inspect", "--size", identifier))[0]
        logging = info["HostConfig"]["LogConfig"]
        # Lab policy bounds json-file logs to two files of five MB.
        if logging["Type"] not in {"json-file", "local"} or logging["Config"] != {
            "max-file": "2",
            "max-size": "5m",
        }:
            raise RuntimeError("Unexpected owned-container log policy; disk budget unresolved")
        containers.append(
            {
                "id": identifier,
                "name": info["Name"],
                "writable_bytes": info["SizeRw"],
                "reserved_log_bytes": 20_971_520,
            }
        )
    source = tree_bytes(ROOT)
    temporary = tree_bytes(Path("/tmp/es-cli-research-http"))
    accounted = (
        sum(i["bytes"] for i in images.values())
        + source
        + temporary
        + sum(c["writable_bytes"] + c["reserved_log_bytes"] for c in containers)
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    record = {
        "schema_version": 1,
        "at": stamp,
        "task_limit_bytes": LIMIT,
        "working_limit_bytes": WORKING,
        "accounted_bytes": accounted,
        "images": list(images.values()),
        "containers": containers,
        "repository_bytes_including_git_cache_report": source,
        "temporary_http_cache_bytes": temporary,
        "host_free_bytes": free_bytes(),
        "within_working_budget": accounted < WORKING,
        "limitations": "Logical image sizes (shared layers overcounted), source/cache and bounded log reserve. Not a physical VHDX peak measurement. Tmpfs is RAM.",
        "foreign_resources": "not mutated",
    }
    target = ROOT / "docs/research/disk-checkpoints" / (stamp + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    if accounted >= WORKING:
        raise RuntimeError("Working budget exceeded; no further research mutations allowed")
    return record


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(checkpoint()))


if __name__ == "__main__":
    main()
