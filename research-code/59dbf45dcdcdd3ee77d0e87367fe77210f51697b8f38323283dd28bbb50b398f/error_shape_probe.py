"""Bounded explicitly admitted public error format comparison; no SDK or cluster writes."""

import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def request(base, method, path, media, body):
    config = {
        "url": base + path,
        "method": method,
        "headers": {"Accept": media, "Content-Type": media},
        "body_b64": base64.b64encode(body).decode() if body is not None else None,
        "socket_timeout": 5,
        "max_response_bytes": 65536,
    }
    started = time.monotonic()
    child = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("http_attempt.py"))],
        input=json.dumps(config), capture_output=True, text=True, timeout=8, check=True,
    )
    response = json.loads(child.stdout)
    raw = base64.b64decode(response.pop("body_b64") or "")
    return {
        "method": method, "path": path, "requested_media": media,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        **response, "body_sha256": hashlib.sha256(raw).hexdigest(),
        "body_length": len(raw), "body_excerpt": raw[:16384].decode("utf-8", errors="replace"),
        "excerpt_complete": len(raw) <= 16384,
    }


def run(config):
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=False)
    rows = []

    def record(row):
        rows.append(row)
        (out / "observations.json").write_text(json.dumps(rows, indent=2) + "\n")
        return row

    for number in range(40):
        row = record({"phase": "readiness", "number": number, **request(
            config["reduced_base"], "GET", "/", "application/json", None
        )})
        if row["status"] == 200 and row["body_complete"]:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Reduced-detail exact node did not become ready")

    for detail, base in [(True, config["default_base"]), (False, config["reduced_base"])]:
        for compatibility in [False, True]:
            media = "application/vnd.elasticsearch+json;compatible-with=8" if compatibility else "application/json"
            for name, method, path, body in [
                ("root", "GET", "/", None),
                ("malformed", "POST", "/_rank_eval", b"{"),
                ("invalid-source-media", "GET", "/_rank_eval?source=%7B%7D&source_content_type=application%2Fx-es-cli-invalid", None),
            ]:
                row = record({
                    "phase": "selected", "detailed_errors": detail,
                    "v8_compatibility": compatibility, "case": name,
                    **request(base, method, path, media, body),
                })
                assert row["body_complete"] and row["excerpt_complete"], row
                headers = {k.lower(): v for k, v in row["headers"].items()}
                assert headers.get("x-elastic-product") == ["Elasticsearch"], row
                actual_media = headers.get("content-type", [""])[0]
                assert "json" in actual_media, row
                if compatibility:
                    assert "compatible-with=8" in actual_media, row
                else:
                    assert actual_media.split(";")[0] == "application/json", row
                value = json.loads(row["body_excerpt"])
                assert row["status"] == (200 if name == "root" else 400), row
                if name == "root":
                    assert value["version"]["number"] == config["release"], row
                    continue
                error = value["error"]
                if detail:
                    assert isinstance(error, dict) and isinstance(error["root_cause"], list), row
                elif compatibility or config["release"] == "8.19.24":
                    assert isinstance(error, str), row
                    assert any("http_detailed_errors" in x or "non-detailed errors" in x for x in headers.get("warning", [])), row
                else:
                    assert isinstance(error, dict) and set(error) == {"type", "reason"}, row
                if name == "invalid-source-media" and isinstance(error, dict):
                    assert error["type"] == "validation_exception", row
                    assert error["reason"] == "Validation Failed: 1: Unknown value for source_content_type [application/x-es-cli-invalid];", row
    summary = {
        "release": config["release"], "v8_media_role": "current" if config["release"] == "8.19.24" else "compatibility",
        "selected_http": sum(x["phase"] == "selected" for x in rows),
        "readiness_attempts": sum(x["phase"] == "readiness" for x in rows),
        "status": "selected-assertions-passed",
        "limitations": ["Two public error cases only; no API completeness, old-release, auth, TLS or consumer claim."],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    run(json.load(sys.stdin))
