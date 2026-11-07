"""Five exact literal boolean-option probes; no index or data writes."""

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
        ("true", "true"),
        ("false", "false"),
        ("uppercase", "TRUE"),
        ("invalid", "not-a-bool"),
    ]:
        script = {"lang": "mustache", "source": '{"query":{"term":{"tag":"{{tag}}"}}}'}
        if option is not None:
            script["options"] = {"detect_missing_params": option}
        body = {
            "requests": [
                {"id": "q", "template_id": "t", "params": {"tag": "known"}, "ratings": []}
            ],
            "templates": [{"id": "t", "template": script}],
            "metric": {"precision": {"k": 1}},
        }
        expected = 400 if version == "9.3.8" and name in {"uppercase", "invalid"} else 200
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
            assert isinstance(value["error"], dict) and "metric_score" not in value, row
        print(name, row["status"], flush=True)
    (out / "summary.json").write_text(
        json.dumps(
            {
                "release": version,
                "status": "selected-assertions-passed",
                "actual_http_responses": 5,
                "data_mutations": 0,
                "limitations": [
                    "Five literal option values only; not missing-variable behavior, render API or all boolean consumers."
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    run(json.load(sys.stdin))
