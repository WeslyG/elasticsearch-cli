"""Temporary persistent three-node fixture on the current pinned anchor image."""

import argparse
import base64
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone

from anchor_lab import (
    LABEL,
    ROOT,
    assert_committed_tools,
    docker,
    owned,
    run_attempt,
    save,
    startup_settings,
    validate_families,
    validate_state,
)
from disk_checkpoint import checkpoint
from early_voting_family import PREPARED_VERSIONS as EARLY_VOTING_RELEASES
from scenario_catalog import validate_family_selection
from voting_name_family import PREPARED_VERSIONS as NAME_VOTING_RELEASES


def run(state_path, *, dangling_only=False, voting_names_only=False):
    path, state = validate_state(state_path)
    if (
        state["release"]
        not in EARLY_VOTING_RELEASES | NAME_VOTING_RELEASES | {"9.5.6", "7.17.29", "8.19.24"}
        or state["status"] != "ready-development-anchor"
    ):
        raise ValueError("Topology development fixture requires a prepared pinned anchor")
    if voting_names_only and (dangling_only or state["release"] not in NAME_VOTING_RELEASES):
        raise ValueError("Duplicate-name fixture requires a source-prepared exact release")
    assert_committed_tools()
    selected = [
        "voting-names"
        if voting_names_only
        else "topology-dangling"
        if dangling_only
        else "topology"
    ]
    validate_family_selection(state["release"], selected)
    validate_families(selected)
    runner = state["runner_id"]
    owned(state, runner)
    token = uuid.uuid4().hex[:8]
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + token
    out = path.parent / "topology" / identifier
    out.mkdir(parents=True, exist_ok=False)
    before = checkpoint()
    reserve = 1_500_000_000
    save(
        out / "admission.json",
        {
            "existing_accounted_bytes": before["accounted_bytes"],
            "growth_reserve_bytes": reserve,
            "image_pull": False,
            "working_limit_bytes": 24_000_000_000,
            "task_limit_bytes": 30_000_000_000,
        },
    )
    if before["accounted_bytes"] + reserve >= 24_000_000_000 or before["host_free_bytes"] < reserve:
        raise RuntimeError("Topology fixture exceeds conservative working budget")
    nodes = {}
    active = []
    volumes = []
    errors = []
    result_path = None
    cluster_name = "es-cli-topology-" + token

    def resources():
        save(
            out / "resources.json",
            {"active_nodes": active, "active_volumes": volumes, "cleanup_errors": errors},
        )

    def inside(*args, input=None, timeout=90):
        result = subprocess.run(
            ["docker", "exec", "-i", runner, *args],
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError("Runner command failed: " + (result.stdout + result.stderr)[-3000:])
        return result

    try:
        resources()
        helper = ROOT / "tools/research/http_attempt.py"
        expected_helper = hashlib.sha256(helper.read_bytes()).hexdigest()
        docker("exec", runner, "mkdir", "-p", "/workspace/tools/research")
        docker("cp", str(helper), runner + ":/workspace/tools/research/http_attempt.py")
        copied_helper = docker(
            "exec",
            runner,
            "python3",
            "-c",
            "import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/workspace/tools/research/http_attempt.py').read_bytes()).hexdigest())",
        ).stdout.strip()
        save(
            out / "readiness-helper.json",
            {
                "source": "tools/research/http_attempt.py",
                "expected_sha256": expected_helper,
                "runner_sha256": copied_helper,
                "git_sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
            },
        )
        if copied_helper != expected_helper:
            raise RuntimeError("Readiness helper copy differs;no nodes or HTTP created")
        for letter in ["a", "b", "c"]:
            name = cluster_name + "-" + letter
            volume = name + "-data"
            created = inside(
                "docker", "volume", "create", "--label", LABEL + "=" + state["lab_id"], volume
            ).stdout.strip()
            assert created == volume
            volumes.append(volume)
            resources()
            environment = {
                "cluster.name": cluster_name,
                "node.name": name,
                "node.roles": "master,data,ingest",
                # Bootstrap one explicit initial voter, then let the cluster expand
                # to three voters; the REST fixture checks the committed IDs.
                "cluster.initial_master_nodes": cluster_name + "-a",
                "discovery.seed_hosts": ",".join(
                    cluster_name + "-" + item for item in ["a", "b", "c"]
                ),
                "cluster.indices.tombstones.size": "1",
                "node.store.allow_mmap": "false",
                "node.processors": "2",
                "xpack.security.enabled": "false",
                "xpack.ml.enabled": "false",
                "ingest.geoip.downloader.enabled": "false",
                "ES_JAVA_OPTS": "-Xms512m -Xmx512m -XX:ActiveProcessorCount=2 -Xlog:disable -Xlog:gc*:stderr:utctime,level,tags -XX:-HeapDumpOnOutOfMemoryError",
            }
            if state["release"] in EARLY_VOTING_RELEASES:
                environment = startup_settings(state["release"], state["lab_id"])
                environment.pop("discovery.type")
                environment.update(
                    {
                        "cluster.name": cluster_name,
                        "node.name": name,
                        "cluster.initial_master_nodes": cluster_name + "-a",
                        "discovery.seed_hosts": ",".join(
                            cluster_name + "-" + item for item in ["a", "b", "c"]
                        ),
                        "node.store.allow_mmap": "false",
                        "xpack.ml.enabled": "false",
                    }
                )
                environment["ES_JAVA_OPTS"] += " -XX:ActiveProcessorCount=2"
            if state["release"] == "7.17.29":
                environment["gateway.auto_import_dangling_indices"] = "false"
            if voting_names_only and letter in {"b", "c"}:
                environment["node.name"] = cluster_name + "-duplicate"
            args = [
                "docker",
                "create",
                "--pull=never",
                "--name",
                name,
                "--label",
                LABEL + "=" + state["lab_id"],
                "--label",
                "io.es-cli.research.kind=topology",
                "--network",
                state["network_id"],
                "--network-alias",
                name,
                "--memory=2g",
                "--memory-swap=2g",
                "--ulimit",
                "nofile=65536:65536",
                "--log-driver=local",
                "--log-opt=max-size=5m",
                "--log-opt=max-file=2",
                "--mount",
                "type=volume,source=" + volume + ",target=/usr/share/elasticsearch/data",
            ]
            for key, value in environment.items():
                args.extend(["-e", key + "=" + value])
            args.append(state["image"])
            node = inside(*args).stdout.strip()
            active.append(node)
            nodes[letter] = {"id": node, "name": name, "volume": volume}
            if voting_names_only:
                nodes[letter]["node_name"] = environment["node.name"]
            resources()
            save(
                out / (letter + "-node-config.json"),
                {
                    "image": state["image"],
                    "environment": environment,
                    "node": nodes[letter],
                    "host_ports": [],
                    "memory_limit_bytes": 2147483648,
                },
            )
        for node in active:
            inside("docker", "start", node)
        url = "http://" + nodes["a"]["name"] + ":9200"
        deadline = time.monotonic() + 180
        identity = None
        while time.monotonic() < deadline:
            config = {
                "url": url + "/_cluster/health?wait_for_nodes=3&timeout=1s",
                "method": "GET",
                "headers": {},
                "body_b64": None,
                "socket_timeout": 3,
                "max_response_bytes": 16000,
            }
            result = inside(
                "python3",
                "/workspace/tools/research/http_attempt.py",
                input=json.dumps(config),
                timeout=6,
            )
            wire = json.loads(result.stdout)
            save(out / "readiness-last.json", wire)
            if wire.get("status") == 200:
                health = json.loads(base64.b64decode(wire["body_b64"]))
                if health.get("number_of_nodes") == 3 and not health.get("timed_out"):
                    config["url"] = url + "/"
                    response = inside(
                        "python3",
                        "/workspace/tools/research/http_attempt.py",
                        input=json.dumps(config),
                        timeout=6,
                    )
                    identity = json.loads(base64.b64decode(json.loads(response.stdout)["body_b64"]))
                    if (
                        identity["version"]["number"] != state["release"]
                        or identity["cluster_name"] != cluster_name
                    ):
                        raise RuntimeError("Wrong version or cluster in topology readiness")
                    save(out / "server-identity.json", identity)
                    save(out / "health-ready.json", health)
                    break
            time.sleep(2)
        if identity is None:
            for letter, node in nodes.items():
                captured = docker("logs", "--tail", "70", node["id"])
                logs = captured.stdout + captured.stderr
                (out / (letter + "-startup.log")).write_text(logs[-16000:])
            raise RuntimeError("Three-node topology did not become ready")
        save(out / "disk-running.json", checkpoint())
        result_path = run_attempt(
            path,
            selected,
            target_url=url,
            extra_env={"ES_TOPOLOGY_NODES": json.dumps(nodes)},
            fixture_context={
                "kind": "three-node-duplicate-names"
                if voting_names_only
                else "three-node-persistent-topology",
                "base_url": url,
                "server_identity": identity,
                "nodes": nodes,
                "controller_ref": str(out.relative_to(ROOT)),
                "tombstones_size": 1,
                "note": "Only duplicate REST node names;Docker aliases stay unique;no dangling-index cases"
                if voting_names_only
                else "Test-only retention=1 plus one extra owned filler deletion evicts missed UUIDs while preserving later dangling-delete propagation. No production setting recommendation.",
            },
        )
        save(out / "attempt-ref.json", {"attempt": str(result_path.relative_to(ROOT))})
        save(out / "disk-after-execution.json", checkpoint())
    except BaseException as error:
        save(
            out / "infrastructure-error.json",
            {"type": type(error).__name__, "message": str(error)[-3000:]},
        )
        raise
    finally:
        # Retain bounded coordination diagnostics before removing owned nodes.
        for letter, node in nodes.items():
            captured = docker("logs", "--tail", "100", node["id"])
            (out / (letter + "-final.log")).write_text((captured.stdout + captured.stderr)[-24000:])
        for node in list(active):
            try:
                owned(state, node)
                docker("rm", "-f", node)
                active.remove(node)
                resources()
            except Exception as error:
                errors.append(type(error).__name__ + ": owned topology node cleanup failed")
        for volume in list(volumes):
            try:
                owned(state, volume, "volume")
                docker("volume", "rm", volume)
                volumes.remove(volume)
                resources()
            except Exception as error:
                errors.append(type(error).__name__ + ": owned topology volume cleanup failed")
        resources()
        save(out / "disk-after-cleanup.json", checkpoint())
        print(
            json.dumps(
                {
                    "topology_run": str(out),
                    "attempt": str(result_path) if result_path else None,
                    "cleanup_errors": errors,
                }
            ),
            flush=True,
        )
    if errors:
        raise RuntimeError("Topology resource cleanup incomplete")
    return result_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dangling-only", action="store_true")
    mode.add_argument("--voting-names-only", action="store_true")
    args = parser.parse_args()
    run(args.state, dangling_only=args.dangling_only, voting_names_only=args.voting_names_only)


if __name__ == "__main__":
    main()
