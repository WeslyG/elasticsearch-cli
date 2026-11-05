"""Native Elasticsearch TLS probes; transport evidence is separate from REST coverage."""

import argparse
import base64
import hashlib
import json
import os
import platform
import ssl
import subprocess
import sys
import time
from pathlib import Path


def command(*args):
    return subprocess.check_output(list(args), stderr=subprocess.DEVNULL, timeout=30)


def prepare(root, hostname):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=ES CLI research CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        str(root / "ca.key"),
        "-out",
        str(root / "ca.crt"),
    )
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=Unrelated research CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-keyout",
        str(root / "wrong.key"),
        "-out",
        str(root / "wrong.crt"),
    )
    node = root / "ca-signed/node"
    node.mkdir(parents=True)
    command(
        "openssl",
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=" + hostname,
        "-keyout",
        str(node / "server.key"),
        "-out",
        str(root / "server.csr"),
    )
    (root / "server.ext").write_text(
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:" + hostname + "\n"
    )
    command(
        "openssl",
        "x509",
        "-req",
        "-in",
        str(root / "server.csr"),
        "-CA",
        str(root / "ca.crt"),
        "-CAkey",
        str(root / "ca.key"),
        "-CAcreateserial",
        "-days",
        "2",
        "-extfile",
        str(root / "server.ext"),
        "-out",
        str(node / "server.crt"),
    )
    self_node = root / "self-signed/node"
    self_node.mkdir(parents=True)
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=" + hostname,
        "-addext",
        "subjectAltName=DNS:" + hostname,
        "-addext",
        "basicConstraints=critical,CA:FALSE",
        "-addext",
        "extendedKeyUsage=serverAuth",
        "-keyout",
        str(self_node / "server.key"),
        "-out",
        str(self_node / "server.crt"),
    )
    # Disposable node needs to read its own key as uid 1000; no keys leave this lab.
    for directory in [node, self_node]:
        (directory / "server.key").chmod(0o644)
    certificates = {}
    for name, path in [
        ("ca", root / "ca.crt"),
        ("wrong-ca", root / "wrong.crt"),
        ("ca-signed", node / "server.crt"),
        ("self-signed", self_node / "server.crt"),
    ]:
        certificates[name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pem": path.read_text(),
            "details": command(
                "openssl",
                "x509",
                "-in",
                str(path),
                "-noout",
                "-subject",
                "-issuer",
                "-dates",
                "-serial",
            ).decode(),
        }
    (root / "certificates.json").write_text(json.dumps(certificates, indent=2) + "\n")


