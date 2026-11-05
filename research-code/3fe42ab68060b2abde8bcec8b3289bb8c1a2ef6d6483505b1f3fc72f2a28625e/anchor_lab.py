"""Own one development anchor lab; keep it between attempts, never overlap versions."""

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from disk_checkpoint import checkpoint
from scenario_catalog import Catalog

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools/research"
RUNS = ROOT / "docs/research/runs"
BASE = (
    "weslyg/ansible-infra@sha256:86781ccdc5038239faefcd64bee767206ac74b056b86bb6e889f8a2a87403969"
)
LABEL = "io.es-cli.research"


def command(*args, capture=True, timeout=90):
    return subprocess.run(
        list(args), cwd=ROOT, capture_output=capture, text=True, timeout=timeout, check=True
    )


def docker(*args, **kwargs):
    return command("docker", *args, **kwargs)


def load(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    temporary = Path(path).with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def inspect(identifier, kind="container"):
    return json.loads(docker(kind, "inspect", identifier).stdout)[0]


def owned(state, identifier, kind="container"):
    item = inspect(identifier, kind)
    labels = item.get("Labels", {}) if kind == "network" else item["Config"].get("Labels", {})
    if labels.get(LABEL) != state["lab_id"]:
        raise RuntimeError("Resource ownership mismatch; refusing mutation")
    return item


def validate_state(path):
    path = Path(path).resolve()
    if not path.is_relative_to(RUNS):
        raise ValueError("Lab state must be inside research runs directory")
    return path, load(path)


def cleanup(path, state):
    errors = []
    for key in ["node_id", "runner_id"]:
        identifier = state.get(key)
        if not identifier:
            continue
        try:
            owned(state, identifier)
            docker("rm", "-f", identifier)
            state[key] = None
        except subprocess.CalledProcessError as error:
            if "No such" not in (error.stderr or ""):
                errors.append(key + ": " + (error.stderr or str(error))[-1500:])
        except Exception as error:
            errors.append(key + ": " + str(error))
    if state.get("network_id"):
        try:
            owned(state, state["network_id"], "network")
            docker("network", "rm", state["network_id"])
            state["network_id"] = None
        except Exception as error:
            errors.append("network: " + str(error))
    if not errors and not state.get("image_preexisting") and state.get("image_pulled"):
        result = subprocess.run(
            ["docker", "image", "rm", state["image"]], capture_output=True, text=True, timeout=90
        )
        if result.returncode:
            errors.append("image retained: " + result.stderr[-1500:])
        else:
            state["image_pulled"] = False
    state["status"] = "cleaned" if not errors else "cleanup-incomplete"
    state["cleanup_errors"] = errors
    save(path, state)
    return errors


def start(version, development):
    folder = ROOT / "docs/research/versions" / version
    inventory = load(folder / "inventory.json")
    catalog = Catalog(version, inventory)
    plan = catalog.manifest()
    if plan["definition_errors"]:
        raise ValueError("\n".join(plan["definition_errors"]))
    if not development and not plan["ready_for_full_matrix"]:
        raise ValueError("Full matrix gate is not ready; development anchor must be explicit")
    existing = docker("ps", "-aq", "--filter", "label=" + LABEL).stdout.split()
    if existing:
        raise RuntimeError(
            "A task-owned lab already exists; reuse or stop it before another version"
        )
    lab_id = (
        "deep-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    )
    out = RUNS / version / lab_id
    out.mkdir(parents=True, exist_ok=False)
    path = out / "lab.json"
    baseline = load(folder / "run-manifest.json")
    state = {
        "schema_version": 2,
        "lab_id": lab_id,
        "release": version,
        "source_commit": inventory["source_commit"],
        "image": baseline["image"],
        "base": BASE,
        "status": "admission",
        "mode": "development-anchor",
        "runner_id": None,
        "node_id": None,
        "network_id": None,
        "image_preexisting": False,
        "image_pulled": False,
    }
    save(path, state)
    save(out / "initial-scenario-plan.json", plan)
    try:
        state["image_preexisting"] = (
            subprocess.run(
                ["docker", "image", "inspect", state["image"]], capture_output=True
            ).returncode
            == 0
        )
        manifest = json.loads(docker("manifest", "inspect", "--verbose", state["image"]).stdout)
        selected = manifest[0] if isinstance(manifest, list) else manifest
        compressed = sum(
            layer["size"] for layer in json.loads(base64.b64decode(selected["Raw"]))["layers"]
        )
        base_size = inspect(BASE, "image")["Size"]
        owned_files = sum(
            file.stat().st_size
            for root in [ROOT, Path("/tmp/es-cli-research-http")]
            for file in root.rglob("*")
            if file.is_file()
        )
        command(
            sys.executable,
            str(TOOLS / "guarded_pull.py"),
            state["image"],
            "--compressed-bytes",
            str(compressed),
            "--existing-bytes",
            str(base_size + owned_files),
            "--output",
            str(out / "image-admission.json"),
            capture=False,
            timeout=600,
        )
        state["image_pulled"] = True
        save(path, state)
        network = "es-cli-" + lab_id.lower()
        state["network_id"] = docker(
            "network", "create", "--internal", "--label", LABEL + "=" + lab_id, network
        ).stdout.strip()
        save(path, state)
        runner = "es-cli-runner-" + lab_id.lower()
        state["runner_id"] = docker(
            "create",
            "--name",
            runner,
            "--label",
            LABEL + "=" + lab_id,
            "--network",
            network,
            "--memory",
            "1g",
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=5m",
            "--log-opt",
            "max-file=2",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "--entrypoint",
            "/bin/sh",
            BASE,
            "-c",
            "sleep infinity",
        ).stdout.strip()
        save(path, state)
        docker("start", state["runner_id"])
        settings = {
            "node.name": "es-cli-anchor",
            "cluster.name": lab_id,
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
            "path.repo": "/tmp/es-snapshots",
            "ES_JAVA_OPTS": "-Xms512m -Xmx512m",
        }
        if not version.startswith("6."):
            settings["ingest.geoip.downloader.enabled"] = "false"
        env = [part for key, value in settings.items() for part in ["-e", key + "=" + value]]
        state["node_id"] = docker(
            "exec",
            state["runner_id"],
            "docker",
            "create",
            "--name",
            "es-cli-node-" + lab_id.lower(),
            "--label",
            LABEL + "=" + lab_id,
            "--network",
            network,
            "--network-alias",
            "es-cli-active",
            "--memory",
            "2g",
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=5m",
            "--log-opt",
            "max-file=2",
            "--tmpfs",
            "/usr/share/elasticsearch/data:rw,uid=1000,gid=0,size=268435456",
            "--tmpfs",
            "/tmp/es-snapshots:rw,uid=1000,gid=0,size=134217728",
            *env,
            state["image"],
        ).stdout.strip()
        save(path, state)
        docker("exec", state["runner_id"], "docker", "start", state["node_id"])
        readiness = """
import json,time,urllib.request
for attempt in range(90):
    try:
        with urllib.request.urlopen('http://es-cli-active:9200',timeout=2) as response:
            data=json.loads(response.read(100001))
        if data['version']['number'] != VERSION:
            raise SystemExit('Unexpected server version')
        print(json.dumps(data),flush=True)
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('Readiness deadline exceeded')
""".replace("VERSION", repr(version))
        result = docker("exec", state["runner_id"], "python3", "-c", readiness, timeout=200)
        save(out / "server-identity.json", json.loads(result.stdout))
        state["status"] = "ready-development-anchor"
        save(path, state)
        print(
            json.dumps({"lab_state": str(path), "release": version, "status": state["status"]}),
            flush=True,
        )
    except BaseException as error:
        state["startup_error"] = type(error).__name__ + ": " + str(error)[:2000]
        if state.get("node_id"):
            log = subprocess.run(
                ["docker", "logs", "--tail", "80", state["node_id"]],
                capture_output=True,
                text=True,
                timeout=30,
            )
            (out / "startup-node.log").write_text((log.stdout + log.stderr)[-16000:])
        cleanup(path, state)
        raise


def run_attempt(path, families=None):
    path, state = validate_state(path)
    if state["status"] != "ready-development-anchor":
        raise ValueError("Lab is not ready")
    owned(state, state["runner_id"])
    owned(state, state["node_id"])
    disk_before = checkpoint()
    token = uuid.uuid4().hex[:8]
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + token
    out = path.parent / "attempts" / identifier
    out.mkdir(parents=True, exist_ok=False)
    save(out / "disk-before.json", disk_before)
    version = state["release"]
    inventory = ROOT / "docs/research/versions" / version / "inventory.json"
    plan = Catalog(version, load(inventory)).manifest()
    if plan["definition_errors"]:
        raise ValueError("Scenario source validation failed before execution")
    save(out / "scenario-plan.json", plan)
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in TOOLS.iterdir()
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    save(
        out / "execution-provenance.json",
        {
            "schema_version": 2,
            "lab_id": state["lab_id"],
            "attempt_id": identifier,
            "image": state["image"],
            "base": state["base"],
            "source_commit": state["source_commit"],
            "tool_sha256": hashes,
            "git_sha": command("git", "rev-parse", "HEAD").stdout.strip(),
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "mode": "development-anchor-not-full-matrix",
            "selected_families": families or ["bulk", "tasks", "snapshot", "reopen"],
        },
    )
    runner = state["runner_id"]
    docker("exec", runner, "mkdir", "-p", "/workspace/tools", "/workspace/catalog")
    docker(
        "exec",
        runner,
        "python3",
        "-c",
        "from pathlib import Path;import shutil;p=Path('/workspace/tools/research');"
        "assert p.resolve()==p;shutil.rmtree(p) if p.exists() else None;p.mkdir(parents=True)",
    )
    docker("cp", str(TOOLS) + "/.", runner + ":/workspace/tools/research")
    docker(
        "exec",
        runner,
        "python3",
        "-c",
        "from pathlib import Path;import shutil;p=Path('/workspace/tools/research/__pycache__');"
        "shutil.rmtree(p) if p.exists() else None",
    )
    actual = docker(
        "exec",
        runner,
        "python3",
        "-c",
        "import hashlib,json;from pathlib import Path;root=Path('/workspace/tools/research');"
        "print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file() and p.suffix in {'.py','.json'}}))",
    )
    actual_hashes = json.loads(actual.stdout)
    save(out / "runner-code-sha256.json", actual_hashes)
    if actual_hashes != hashes:
        raise RuntimeError(
            "Copied runner code differs from frozen source snapshot; no HTTP executed"
        )
    docker("cp", str(inventory), runner + ":/workspace/catalog/inventory.json")
    remote = "/workspace/evidence/" + identifier
    execution = None
    try:
        arguments = ["--families", *families] if families else []
        execution = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                "ES_URL=http://es-cli-active:9200",
                "-e",
                "ES_RESEARCH_NODE=" + state["node_id"],
                "-e",
                "ES_RESEARCH_LAB=" + state["lab_id"],
                runner,
                "python3",
                "/workspace/tools/research/supervise.py",
                "--timeout",
                "870",
                "python3",
                "/workspace/tools/research/deep_cases.py",
                "--inventory",
                "/workspace/catalog/inventory.json",
                "--output",
                remote,
                "--run-id",
                identifier,
                "--prefix",
                "es-cli-v2-" + token,
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        (out / "console.log").write_text((execution.stdout + execution.stderr)[-16000:])
        print((execution.stdout + execution.stderr)[-16000:], flush=True)
    finally:
        copy = subprocess.run(
            ["docker", "cp", runner + ":" + remote + "/.", str(out)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        status = {
            "exit_code": execution.returncode if execution else None,
            "evidence_copied": copy.returncode == 0,
            "copy_error": copy.stderr[-2000:] if copy.returncode else None,
        }
        save(out / "driver-outcome.json", status)
        save(out / "disk-after.json", checkpoint())
        print(json.dumps({"attempt": str(out), **status}), flush=True)
    if execution is None or execution.returncode:
        raise SystemExit(
            "Recipe infrastructure error; inspect preserved attempt, lab retained for correction"
        )


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    starter = commands.add_parser("start")
    starter.add_argument("version", choices=["9.5.6", "6.0.0", "6.0.1"])
    starter.add_argument("--development-anchor", action="store_true")
    for name in ["run", "stop"]:
        sub = commands.add_parser(name)
        sub.add_argument("state")
        if name == "run":
            sub.add_argument(
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
                ],
            )
    args = parser.parse_args()
    if args.command == "start":
        start(args.version, args.development_anchor)
    elif args.command == "run":
        run_attempt(args.state, args.families)
    else:
        path, state = validate_state(args.state)
        errors = cleanup(path, state)
        print(json.dumps({"status": state["status"], "errors": errors}))
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
