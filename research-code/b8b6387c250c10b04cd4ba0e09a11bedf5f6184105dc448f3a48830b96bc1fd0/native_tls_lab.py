"""Own sequential native-TLS nodes on the existing anchor image; no extra image pull."""

import argparse
import base64
import hashlib
import json
import secrets
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from anchor_lab import LABEL, ROOT, docker, owned, save, validate_state
from disk_checkpoint import checkpoint


def run(state_path, *, required_auth=False):
    path, state = validate_state(state_path)
    if state["status"] != "ready-development-anchor" or state["release"] not in {
        "9.5.6",
        "8.19.24",
    }:
        raise ValueError("Native TLS pilot requires the current ready prepared 8.x/9.x anchor")
    owned(state, state["runner_id"])
    runner = state["runner_id"]
    token = uuid.uuid4().hex[:8]
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + token
    out = path.parent / "native-tls" / identifier
    out.mkdir(parents=True, exist_ok=False)
    before = checkpoint()
    save(out / "disk-before.json", before)
    reserve = 800_000_000
    save(
        out / "admission.json",
        {
            "existing_accounted_bytes": before["accounted_bytes"],
            "growth_reserve_bytes": reserve,
            "working_limit_bytes": 24_000_000_000,
            "task_limit_bytes": 30_000_000_000,
            "image_pull": False,
        },
    )
    if before["accounted_bytes"] + reserve >= 24_000_000_000 or before["host_free_bytes"] < reserve:
        raise RuntimeError("Native TLS fixture exceeds conservative working budget")
    hostname = "es-cli-native-" + token
    wrong = "es-cli-native-wrong-" + token
    remote = "/workspace/native-tls/" + identifier
    material = remote + "/material"
    password = secrets.token_hex(24)
    nodes = []
    cleanup_errors = []
    outcomes = []

    def inside(*args, input=None, timeout=90, check=True):
        result = subprocess.run(
            ["docker", "exec", "-i", runner, *args],
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            message = (result.stdout + result.stderr).replace(password, "[redacted]")
            raise RuntimeError("Runner command failed: " + message[-3000:])
        return result

    def remove_node(node):
        owned(state, node)
        docker("rm", "-f", node)
        nodes.remove(node)
        save(out / "resources.json", {"active_nodes": nodes, "cleanup_errors": cleanup_errors})

    try:
        hashes = {}
        for name in ["native_tls_probe.py", "http_attempt.py"]:
            source = ROOT / "tools/research" / name
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
            docker("cp", str(source), runner + ":/workspace/tools/research/" + name)
        actual = inside(
            "python3",
            "-c",
            "import hashlib,json;from pathlib import Path;"
            "p=Path('/workspace/tools/research');"
            "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() "
            "for n in ['native_tls_probe.py','http_attempt.py']}))",
        )
        assert json.loads(actual.stdout) == hashes, "Copied TLS code hash mismatch"
        save(
            out / "execution-provenance.json",
            {
                "schema_version": 1,
                "kind": "native-tls-transport-not-rest-coverage",
                "auth_policy": "required-basic" if required_auth else "anonymous-and-basic",
                "git_sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "tool_sha256": {
                    **hashes,
                    "native_tls_lab.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                },
                "image": state["image"],
                "base": state["base"],
                "release": state["release"],
                "network": "existing internal lab network; no published host ports",
                "actual_runner_hashes": json.loads(actual.stdout),
            },
        )
        inside(
            "python3",
            "/workspace/tools/research/native_tls_probe.py",
            "--prepare",
            material,
            "--hostname",
            hostname,
        )
        docker("cp", runner + ":" + material + "/certificates.json", str(out / "certificates.json"))

        for mode in ["ca-signed", "self-signed"]:
            name = "es-cli-tls-" + token + "-" + mode
            environment = {
                "discovery.type": "single-node",
                "cluster.name": "native-tls-" + token,
                "node.name": name,
                "ES_JAVA_OPTS": "-Xms512m -Xmx512m -XX:ActiveProcessorCount=2 -Xlog:disable -Xlog:gc*:stderr:utctime,level,tags -XX:-HeapDumpOnOutOfMemoryError",
                "node.processors": "2",
                "node.store.allow_mmap": "false",
                "xpack.security.enabled": "true",
                "xpack.security.enrollment.enabled": "false",
                "xpack.security.http.ssl.enabled": "true",
                "xpack.security.http.ssl.certificate": "research-tls/server.crt",
                "xpack.security.http.ssl.key": "research-tls/server.key",
                "xpack.security.http.ssl.client_authentication": "none",
                "xpack.security.authc.anonymous.roles": "superuser",
                "ingest.geoip.downloader.enabled": "false",
                "ELASTIC_PASSWORD": password,
            }
            if required_auth:
                environment.pop("xpack.security.authc.anonymous.roles")
            arguments = [
                "docker",
                "create",
                "--name",
                name,
                "--label",
                LABEL + "=" + state["lab_id"],
                "--label",
                "io.es-cli.research.kind=native-tls",
                "--network",
                state["network_id"],
                "--network-alias",
                hostname,
                "--network-alias",
                wrong,
                "--memory",
                "2g",
                "--memory-swap",
                "2g",
                "--log-driver",
                "local",
                "--log-opt",
                "max-size=5m",
                "--log-opt",
                "max-file=2",
                "--tmpfs",
                "/usr/share/elasticsearch/data:rw,size=256m,uid=1000,gid=0,mode=0775",
            ]
            for key, value in environment.items():
                arguments.extend(["-e", key + "=" + value])
            arguments.append(state["image"])
            node = inside(*arguments).stdout.strip()
            nodes.append(node)
            save(out / "resources.json", {"active_nodes": nodes, "cleanup_errors": cleanup_errors})
            save(
                out / (mode + "-node-config.json"),
                {
                    "image": state["image"],
                    "node_id": node,
                    "environment": {
                        key: "[ephemeral redacted]" if key == "ELASTIC_PASSWORD" else value
                        for key, value in environment.items()
                    },
                    "host_ports": [],
                    "data_tmpfs_bytes": 268435456,
                },
            )
            inside(
                "docker",
                "cp",
                material + "/" + mode + "/node",
                node + ":/usr/share/elasticsearch/config/research-tls",
            )
            inside("docker", "start", node)
            ca = (
                material + "/ca.crt"
                if mode == "ca-signed"
                else material + "/" + mode + "/node/server.crt"
            )
            readiness = {
                "url": "https://" + hostname + ":9200/",
                "method": "GET",
                "headers": {},
                "body_b64": None,
                "socket_timeout": 3,
                "max_response_bytes": 16000,
                "tls": {"cafile": ca},
            }
            if required_auth:
                readiness["headers"]["Authorization"] = (
                    "Basic " + base64.b64encode(("elastic:" + password).encode()).decode()
                )
            ready = False
            startup_deadline = time.monotonic() + 150
            for _ in range(60):
                if time.monotonic() >= startup_deadline:
                    break
                result = inside(
                    "python3",
                    "/workspace/tools/research/http_attempt.py",
                    input=json.dumps(readiness),
                    timeout=6,
                    check=False,
                )
                if result.returncode == 0:
                    observed = json.loads(result.stdout)
                    save(out / (mode + "-readiness-last.json"), observed)
                    if observed.get("status") == 200:
                        body = json.loads(base64.b64decode(observed["body_b64"]))
                        if body["version"]["number"] != state["release"]:
                            raise RuntimeError("Wrong Elasticsearch version in native TLS fixture")
                        save(out / (mode + "-server-identity.json"), body)
                        ready = True
                        break
                time.sleep(2)
            if not ready:
                log = docker("logs", "--tail", "60", node).stdout.replace(password, "[redacted]")
                (out / (mode + "-startup.log")).write_text(log[-12000:])
                raise RuntimeError(
                    "Native TLS node did not become ready; inspect saved startup log"
                )
            save(out / (mode + "-disk-running.json"), checkpoint())
            config = {
                "material": material,
                "output": remote + "/evidence/" + mode,
                "mode": mode,
                "required_auth": required_auth,
                "hostname": hostname,
                "wrong_hostname": wrong,
                "password": password,
                "release": state["release"],
                "system_ca_filename": "es-cli-native-" + token + "-" + mode + ".crt",
            }
            result = inside(
                "python3",
                "/workspace/tools/research/native_tls_probe.py",
                input=json.dumps(config),
                timeout=150,
                check=False,
            )
            print(result.stdout, flush=True)
            (out / (mode + "-console.log")).write_text(
                (result.stdout + result.stderr).replace(password, "[redacted]")[-16000:]
            )
            target = out / mode
            target.mkdir()
            copied = subprocess.run(
                ["docker", "cp", runner + ":" + config["output"] + "/.", str(target)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            outcomes.append(
                {
                    "mode": mode,
                    "exit_code": result.returncode,
                    "evidence_copied": copied.returncode == 0,
                }
            )
            save(out / "driver-outcome.json", {"kind": "native-tls-transport", "modes": outcomes})
            remove_node(node)
            if result.returncode or copied.returncode:
                raise RuntimeError("Native TLS probes incomplete; partial evidence preserved")
    except Exception as error:
        save(
            out / "infrastructure-error.json",
            {
                "type": type(error).__name__,
                "message": str(error).replace(password, "[redacted]")[-3000:],
            },
        )
        raise
    finally:
        for node in list(nodes):
            try:
                remove_node(node)
            except Exception as error:
                cleanup_errors.append(type(error).__name__ + ": native TLS node cleanup failed")
        for mode in ["ca-signed", "self-signed"]:
            cert = "/usr/local/share/ca-certificates/es-cli-native-" + token + "-" + mode + ".crt"
            result = inside(
                "python3",
                "-c",
                "from pathlib import Path;p=Path(" + repr(cert) + ");"
                "assert p.name.startswith('es-cli-native-');p.unlink(missing_ok=True)",
                check=False,
            )
            if result.returncode:
                cleanup_errors.append("system CA file cleanup failed")
        result = inside("update-ca-certificates", check=False)
        if result.returncode:
            cleanup_errors.append("system CA bundle cleanup failed")
        result = inside(
            "python3",
            "-c",
            "from pathlib import Path;import shutil;p=Path(" + repr(remote) + ");"
            "assert p.parent==Path('/workspace/native-tls');"
            "shutil.rmtree(p) if p.exists() else None",
            check=False,
        )
        if result.returncode:
            cleanup_errors.append("private workspace cleanup failed")
        save(out / "resources.json", {"active_nodes": nodes, "cleanup_errors": cleanup_errors})
        save(out / "disk-after.json", checkpoint())
        print(
            json.dumps(
                {"native_tls_run": str(out), "modes": outcomes, "cleanup_errors": cleanup_errors}
            ),
            flush=True,
        )
    if cleanup_errors:
        raise RuntimeError("Native TLS cleanup incomplete")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    parser.add_argument("--required-auth", action="store_true")
    args = parser.parse_args()
    run(args.state, required_auth=args.required_auth)


if __name__ == "__main__":
    main()
