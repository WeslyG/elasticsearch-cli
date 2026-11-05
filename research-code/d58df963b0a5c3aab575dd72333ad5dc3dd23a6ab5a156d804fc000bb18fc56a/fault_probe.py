"""Controlled loopback faults against a real ES backend; never REST API coverage."""

import hashlib
import http.client
import json
import os
import socket
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from evidence_runner import OMITTED, Session


def run(config):
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=False)
    backend = urlsplit(config["base_url"])
    if (backend.scheme, backend.hostname, backend.port, backend.path) != (
        "http",
        "es-cli-active",
        9200,
        "",
    ):
        raise ValueError("Fault backend must be the owned internal primary")
    index = config["prefix"] + "-index"
    assert index.startswith("es-cli-fault-") and "/" not in index
    case_rows, events = [], []
    lock = threading.Lock()
    ready = {name: threading.Event() for name in ["drop-write", "socket-timeout", "wall-deadline"]}
    trace_file = (output / "proxy-events.jsonl").open("x")
    fixture_purpose = "controlled-transport-fixture-not-api-coverage"

    def event(row):
        with lock:
            events.append(row)
            trace_file.write(json.dumps(row) + "\n")
            trace_file.flush()
            os.fsync(trace_file.fileno())

    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.forward()

        def do_PUT(self):
            self.forward()

        def forward(self):
            name = self.path.removeprefix("/")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            row = {
                "path": self.path,
                "method": self.command,
                "request_body_sha256": hashlib.sha256(body).hexdigest(),
                "backend_forwarded": False,
            }
            if name == "redirect":
                self.send_response(307)
                self.send_header("Location", proxy_url + "/redirect-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
                event(row)
                self.close_connection = True
                return
            routes = {
                "drop-write": ("PUT", "/" + index + "/_doc/lost?op_type=create&refresh=true"),
                "socket-timeout": ("PUT", "/" + index + "/_doc/socket?op_type=create&refresh=true"),
                "wall-deadline": ("PUT", "/" + index + "/_doc/wall?op_type=create&refresh=true"),
                "short-length": ("GET", "/" + index + "/_doc/readable"),
                "short-chunked": ("GET", "/" + index + "/_doc/readable"),
                "delayed-read": ("GET", "/" + index + "/_doc/readable"),
                "response-limit": ("GET", "/" + index + "/_doc/large"),
                "redirect-target": (
                    "PUT",
                    "/" + index + "/_doc/redirected?op_type=create&refresh=true",
                ),
            }
            if name not in routes:
                self.send_error(404)
                return
            method, path = routes[name]
            connection = http.client.HTTPConnection(backend.hostname, backend.port, timeout=5)
            try:
                connection.request(
                    method, path, body=body or None, headers={"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                raw = response.read(4_000_001)
                assert len(raw) <= 4_000_000
                row.update(
                    backend_forwarded=True,
                    backend_method=method,
                    backend_path=path,
                    backend_status=response.status,
                    backend_body_length=len(raw),
                    backend_body_sha256=hashlib.sha256(raw).hexdigest(),
                    action=name,
                )
                event(row)
                if name in ready:
                    ready[name].set()
                if name == "drop-write":
                    self.close_connection = True
                    return
                if name in {"socket-timeout", "wall-deadline", "delayed-read"}:
                    time.sleep(
                        1.0
                        if name == "wall-deadline"
                        else 0.5
                        if name == "socket-timeout"
                        else 0.25
                    )
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                if name == "short-chunked":
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    fragment = raw[: max(1, len(raw) // 2)]
                    self.wfile.write(hex(len(fragment))[2:].encode() + b"\r\n" + fragment + b"\r\n")
                else:
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(
                        raw[: max(1, len(raw) // 2)] if name == "short-length" else raw
                    )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # Expected after the client-side timeout; the backend event is already durable.
                pass
            finally:
                connection.close()
                self.close_connection = True

    def session(name, base_url, specs):
        plan = [
            {
                "id": sid,
                "api_id": api,
                "method": method,
                "path": path,
                "expected": list(expected),
                "purpose": fixture_purpose,
            }
            for sid, api, method, path, expected in specs
        ]
        return Session(
            output / name,
            base_url=base_url,
            release=config["release"],
            run_id=config["run_id"] + "-" + name,
            provenance={"kind": fixture_purpose, "scenario_plan": {"scenarios": plan}},
        )

    setup_specs = [
        ("identity", "info", "GET", "/", (200,)),
        ("create", "indices.create", "PUT", "/" + index, (200,)),
        ("readable", "index", "PUT", "/" + index + "/_doc/readable?refresh=true", (201,)),
        ("large", "index", "PUT", "/" + index + "/_doc/large?refresh=true", (201,)),
    ]
    fault_specs = [
        (
            name,
            "transport.fixture",
            "PUT"
            if name in {"drop-write", "socket-timeout", "wall-deadline", "redirect"}
            else "GET",
            "/" + name,
            (307,) if name == "redirect" else (201,) if name in ready else (200,),
        )
        for name in [
            "drop-write",
            "socket-timeout",
            "wall-deadline",
            "short-length",
            "short-chunked",
            "delayed-read",
            "response-limit",
            "redirect",
        ]
    ]
    resolution_specs = [
        (name + "-readback", "get", "GET", "/" + index + "/_doc/" + identifier, (200,))
        for name, identifier in [
            ("drop-write", "lost"),
            ("socket-timeout", "socket"),
            ("wall-deadline", "wall"),
        ]
    ] + [
        ("redirect-absent", "get", "GET", "/" + index + "/_doc/redirected", (404,)),
        ("count", "count", "GET", "/" + index + "/_count", (200,)),
        ("cleanup", "indices.delete", "DELETE", "/" + index, (200, 404)),
        ("cleaned", "indices.exists", "HEAD", "/" + index, (404,)),
    ]

    def call(session, specs, name, body=OMITTED, **kwargs):
        spec = next(row for row in specs if row[0] == name)
        result = session.call(
            spec[1], name, spec[2], spec[3], spec[4], body=body, purpose=fixture_purpose, **kwargs
        )
        return result, session.rows[-1]

    def save_case(name, sample_session, sample, checks, resolution=None):
        assertions = [
            {
                "name": label,
                "actual": actual,
                "expected": expected,
                "passed": type(actual) is type(expected) and actual == expected,
            }
            for label, actual, expected in checks
        ]
        row = {
            "schema_version": 1,
            "kind": "controlled-fault-transport-not-rest-coverage",
            "case_id": name,
            "sample": {"session": sample_session, "scenario_id": sample["scenario_id"]},
            "resolution": resolution,
            "assertions": assertions,
            "state": "passed" if all(c["passed"] for c in assertions) else "failed",
        }
        case_rows.append(row)
        print(name, row["state"], flush=True)

    class FaultServer(ThreadingHTTPServer):
        daemon_threads = False

    server = FaultServer(("127.0.0.1", 0), Proxy)
    proxy_url = "http://127.0.0.1:" + str(server.server_address[1])
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    setup = session("setup", config["base_url"], setup_specs)
    samples = session("fault-attempts", proxy_url, fault_specs)
    resolutions = session("resolution", config["base_url"], resolution_specs)
    refused_socket = socket.socket()
    refused_socket.bind(
        ("127.0.0.1", 0)
    )  # Bound but not listening; no other process can claim the port.
    refused_specs = [("connect-refused", "transport.fixture", "GET", "/", (200,))]
    refused = session(
        "refused-attempt", "http://127.0.0.1:" + str(refused_socket.getsockname()[1]), refused_specs
    )
    thread.start()
    try:
        identity, _ = call(
            setup,
            setup_specs,
            "identity",
            assertions=[
                ("actual ES release", lambda d: d["version"]["number"], config["release"]),
                ("owned primary node", lambda d: d["name"], "es-cli-anchor"),
            ],
        )
        if not identity.passed:
            raise RuntimeError("Fault backend identity was not verified")
        for name, body in [
            (
                "create",
                {
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {
                        "properties": {
                            "n": {"type": "integer"},
                            "payload": {"type": "text", "index": False},
                        }
                    },
                },
            ),
            ("readable", {"n": 7}),
            ("large", {"n": 8, "payload": "x" * 2_000_128}),
        ]:
            result, _ = call(setup, setup_specs, name, body)
            if not result.passed:
                raise RuntimeError("Fault fixture setup did not pass: " + name)
        for name, value, error_type, deadline, socket_timeout in [
            ("drop-write", 42, "RemoteDisconnected", 5, 2),
            ("socket-timeout", 43, "TimeoutError", 5, 0.15),
            ("wall-deadline", 44, "wall-deadline", 0.5, 0.5),
        ]:
            _, sample = call(
                samples,
                fault_specs,
                name,
                {"n": value},
                deadline=deadline,
                socket_timeout=socket_timeout,
            )
            if not ready[name].wait(5):
                raise RuntimeError("No durable backend response for " + name)
            readback, _ = call(
                resolutions,
                resolution_specs,
                name + "-readback",
                assertions=[
                    ("actual committed value", lambda d: d["_source"]["n"], value),
                    ("one create, no overwrite", lambda d: d["_version"], 1),
                ],
            )
            matching = [item for item in events if item["path"] == "/" + name]
            save_case(
                name,
                "fault-attempts",
                sample,
                [
                    ("client transport outcome", sample["state"], "infrastructure-error"),
                    (
                        "exact client failure",
                        sample.get("transport_error", {}).get("type"),
                        error_type,
                    ),
                    (
                        "write outcome remains unknown to client",
                        sample.get("write_outcome"),
                        "unknown",
                    ),
                    ("proxy saw exactly one attempt", len(matching), 1),
                    (
                        "backend actually committed",
                        matching[0]["backend_status"] if matching else None,
                        201,
                    ),
                    ("independent ES readback passed", readback.passed, True),
                ],
                {"session": "resolution", "scenario_id": name + "-readback"},
            )
        for name, expected_error in [
            ("short-length", "response-length-mismatch"),
            ("short-chunked", "IncompleteRead"),
            ("response-limit", "response-size-limit"),
        ]:
            _, sample = call(samples, fault_specs, name)
            body = (sample.get("response") or {}).get("body", {})
            matching = [item for item in events if item["path"] == "/" + name]
            save_case(
                name,
                "fault-attempts",
                sample,
                [
                    ("HTTP status was received", (sample.get("response") or {}).get("status"), 200),
                    (
                        "body interruption is explicit",
                        sample.get("transport_error", {}).get("type"),
                        expected_error,
                    ),
                    ("body is not complete", body.get("complete"), False),
                    (
                        "received fragment hash retained",
                        bool(body.get("received_bytes", {}).get("sha256")),
                        True,
                    ),
                    (
                        "backend sent more than client retained",
                        bool(
                            matching and matching[0]["backend_body_length"] > body.get("length", 0)
                        ),
                        True,
                    ),
                    ("no hidden retry", len(matching), 1),
                ],
            )
        result, sample = call(samples, fault_specs, "delayed-read", socket_timeout=2, deadline=4)
        save_case(
            "delayed-read",
            "fault-attempts",
            sample,
            [
                (
                    "delayed real response accepted",
                    result.passed and result.data["_source"]["n"] == 7,
                    True,
                ),
                ("configured delay was visible", sample["elapsed_seconds"] >= 0.25, True),
            ],
        )
        _, sample = call(samples, fault_specs, "redirect", {"n": 45})
        absent, _ = call(
            resolutions,
            resolution_specs,
            "redirect-absent",
            assertions=[("redirect target was not written", lambda d: d["found"], False)],
        )
        save_case(
            "redirect",
            "fault-attempts",
            sample,
            [
                ("redirect returned unchanged", sample["response"]["status"], 307),
                (
                    "no redirect target request",
                    sum(e["path"] == "/redirect-target" for e in events),
                    0,
                ),
                ("no backend write", absent.passed, True),
            ],
            {"session": "resolution", "scenario_id": "redirect-absent"},
        )
        _, sample = call(refused, refused_specs, "connect-refused", socket_timeout=1, deadline=3)
        save_case(
            "connect-refused",
            "refused-attempt",
            sample,
            [
                (
                    "connection refusal is explicit",
                    sample.get("transport_error", {}).get("type"),
                    "ConnectionRefusedError",
                ),
                ("no HTTP response", (sample.get("response") or {}).get("status"), None),
            ],
        )
        total, _ = call(
            resolutions,
            resolution_specs,
            "count",
            assertions=[("only the five intended documents exist", lambda d: d["count"], 5)],
        )
        if not total.passed:
            raise RuntimeError("Unexpected backend document count")
    finally:
        server.shutdown()
        server.server_close()  # Wait for timed-out request handlers before deleting their index.
        thread.join(timeout=3)
        refused_socket.close()
        try:
            call(resolutions, resolution_specs, "cleanup")
            call(resolutions, resolution_specs, "cleaned")
        finally:
            for item in [setup, samples, resolutions, refused]:
                item.close()
            trace_file.close()
        raw = "".join(json.dumps(row) + "\n" for row in case_rows).encode()
        (output / "observations.jsonl").write_bytes(raw)
        manifest = {
            "schema_version": 1,
            "kind": "controlled-fault-transport-not-rest-coverage",
            "release": config["release"],
            "probes": len(case_rows),
            "states": dict(Counter(row["state"] for row in case_rows)),
            "observations_sha256": hashlib.sha256(raw).hexdigest(),
            "proxy_events_sha256": hashlib.sha256(
                (output / "proxy-events.jsonl").read_bytes()
            ).hexdigest(),
            "session_manifests": {
                name: hashlib.sha256((output / name / "manifest.json").read_bytes()).hexdigest()
                for name in ["setup", "fault-attempts", "resolution", "refused-attempt"]
            },
            "listeners_closed": not thread.is_alive(),
            "background_proxy": False,
            "remaining": [
                "installed core/CLI consumers",
                "other exact ES releases/OS",
                "TCP mid-request body loss",
            ],
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    import sys

    run(json.load(sys.stdin))
