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


def volume_usage(lab_ids):
    volumes = []
    names = docker("volume", "ls", "-q", "--filter", "label=io.es-cli.research").split()
    counter = (
        "import os,stat;total=0;"
        "\nfor root,dirs,files in os.walk('/meter',followlinks=False):"
        "\n for name in ['.',*files]:"
        "\n  try:s=os.stat(os.path.join(root,name),follow_symlinks=False)"
        "\n  except FileNotFoundError:continue"
        "\n  total+=max(s.st_size,s.st_blocks*512)"
        "\nprint(total)"
    )
    for name in names:
        info = json.loads(docker("volume", "inspect", name))[0]
        owner = (info.get("Labels") or {}).get("io.es-cli.research")
        if owner not in lab_ids:
            continue
        if not name.startswith("es-cli-"):
            raise RuntimeError("Unexpected name on a task-labelled volume")
        size = int(
            docker(
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--label",
                "io.es-cli.research=" + owner,
                "--log-driver=local",
                "--log-opt=max-size=5m",
                "--log-opt=max-file=2",
                "--mount",
                "type=volume,source=" + name + ",target=/meter,readonly,volume-nocopy",
                "--entrypoint=python3",
                BASE,
                "-c",
                counter,
            )
        )
        volumes.append(
            {
                "name": name,
                "owner": owner,
                "allocated_or_logical_bytes": size,
                "method": "read-only stat in pinned no-network helper",
            }
        )
    return volumes


def checkpoint():
    references = {BASE}
    lab_ids = set()
    for path in (ROOT / "docs/research/runs").glob("*/*/lab.json"):
        state = json.loads(path.read_text())
        references.add(state["image"])
        lab_ids.add(state["lab_id"])
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
    volumes = volume_usage(lab_ids)
    source = tree_bytes(ROOT)
    temporary = tree_bytes(Path("/tmp/es-cli-research-http"))
    accounted = (
        sum(i["bytes"] for i in images.values())
        + source
        + temporary
        + sum(c["writable_bytes"] + c["reserved_log_bytes"] for c in containers)
        + sum(v["allocated_or_logical_bytes"] for v in volumes)
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
        "volumes": volumes,
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