def run_probes(config):
    root = Path(config["material"])
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=False)
    mode = config["mode"]
    trust = root / "ca.crt" if mode == "ca-signed" else root / mode / "node/server.crt"
    ca_destination = Path("/usr/local/share/ca-certificates") / config["system_ca_filename"]
    assert ca_destination.name.startswith("es-cli-native-") and not ca_destination.exists()
    rows = []
    stream = (output / "observations.jsonl").open("x")

    def probe(
        name, *, tls=None, hostname=None, credential=None, status=None, error=None, verify_code=None
    ):
        request_headers = {"Accept": "application/json"}
        if credential is not None:
            request_headers["Authorization"] = (
                "Basic " + base64.b64encode(("elastic:" + credential).encode()).decode()
            )
        payload = {
            "url": "https://" + (hostname or config["hostname"]) + ":9200/",
            "method": "GET",
            "headers": request_headers,
            "body_b64": None,
            "socket_timeout": 5,
            "max_response_bytes": 16000,
            "tls": tls or {},
        }
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("http_attempt.py"))],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=8,
        )
        wire = (
            json.loads(result.stdout)
            if result.returncode == 0
            else {"status": None, "error": {"type": "worker-failure"}, "body_b64": None}
        )
        raw = base64.b64decode(wire["body_b64"]) if wire.get("body_b64") is not None else b""
        actual_error = wire.get("error")
        checks = []

        def check(label, actual, expected):
            checks.append(
                {
                    "name": label,
                    "actual": actual,
                    "expected": expected,
                    "passed": type(actual) is type(expected) and actual == expected,
                }
            )

        if error:
            check("TLS rejected before HTTP response", wire["status"], None)
            check("exact TLS error class", (actual_error or {}).get("type"), error)
            if verify_code is not None:
                check(
                    "certificate verification code",
                    (actual_error or {}).get("verify_code"),
                    verify_code,
                )
        else:
            check("HTTP status", wire["status"], status)
            check("no transport error", actual_error, None)
            data = json.loads(raw) if raw else {}
            if status == 200:
                check(
                    "actual Elasticsearch version",
                    data.get("version", {}).get("number"),
                    config["release"],
                )
            if status == 401:
                check(
                    "authentication rejection",
                    data.get("error", {}).get("type"),
                    "security_exception",
                )
        record = {
            "schema_version": 1,
            "kind": "native-tls-transport-not-rest-coverage",
            "case_id": mode + "." + name,
            "mode": mode,
            "expected": {"status": status, "tls_error": error},
            "request": {
                "method": "GET",
                "url": payload["url"],
                "tls": payload["tls"],
                "authorization": "Basic [redacted]" if credential is not None else "omitted",
            },
            "certificate_sha256": hashlib.sha256(
                (root / mode / "node/server.crt").read_bytes()
            ).hexdigest(),
            "response": {
                "status": wire["status"],
                "headers": wire.get("headers", {}),
                "body_base64": wire.get("body_b64"),
                "complete": wire.get("body_complete", False),
                "body_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            },
            "transport_error": actual_error,
            "assertions": checks,
            "state": "passed" if all(c["passed"] for c in checks) else "failed",
            "elapsed_seconds": round(time.monotonic() - started, 6),
        }
        stream.write(json.dumps(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        rows.append(record)
        print(record["case_id"], record["state"], wire["status"], flush=True)

    try:
        probe("default-untrusted", error="SSLCertVerificationError")
        probe("explicit-trust-no-auth", tls={"cafile": str(trust)}, status=200)
        probe("wrong-ca", tls={"cafile": str(root / "wrong.crt")}, error="SSLCertVerificationError")
        probe(
            "wrong-host",
            hostname=config["wrong_hostname"],
            tls={"cafile": str(trust)},
            error="SSLCertVerificationError",
            verify_code=62,
        )
        probe("explicit-insecure", tls={"insecure": True}, status=200)
        probe(
            "basic-wrong", tls={"cafile": str(trust)}, credential="deliberately-wrong", status=401
        )
        probe(
            "basic-correct", tls={"cafile": str(trust)}, credential=config["password"], status=200
        )
        ca_destination.write_bytes(trust.read_bytes())
        command("update-ca-certificates")
        probe("system-trust-no-cafile", status=200)
        probe(
            "system-trust-wrong-host",
            hostname=config["wrong_hostname"],
            error="SSLCertVerificationError",
            verify_code=62,
        )
    finally:
        ca_destination.unlink(missing_ok=True)
        command("update-ca-certificates")
        try:
            probe("system-trust-removed", error="SSLCertVerificationError")
        finally:
            stream.close()
            raw = (output / "observations.jsonl").read_bytes()
            manifest = {
                "schema_version": 1,
                "kind": "native-tls-transport-not-rest-coverage",
                "release": config["release"],
                "mode": mode,
                "states": {
                    state: sum(r["state"] == state for r in rows) for state in ["passed", "failed"]
                },
                "probes": len(rows),
                "http_responses": sum(r["response"]["status"] is not None for r in rows),
                "tls_rejections": sum(r["transport_error"] is not None for r in rows),
                "observations_sha256": hashlib.sha256(raw).hexdigest(),
                "system_ca_removed": not ca_destination.exists(),
                "runtime": {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "openssl": ssl.OPENSSL_VERSION,
                },
                "remaining": [
                    "expired certificates",
                    "mTLS",
                    "required-auth-only cluster",
                    "proxy faults",
                    "core/CLI consumers",
                    "other Elasticsearch versions",
                ],
            }
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare")
    parser.add_argument("--hostname")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare, args.hostname)
    else:
        run_probes(json.load(sys.stdin))


if __name__ == "__main__":
    main()
