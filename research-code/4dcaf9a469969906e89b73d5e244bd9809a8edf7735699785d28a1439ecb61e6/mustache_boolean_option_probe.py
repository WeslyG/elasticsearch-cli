"""Six exact literal script-option gate probes; no index or data writes."""

import json
import sys
from pathlib import Path

from error_shape_probe import request


def run(config):
    version = config["release"]
    if version not in {"9.2.8", "9.3.8"}:
        raise ValueError("Only exact source-reviewed boolean boundary releases")
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=False)
    prefix = config["index_prefix"]
    if not prefix.startswith("es-cli-template-option-"):
        raise ValueError("Owned empty wildcard prefix required")
    path = "/" + prefix + "*/_rank_eval?ignore_unavailable=true&allow_no_indices=true"
    rows = []
    for name, option in [
        ("omitted", None),
        ("content-type-control", "application/json"),
        ("true", "true"),
        ("false", "false"),
        ("uppercase", "TRUE"),
        ("invalid", "not-a-bool"),
    ]:
        script = {"lang": "mustache", "source": '{"query":{"term":{"tag":"{{tag}}"}}}'}
        if name == "content-type-control":
            script["options"] = {"content_type": option}
        elif option is not None:
            script["options"] = {"detect_missing_params": option}
        body = {
            "requests": [
                {"id": "q", "template_id": "t", "params": {"tag": "known"}, "ratings": []}
            ],
            "templates": [{"id": "t", "template": script}],
            "metric": {"precision": {"k": 1}},
        }
        expected = 200 if name in {"omitted", "content-type-control"} else 400
        row = {
            "case": name,
            "option_value": option,
            "request_body": body,
            "expected_status": expected,
            **request(config["base"], "POST", path, "application/json", json.dumps(body).encode()),
        }
        rows.append(row)
        (out / "observations.json").write_text(json.dumps(rows, indent=2) + "\n")
        assert row["body_complete"] and row["excerpt_complete"] and row["status"] == expected, row
        value = json.loads(row["body_excerpt"])
        if expected == 200:
            assert (
                value["metric_score"] == 0
                and value["details"]["q"]["hits"] == []
                and value["failures"] == {}
            ), row
        else:
            assert (
                value["error"]["type"] == "x_content_parse_exception"
                and "metric_score" not in value
            ), row
            cause = value["error"]
            while isinstance(cause.get("caused_by"), dict):
                cause = cause["caused_by"]
            assert cause["type"] == "illegal_argument_exception", row
            assert (
                cause["reason"]
                == "illegal compiler options [{detect_missing_params=" + option + "}] specified"
            ), row
        print(name, row["status"], flush=True)
    (out / "summary.json").write_text(
        json.dumps(
            {
                "release": version,
                "status": "selected-assertions-passed",
                "actual_http_responses": len(rows),
                "data_mutations": 0,
                "limitations": [
                    "Two allowed controls and four rejected option literals. Internal boolean conversion and missing-variable behavior are not exercised."
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    run(json.load(sys.stdin))
