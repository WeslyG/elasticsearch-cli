"""Generate ephemeral mTLS/validity fixtures and probe native Elasticsearch HTTPS."""

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
from datetime import datetime, timedelta, timezone
from pathlib import Path


def command(*args):
    return subprocess.check_output(list(args), stderr=subprocess.DEVNULL, timeout=30)


def prepare(root, hostname):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    certificates = {}

    def remember(name, path):
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

    for issuer in ["server-ca", "client-ca", "wrong-client-ca"]:
        command(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "7",
            "-subj",
            "/CN=ES CLI " + issuer,
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            str(root / (issuer + ".key")),
            "-out",
            str(root / (issuer + ".crt")),
        )
        remember(issuer, root / (issuer + ".crt"))
        (root / (issuer + ".index")).touch()
        (root / (issuer + ".serial")).write_text("01\n")

    def issue(name, issuer, purpose, *, offset=None, server=False):
        target = root / name / "node" if server else root
        target.mkdir(parents=True, exist_ok=True)
        stem = "server" if server else name
        key, cert, csr = (target / (stem + suffix) for suffix in [".key", ".crt", ".csr"])
        command(
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=" + (hostname if server else name),
            "-keyout",
            str(key),
            "-out",
            str(csr),
        )
        config = root / (name + ".cnf")
        config.write_text(
            "[ca]\ndefault_ca=research\n[research]\n"
            + "database="
            + str(root / (issuer + ".index"))
            + "\n"
            + "serial="
            + str(root / (issuer + ".serial"))
            + "\n"
            + "certificate="
            + str(root / (issuer + ".crt"))
            + "\n"
            + "private_key="
            + str(root / (issuer + ".key"))
            + "\n"
            + "new_certs_dir="
            + str(root)
            + "\ndefault_md=sha256\ndefault_days=2\n"
            + "unique_subject=no\npolicy=names\nx509_extensions=leaf\n"
            + "[names]\ncommonName=supplied\n[leaf]\nbasicConstraints=critical,CA:FALSE\n"
            + "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage="
            + purpose
            + "\n"
            + ("subjectAltName=DNS:" + hostname + "\n" if server else "")
        )
        arguments = [
            "openssl",
            "ca",
            "-batch",
            "-notext",
            "-config",
            str(config),
            "-in",
            str(csr),
            "-out",
            str(cert),
        ]
        if offset is not None:
            now = datetime.now(timezone.utc)
            arguments += [
                "-startdate",
                (now + timedelta(days=offset)).strftime("%Y%m%d%H%M%SZ"),
                "-enddate",
                (now + timedelta(days=offset + 1)).strftime("%Y%m%d%H%M%SZ"),
            ]
        command(*arguments)
        key.chmod(0o640 if server else 0o600)
        remember(name, cert)

    issue("mtls", "server-ca", "serverAuth", server=True)
    issue("expired-server", "server-ca", "serverAuth", offset=-4, server=True)
    issue("future-server", "server-ca", "serverAuth", offset=3, server=True)
    issue("client-valid", "client-ca", "clientAuth")
    issue("client-expired", "client-ca", "clientAuth", offset=-4)
    issue("client-wrong-ca", "wrong-client-ca", "clientAuth")
    issue("client-wrong-usage", "client-ca", "serverAuth")
    (root / "mtls/node/client-ca.crt").write_bytes((root / "client-ca.crt").read_bytes())
    (root / "certificates.json").write_text(json.dumps(certificates, indent=2) + "\n")


