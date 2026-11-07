"""Compare error shapes on an owned exact main and a same-image reduced-detail node."""

import argparse
import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone

from anchor_lab import LABEL, ROOT, docker, owned, save, startup_settings, validate_state
from disk_checkpoint import checkpoint


def run(state_path):
    path, state = validate_state(state_path)
    if state["release"] not in {"8.19.24", "9.0.8", "9.5.6"} or state["status"] != "ready-development-anchor":
        raise ValueError("Only ready exact source-reviewed error-shape releases are admitted")
    version = state["release"]
    runner = state["runner_id"]
    owned(state, runner)
    primary = owned(state, state["node_id"])
    primary_env = primary["Config"]["Env"]
    if any(x.startswith("http.detailed_errors.enabled=") and x != "http.detailed_errors.enabled=true" for x in primary_env):
        raise ValueError("Primary does not use the admitted detailed error default")
    network = owned(state, state["network_id"], "network")["Name"]
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = path.parent / "error-shapes" / identifier
    out.mkdir(parents=True, exist_ok=False)
    before = checkpoint()
    save(out / "disk-before.json", before)
    reserve = 300_000_000
    save(out / "admission.json", {
        "existing_accounted_bytes": before["accounted_bytes"], "growth_reserve_bytes": reserve,
        "working_limit_bytes": 24_000_000_000, "task_limit_bytes": 30_000_000_000,
        "image_pull": False, "image": state["image"],
    })
    if before["accounted_bytes"] + reserve >= 24_000_000_000 or before["host_free_bytes"] < reserve:
        raise RuntimeError("Error shape fixture exceeds disk admission")
    plan = ROOT / f"docs/research/source-analysis/{version}/error-shape-source-plan.json"
    save(out / "producer.json", {
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "sources": {name: hashlib.sha256((ROOT / "tools/research" / name).read_bytes()).hexdigest()
                    for name in ["error_shape_lab.py", "error_shape_probe.py", "http_attempt.py", "supervise.py"]},
    })
    docker("exec", runner, "mkdir", "-p", "/workspace/tools/research")
    for name in ["error_shape_probe.py", "http_attempt.py", "supervise.py"]:
        docker("cp", str(ROOT / "tools/research" / name), runner + ":/workspace/tools/research/" + name)
    settings = startup_settings(version, state["lab_id"] + "-error-shapes")
    settings.update({"node.name": "es-cli-error-shapes", "http.detailed_errors.enabled": "false"})
    env = [part for key, value in settings.items() for part in ["-e", key + "=" + value]]
    node = docker(
        "exec", runner, "docker", "create", "--name", "es-cli-error-shapes-" + identifier.lower(),
        "--label", LABEL + "=" + state["lab_id"], "--network", network,
        "--network-alias", "es-cli-error-reduced", "--memory", "2g",
        "--log-driver", "local", "--log-opt", "max-size=5m", "--log-opt", "max-file=2",
        "--tmpfs", "/usr/share/elasticsearch/data:rw,uid=1000,gid=0,size=268435456",
        "--tmpfs", "/tmp/es-snapshots:rw,uid=1000,gid=0,size=134217728",
        *env, state["image"],
    ).stdout.strip()
    save(out / "node.json", {"id": node, "settings": settings, "image": state["image"]})
    remote = "/workspace/error-shapes/" + identifier
    config = {
        "output": remote, "release": version, "default_base": "http://es-cli-active:9200",
        "reduced_base": "http://es-cli-error-reduced:9200",
    }
    result = None
    copied = None
    try:
        sibling = owned(state, node)
        assert sibling["Image"] == primary["Image"], "Exact running image mismatch"
        save(out / "runtime-image.json", {"primary_image_id": primary["Image"], "sibling_image_id": sibling["Image"]})
        docker("start", node)
        result = subprocess.run([
            "docker", "exec", "-i", runner, "python3", "/workspace/tools/research/supervise.py",
            "--timeout", "240", "python3", "/workspace/tools/research/error_shape_probe.py",
        ], input=json.dumps(config), capture_output=True, text=True, timeout=260)
        (out / "console.log").write_text((result.stdout + result.stderr)[-16000:])
        print((result.stdout + result.stderr)[-16000:], flush=True)
    finally:
        evidence = out / "evidence"
        evidence.mkdir()
        copied = subprocess.run(
            ["docker", "cp", runner + ":" + remote + "/.", str(evidence)],
            capture_output=True, text=True, timeout=30,
        )
        save(out / "driver-outcome.json", {
            "exit_code": result.returncode if result else None,
            "evidence_copied": copied.returncode == 0,
        })
        passed = result is not None and result.returncode == 0 and copied.returncode == 0
        if passed:
            owned(state, node)
            docker("rm", "-f", node)
        save(out / "resources.json", {
            "sibling_removed": passed, "primary_retained": True,
            "on_failure": "Retain exact sibling and primary for inspection",
        })
        save(out / "disk-after.json", checkpoint())
    print(json.dumps({"error_shape_run": str(out), "passed": passed}), flush=True)
    if not passed:
        raise RuntimeError("Error shape proof incomplete; evidence and exact node retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    run(parser.parse_args().state)
