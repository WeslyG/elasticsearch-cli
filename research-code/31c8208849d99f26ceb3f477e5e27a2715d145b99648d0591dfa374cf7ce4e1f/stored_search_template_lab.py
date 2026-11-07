"""Run the exact stored-template lifecycle on an existing owned exact node."""

import argparse
import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone

from anchor_lab import ROOT, docker, owned, save, validate_state
from disk_checkpoint import checkpoint


def run(state_path):
    path, state = validate_state(state_path)
    if (
        state["release"]
        not in {
            "6.0.0",
            "6.0.1",
            "6.1.4",
            "6.2.4",
            "6.3.2",
            "6.4.3",
            "6.5.4",
            "6.6.2",
            "6.7.2",
            "6.8.23",
            "7.0.1",
            "7.1.1",
            "7.2.1",
            "7.3.2",
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
            "7.17.29",
            "8.0.1",
            "8.1.3",
            "9.5.6",
        }
        or state["status"] != "ready-development-anchor"
    ):
        raise ValueError("Only ready exact source-reviewed stored-template releases are admitted")
    version = state["release"]
    runner = state["runner_id"]
    owned(state, runner)
    owned(state, state["node_id"])
    names = [
        "stored_search_template_probe.py",
        "error_shape_probe.py",
        "http_attempt.py",
        "supervise.py",
    ]
    hashes = {
        name: hashlib.sha256((ROOT / "tools/research" / name).read_bytes()).hexdigest()
        for name in names + ["stored_search_template_lab.py"]
    }
    source_plan = (
        ROOT / f"docs/research/source-analysis/{version}/stored-search-template-source-plan.json"
    )
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name, digest in hashes.items():
        committed = subprocess.check_output(
            ["git", "show", f"{git_head}:tools/research/{name}"], cwd=ROOT
        )
        if hashlib.sha256(committed).hexdigest() != digest:
            raise ValueError(f"Commit exact producer source before HTTP: {name}")
    plan_bytes = source_plan.read_bytes()
    if (
        subprocess.check_output(
            ["git", "show", f"{git_head}:{source_plan.relative_to(ROOT)}"], cwd=ROOT
        )
        != plan_bytes
    ):
        raise ValueError("Commit the exact source plan before HTTP")
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = path.parent / "stored-search-templates" / identifier
    out.mkdir(parents=True, exist_ok=False)
    before = checkpoint()
    save(out / "disk-before.json", before)
    reserve = 32_000_000
    save(
        out / "admission.json",
        {
            "existing_accounted_bytes": before["accounted_bytes"],
            "growth_reserve_bytes": reserve,
            "working_limit_bytes": 24_000_000_000,
            "task_limit_bytes": 30_000_000_000,
            "image_pull": False,
            "image": state["image"],
        },
    )
    if before["accounted_bytes"] + reserve >= 24_000_000_000 or before["host_free_bytes"] < reserve:
        raise RuntimeError("Stored-template fixture exceeds disk admission")
    (out / "source-plan.json").write_bytes(plan_bytes)
    save(
        out / "producer.json",
        {
            "git_head": git_head,
            "sources": hashes,
            "source_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        },
    )
    docker("exec", runner, "mkdir", "-p", "/workspace/tools/research")
    for name in names:
        docker(
            "cp", str(ROOT / "tools/research" / name), runner + ":/workspace/tools/research/" + name
        )
    observed = docker(
        "exec",
        runner,
        "python3",
        "-c",
        "import json,hashlib;from pathlib import Path;p=Path('/workspace/tools/research');"
        "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in "
        + repr(names)
        + "}))",
    )
    if json.loads(observed.stdout) != {name: hashes[name] for name in names}:
        raise RuntimeError("Worker producer bytes differ")
    remote = "/workspace/stored-search-templates/" + identifier
    config = {
        "release": state["release"],
        "base": "http://es-cli-active:9200",
        "index": "es-cli-template-index-" + identifier.lower(),
        "script": "es-cli-template-script-" + identifier.lower(),
        "output": remote,
    }
    config["wire_profile"] = json.loads(source_plan.read_bytes()).get("wire_profile", {})
    save(out / "fixture.json", config)
    result = None
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
                "/workspace/tools/research/stored_search_template_probe.py",
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
            ["docker", "cp", runner + ":" + remote + "/.", str(evidence)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        passed = result is not None and result.returncode == 0 and copied.returncode == 0
        save(
            out / "driver-outcome.json",
            {
                "exit_code": result.returncode if result else None,
                "evidence_copied": copied.returncode == 0,
            },
        )
        save(
            out / "resources.json",
            {
                "primary_retained": True,
                "owned_index_cleanup_asserted": passed,
                "owned_script_cleanup_asserted": passed,
                "index": config["index"],
                "script": config["script"],
                "on_failure": "Retain owned script, corpus and main for investigation",
            },
        )
        save(out / "disk-after.json", checkpoint())
    print(json.dumps({"stored_search_template_run": str(out), "passed": passed}), flush=True)
    if not passed:
        raise RuntimeError("Stored-template proof incomplete; exact lab and raw attempt retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    run(parser.parse_args().state)