def run_probes(config):
    root, output = Path(config["material"]), Path(config["output"])
    output.mkdir(parents=True, exist_ok=False)
    mode = config["mode"]
    rows = []
    stream = (output / "observations.jsonl").open("x")

    def probe(
        name,
        *,
        client=None,
        credential="correct",
        trust="custom",
        wrong_host=False,
        status=None,
        verify_code=None,
        alerts=(),
    ):
        tls = {}
        if trust == "insecure":
            tls["insecure"] = True
        else:
            tls["cafile"] = str(root / ("client-ca.crt" if trust == "wrong" else "server-ca.crt"))
        if client:
            tls.update(
                certfile=str(root / (client + ".crt")), keyfile=str(root / (client + ".key"))
            )
        headers = {"Accept": "application/json"}
        if credential != "omitted":
            password = config["password"] if credential == "correct" else "deliberately-wrong"
            headers["Authorization"] = (
                "Basic " + base64.b64encode(("elastic:" + password).encode()).decode()
            )
        payload = {
            "url": "https://" + config["wrong_hostname" if wrong_host else "hostname"] + ":9200/",
            "method": "GET",
            "headers": headers,
            "body_b64": None,
            "socket_timeout": 5,
            "max_response_bytes": 16000,
            "tls": tls,
        }
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("http_attempt.py"))],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode:
            raise RuntimeError("TLS worker did not produce a complete observation")
        wire = json.loads(result.stdout)
        raw = base64.b64decode(wire["body_b64"]) if wire.get("body_b64") is not None else b""
        error = wire.get("error")
        checks = []

        def check(name, actual, expected):
            checks.append(
                {
                    "name": name,
                    "actual": actual,
                    "expected": expected,
                    "passed": type(actual) is type(expected) and actual == expected,
                }
            )

        expected_error = (
            "SSLCertVerificationError"
            if verify_code is not None
            else "SSLError"
            if alerts
            else None
        )
        if expected_error:
            check("TLS rejection has no HTTP response", wire["status"], None)
            check("TLS exception class", (error or {}).get("type"), expected_error)
            if verify_code is not None:
                check(
                    "certificate verification code", (error or {}).get("verify_code"), verify_code
                )
            if alerts:
                check(
                    "peer certificate alert",
                    any(a in (error or {}).get("message", "").lower() for a in alerts),
                    True,
                )
        else:
            check("HTTP status", wire["status"], status)
            check("no transport error", error, None)
            data = json.loads(raw) if raw else {}
            if status == 200:
                check(
                    "actual Elasticsearch release",
                    data.get("version", {}).get("number"),
                    config["release"],
                )
                check("actual native TLS node", data.get("name"), config["node_name"])
            if status == 401:
                check(
                    "HTTP authentication rejection",
                    data.get("error", {}).get("type"),
                    "security_exception",
                )
        record = {
            "schema_version": 1,
            "kind": "native-tls-transport-not-rest-coverage",
            "suite": "mtls-validity",
            "case_id": mode + "." + name,
            "mode": mode,
            "expected": {
                "status": status,
                "tls_error": expected_error,
                "verify_code": verify_code,
                "tls_alert_markers": list(alerts),
            },
            "request": {
                "method": "GET",
                "url": payload["url"],
                "tls": tls,
                "authorization": "omitted" if credential == "omitted" else "Basic [redacted]",
                "credential_kind": credential,
            },
            "certificate_sha256": hashlib.sha256(
                (root / mode / "node/server.crt").read_bytes()
            ).hexdigest(),
            "client_certificate_sha256": hashlib.sha256(
                (root / (client + ".crt")).read_bytes()
            ).hexdigest()
            if client
            else None,
            "response": {
                "status": wire["status"],
                "headers": wire.get("headers", {}),
                "body_base64": wire.get("body_b64"),
                "complete": wire.get("body_complete", False),
                "body_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            },
            "transport_error": error,
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
        if mode == "mtls":
            required = ("certificate_required", "bad_certificate")
            probe("missing-client", alerts=required)
            probe("insecure-still-needs-client", trust="insecure", alerts=required)
            probe(
                "untrusted-client",
                client="client-wrong-ca",
                alerts=("unknown_ca", "certificate_unknown", "bad_certificate"),
            )
            probe(
                "expired-client",
                client="client-expired",
                alerts=("certificate_expired", "certificate_unknown", "bad_certificate"),
            )
            probe(
                "wrong-client-purpose",
                client="client-wrong-usage",
                alerts=("unsupported_certificate", "certificate_unknown", "bad_certificate"),
            )
            probe("valid-client-no-basic", client="client-valid", credential="omitted", status=401)
            probe("valid-client-wrong-basic", client="client-valid", credential="wrong", status=401)
            probe("valid-client-correct-basic", client="client-valid", status=200)
            probe(
                "client-does-not-trust-server", client="client-valid", trust="wrong", verify_code=20
            )
            probe("wrong-host", client="client-valid", wrong_host=True, verify_code=62)
        elif mode in {"expired-server", "future-server"}:
            probe("validity-rejected", verify_code=10 if mode == "expired-server" else 9)
            probe("explicit-insecure-only", trust="insecure", status=200)
        else:
            raise ValueError("Unknown advanced TLS mode")
    finally:
        stream.close()
        raw = (output / "observations.jsonl").read_bytes()
        manifest = {
            "schema_version": 1,
            "kind": "native-tls-transport-not-rest-coverage",
            "suite": "mtls-validity",
            "release": config["release"],
            "mode": mode,
            "auth_policy": "required-basic",
            "states": {s: sum(r["state"] == s for r in rows) for s in ["passed", "failed"]},
            "probes": len(rows),
            "http_responses": sum(r["response"]["status"] is not None for r in rows),
            "tls_rejections": sum(r["transport_error"] is not None for r in rows),
            "observations_sha256": hashlib.sha256(raw).hexdigest(),
            "system_ca_removed": True,
            "system_trust_modified": False,
            "runtime": {
                "python": sys.version,
                "platform": platform.platform(),
                "openssl": ssl.OPENSSL_VERSION,
            },
            "remaining": [
                "certificate revocation",
                "encrypted private keys",
                "other Elasticsearch releases/OS",
                "controlled network faults",
                "installed core/CLI consumers",
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
