"""Research-only evidence v2 runner with explicit IDs and real dependency blocking."""

import base64
import hashlib
import json
import os
import platform
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

OMITTED = object()
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def json_equal(actual, expected):
    """Compare JSON values without Python's True == 1 coercion."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            json_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            json_equal(left, right) for left, right in zip(actual, expected)
        )
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


@dataclass
class Observation:
    scenario_id: str
    state: str
    status: int | None
    data: object

    @property
    def passed(self):
        return self.state == "passed"


class Session:
    def __init__(self, output, *, base_url, release, run_id, tls=None, provenance=None):
        self.output = Path(output)
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Explicit HTTP(S) base URL without credentials/query/fragment required"
            )
        self.base_url = base_url.rstrip("/")
        self.release, self.run_id = release, run_id
        self.tls = tls or {}
        self.provenance = provenance or {}
        self.runtime = {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "openssl": ssl.OPENSSL_VERSION,
        }
        self.rows = []
        self.outcomes = {}
        self.output.mkdir(parents=True, exist_ok=False)
        self.stream = (self.output / "observations.jsonl").open("x")
        self.closed = False

    def _save(self, record):
        self.rows.append(record)
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def _base(self, api_id, scenario_id, dimensions, depends_on):
        if self.closed:
            raise ValueError("Session already closed")
        if not api_id or not scenario_id or scenario_id in self.outcomes:
            raise ValueError("Explicit API ID and unique scenario ID required")
        if any(dependency not in self.outcomes for dependency in depends_on):
            raise ValueError("Unknown prerequisite in " + scenario_id)
        return {
            "schema_version": 2,
            "run_id": self.run_id,
            "release": self.release,
            "api_id": api_id,
            "scenario_id": scenario_id,
            "dimensions": dimensions,
            "depends_on": depends_on,
            "evidence_kind": "direct-http-research-not-core-or-cli",
            "assertions": [],
            "response": None,
            "request": None,
        }

    def call(
        self,
        api_id,
        scenario_id,
        method,
        path,
        expected_status,
        *,
        body=OMITTED,
        content_type="application/json",
        assertions=(),
        dimensions=(),
        depends_on=(),
        deadline=20,
        socket_timeout=None,
        headers=None,
        semantic=False,
        verifies=(),
        purpose="api-contract",
    ):
        expected_codes = (
            (expected_status,) if isinstance(expected_status, int) else tuple(expected_status)
        )
        if not expected_codes or any(
            not isinstance(code, int) or code < 100 or code > 599 for code in expected_codes
        ):
            raise ValueError("Explicit HTTP status code(s) required")
        dependencies = list(depends_on)
        record = self._base(api_id, scenario_id, list(dimensions), dependencies)
        if any(name not in self.outcomes for name in verifies):
            raise ValueError("Unknown verified action")
        record["verifies"] = list(verifies)
        record["purpose"] = purpose
        blockers = [name for name in dependencies if not self.outcomes[name].passed]
        if blockers:
            record.update(
                state="blocked",
                blocked_by=blockers,
                elapsed_seconds=0,
                evidence_depth="none",
                reason="Prerequisite did not pass; HTTP not executed",
            )
            outcome = Observation(scenario_id, "blocked", None, None)
            self.outcomes[scenario_id] = outcome
            self._save(record)
            return outcome
        if not path.startswith("/") or deadline <= 0 or deadline > 120:
            raise ValueError("Absolute request path and bounded 0 < deadline <= 120 required")
        if body is OMITTED:
            payload = None
        elif isinstance(body, bytes):
            payload = body
        else:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        request_headers = dict(headers or {})
        request_headers.setdefault("Content-Type", content_type)
        # Header values may contain credentials; only a strict safe subset is retained.
        safe_headers = {
            key: value if key.lower() in {"content-type", "accept"} else "[redacted]"
            for key, value in request_headers.items()
        }
        body_info = {
            "presence": "omitted" if payload is None else "present",
            "length": None if payload is None else len(payload),
            "sha256": None if payload is None else hashlib.sha256(payload).hexdigest(),
            "text": None if payload is None else payload[:16000].decode("utf-8", errors="replace"),
            "truncated": payload is not None and len(payload) > 16000,
            "base64": base64.b64encode(payload).decode()
            if payload is not None and len(payload) <= 16000
            else None,
        }
        record["request"] = {
            "method": method,
            "path": path,
            "headers": safe_headers,
            "body": body_info,
        }
        socket_timeout = min(deadline, 10) if socket_timeout is None else socket_timeout
        if socket_timeout <= 0 or socket_timeout > deadline:
            raise ValueError("Socket timeout must be positive and within hard deadline")
        record["timeouts"] = {"socket_seconds": socket_timeout, "deadline_seconds": deadline}
        config = {
            "url": self.base_url + path,
            "method": method,
            "headers": request_headers,
            "body_b64": None if payload is None else base64.b64encode(payload).decode(),
            "socket_timeout": socket_timeout,
            "max_response_bytes": 2_000_000,
            "tls": self.tls,
        }
        started = time.monotonic()
        data, status = None, None
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("http_attempt.py"))],
                input=json.dumps(config),
                capture_output=True,
                text=True,
                timeout=deadline,
                check=True,
            )
            wire = json.loads(result.stdout)
            status = wire["status"]
            raw = base64.b64decode(wire["body_b64"]) if wire.get("body_b64") is not None else None
            if raw is not None:
                media_type = wire["headers"].get("Content-Type", [""])[0].split(";", 1)[0].lower()
                if media_type == "application/json" or media_type.endswith("+json"):
                    try:
                        data = json.loads(raw) if raw else None
                    except (ValueError, UnicodeError):
                        data = raw.decode("utf-8", errors="replace")
                else:
                    data = raw.decode("utf-8", errors="replace") if raw else None
            response_body = {
                "length": None if raw is None else len(raw),
                "sha256": None
                if raw is None or not wire["body_complete"]
                else hashlib.sha256(raw).hexdigest(),
                "complete": wire["body_complete"],
                "excerpt_truncated": raw is not None and len(raw) > 16000,
                "data": data if raw is not None and len(raw) <= 16000 else None,
                "base64": base64.b64encode(raw).decode()
                if raw is not None and len(raw) <= 16000 and wire["body_complete"]
                else None,
                "text_excerpt": raw[:16000].decode("utf-8", errors="replace") if raw else None,
            }
            if raw is not None and not wire["body_complete"]:
                # Hash/bytes describe only the received fragment, never the missing full body.
                response_body["received_bytes"] = {
                    "length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "base64": base64.b64encode(raw).decode() if len(raw) <= 16000 else None,
                }
            record["response"] = {
                "status": status,
                "headers": wire["headers"],
                "body": response_body,
            }
            if wire.get("error"):
                record.update(
                    state="infrastructure-error",
                    transport_error=wire["error"],
                    evidence_depth="response-observed" if status else "none",
                )
            else:
                checks = [
                    {
                        "name": "http-status",
                        "expected": expected_codes[0]
                        if len(expected_codes) == 1
                        else list(expected_codes),
                        "actual": status,
                        "passed": status in expected_codes,
                    }
                ]
                if status in expected_codes:
                    for label, extract, expected in assertions:
                        try:
                            actual = extract(data)
                            check = {
                                "name": label,
                                "expected": expected,
                                "actual": actual,
                                "passed": json_equal(actual, expected),
                            }
                        except Exception as error:
                            check = {
                                "name": label,
                                "expected": expected,
                                "actual": None,
                                "passed": False,
                                "error": type(error).__name__ + ": " + str(error)[:1000],
                            }
                        checks.append(check)
                record["assertions"] = checks
                record["state"] = "passed" if all(check["passed"] for check in checks) else "failed"
                record["evidence_depth"] = (
                    "semantic-verified"
                    if record["state"] == "passed" and assertions and semantic
                    else "response-observed"
                )
                record["positive_http_observation"] = (
                    record["state"] == "passed" and 200 <= status < 300
                )
                record["positive_semantic_evidence"] = (
                    record["positive_http_observation"]
                    and record["evidence_depth"] == "semantic-verified"
                )
        except subprocess.TimeoutExpired:
            record.update(
                state="infrastructure-error",
                transport_error={"type": "wall-deadline", "phase": "unknown-worker-phase"},
                evidence_depth="none",
            )
        except Exception as error:
            record.update(
                state="infrastructure-error",
                transport_error={
                    "type": type(error).__name__,
                    "message": str(error)[:1000],
                    "phase": "worker-execution",
                },
                evidence_depth="none",
            )
        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
        if record["state"] == "infrastructure-error" and method in WRITE_METHODS:
            record["write_outcome"] = "unknown"
        outcome = Observation(scenario_id, record["state"], status, data)
        self.outcomes[scenario_id] = outcome
        self._save(record)
        return outcome

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stream.close()
        manifest = {
            "schema_version": 2,
            "run_id": self.run_id,
            "release": self.release,
            "kind": "research-run-not-client-support",
            "provenance": self.provenance,
            "runtime": self.runtime,
            "states": {
                state: sum(row["state"] == state for row in self.rows)
                for state in sorted({row["state"] for row in self.rows})
            },
            "observations": len(self.rows),
            "observations_sha256": hashlib.sha256(
                (self.output / "observations.jsonl").read_bytes()
            ).hexdigest(),
            "auxiliary_evidence_sha256": {
                name: hashlib.sha256((self.output / name).read_bytes()).hexdigest()
                for name in ["fs-garbage-fixture.json", "node-control.json"]
                if (self.output / name).exists()
            },
            "remaining": [
                "catalog reconciliation",
                "method/path/parameter completeness",
                "native TLS/auth/fault matrix",
                "installed core/CLI consumers",
            ],
        }
        (self.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
