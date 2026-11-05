"""Run bounded controlled faults inside the current owned ES8 research worker."""

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from anchor_lab import ROOT, docker, owned, save, validate_state
from disk_checkpoint import checkpoint


def run(state_path):
    path, state = validate_state(state_path)
    if state["status"] != "ready-development-anchor" or state["release"] != "8.19.24":
        raise ValueError("Fault recipes are prepared only for ready exact 8.19.24")
    runner = state["runner_id"]
    owned(state, runner)
    owned(state, state["node_id"])
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = path.parent / "faults" / identifier
    out.mkdir(parents=True, exist_ok=False)
    before = checkpoint()
    save(out / "disk-before.json", before)
    reserve = 128_000_000
    save(
        out / "admission.json",
        {
            "growth_reserve_bytes": reserve,
            "existing_accounted_bytes": before["accounted_bytes"],
            "working_limit_bytes": 24_000_000_000,
            "task_limit_bytes": 30_000_000_000,
            "image_pull": False,
        },
    )
    if before["accounted_bytes"] + reserve >= 24_000_000_000 or before["host_free_bytes"] < reserve:
        raise RuntimeError("Fault fixture exceeds disk admission")
    remote = "/workspace/faults/" + identifier
    docker("exec", runner, "mkdir", "-p", "/workspace/tools/research")
    hashes = {}
    for name in ["fault_probe.py", "evidence_runner.py", "http_attempt.py", "supervise.py"]:
        source = ROOT / "tools/research" / name
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        docker("cp", str(source), runner + ":/workspace/tools/research/" + name)
    actual = docker(
        "exec",
        runner,
        "python3",
        "-c",
        "import hashlib,json;from pathlib import Path;p=Path('/workspace/tools/research');"
        "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in "
        + repr(list(hashes))
        + "}))",
    )
    assert json.loads(actual.stdout) == hashes
    docker(
        "exec",
        runner,
        "python3",
        "-c",
        "from pathlib import Path;import shutil;p=Path('/workspace/tools/research/__pycache__');"
        "shutil.rmtree(p) if p.exists() else None",
    )
    save(
        out / "execution-provenance.json",
        {
            "schema_version": 1,
            "kind": "controlled-fault-transport-not-rest-coverage",
            "release": state["release"],
            "image": state["image"],
            "base": state["base"],
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "tool_sha256": {
                **hashes,
                "fault_lab.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            "actual_runner_hashes": json.loads(actual.stdout),
            "backend_primary_id": state["node_id"],
            "network": "proxy bound only to loopback in the existing owned runner; real ES on the internal lab network",
        },
    )
    config = {
        "output": remote + "/evidence",
        "base_url": "http://es-cli-active:9200",
        "release": state["release"],
        "run_id": identifier,
        "prefix": "es-cli-fault-" + identifier.rsplit("-", 1)[1],
    }
    result = None
    copied = None
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                runner,
                "python3",
                "/workspace/tools/research/supervise.py",
                "--timeout",
                "180",
                "python3",
                "/workspace/tools/research/fault_probe.py",
            ],
            input=json.dumps(config),
            capture_output=True,
            text=True,
            timeout=200,
        )
        (out / "console.log").write_text((result.stdout + result.stderr)[-16000:])
        print((result.stdout + result.stderr)[-16000:], flush=True)
    finally:
        evidence = out / "evidence"
        evidence.mkdir()
        copied = subprocess.run(
            ["docker", "cp", runner + ":" + config["output"] + "/.", str(evidence)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        outcome = {
            "exit_code": result.returncode if result else None,
            "evidence_copied": copied.returncode == 0,
        }
        save(out / "driver-outcome.json", outcome)
        if copied.returncode == 0:
            for name in ["setup", "fault-attempts", "resolution", "refused-attempt"]:
                if (evidence / name / "manifest.json").exists():
                    save(evidence / name / "driver-outcome.json", outcome)
        cleanup = docker(
            "exec",
            runner,
            "python3",
            "-c",
            "from pathlib import Path;import shutil;p=Path(" + repr(remote) + ");"
            "assert p.parent==Path('/workspace/faults');shutil.rmtree(p) if p.exists() else None",
        )
        save(
            out / "resources.json",
            {
                "worker_exited": result is not None,
                "private_workspace_removed": cleanup.returncode == 0,
                "owned_primary_retained": True,
            },
        )
        save(out / "disk-after.json", checkpoint())
        print(json.dumps({"fault_run": str(out), **outcome}), flush=True)
    if result is None or result.returncode or copied.returncode:
        raise RuntimeError("Fault probe infrastructure failed; evidence preserved and lab retained")
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    run(parser.parse_args().state)
