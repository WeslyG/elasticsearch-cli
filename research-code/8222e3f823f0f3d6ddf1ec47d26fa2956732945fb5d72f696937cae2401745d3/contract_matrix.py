"""Audit exact method/path and query-presence evidence; never infer API completeness."""

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl

from validate_attempt import validate

ROOT = Path(__file__).resolve().parents[2]


def route_pattern(template, trailing_slash=False):
    template = "/" + template.lstrip("/")
    if trailing_slash:
        template = template.rstrip("/") or "/"
    pieces = re.split(r"(\{[^{}]+\})", template)
    pattern = "".join(
        "[^/]+" if piece.startswith("{") and piece.endswith("}") else re.escape(piece)
        for piece in pieces
    )
    if trailing_slash and template != "/":
        pattern += "/?"
    return pattern


def best_routes(method, path, routes, trailing_slash=False):
    candidates = []
    for number, route in enumerate(routes):
        if route["method"] != method:
            continue
        if re.fullmatch(route_pattern(route["path"], trailing_slash), path):
            score = len(re.sub(r"\{[^{}]+\}", "", route["path"]))
            candidates.append((score, number))
    if not candidates:
        return []
    maximum = max(score for score, _ in candidates)
    return [number for score, number in candidates if score == maximum]


def media_mode(row):
    headers = (row.get("request") or {}).get("headers", {})
    if any(
        "compatible-with=" in str(value).lower()
        for name, value in headers.items()
        if name.lower() in {"accept", "content-type"}
    ):
        return "explicit-compatibility-media"
    return "default-media"


def http_state(records):
    successful_media = {
        media_mode(row)
        for row in records
        if 200 <= ((row.get("response") or {}).get("status") or 0) < 300
    }
    if "default-media" in successful_media:
        return "default-media-2xx-observed"
    if successful_media:
        return "compatibility-media-only-2xx-observed"
    if any((row.get("response") or {}).get("status") is not None for row in records):
        return "non-2xx-only-observed"
    return "transport-failure-only" if records else "not-observed"


def sample(value):
    data = value.encode()
    if len(data) <= 160:
        return value
    return {
        "excerpt": value[:80],
        "utf8_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build(version):
    folder = ROOT / "docs/research/versions" / version
    backlog_path = folder / "contract-backlog.json"
    backlog = json.loads(backlog_path.read_text())
    attempts, calls, effects = [], defaultdict(list), []
    for outcome in sorted(
        (ROOT / "docs/research/runs" / version).glob("*/attempts/*/driver-outcome.json")
    ):
        source = outcome.parent
        driver = json.loads(outcome.read_text())
        if not driver["evidence_copied"] or not (source / "manifest.json").exists():
            continue
        summary = validate(source)
        rows = [
            json.loads(line) for line in (source / "observations.jsonl").read_text().splitlines()
        ]
        number = len(attempts)
        attempts.append(
            {
                "source": str((source / "observations.jsonl").relative_to(ROOT)),
                "sha256": summary["raw_observations_sha256"],
                "rows": len(rows),
                "driver_exit_code": driver["exit_code"],
                "note": "HTTP observations do not imply that this whole driver attempt completed.",
            }
        )
        by_id = {row["scenario_id"]: (index, row) for index, row in enumerate(rows)}
        for index, row in enumerate(rows):
            reference = str(number) + ":" + str(index)
            if row["request"] is not None:
                calls[row["api_id"]].append((reference, row))
            if row["state"] == "passed":
                for identifier in row.get("verifies", []):
                    if identifier in by_id:
                        action_index, action = by_id[identifier]
                        effects.append(
                            {
                                "action_ref": str(number) + ":" + str(action_index),
                                "check_ref": reference,
                                "action_api": action["api_id"],
                                "action_state": action["state"],
                                "check_evidence_depth": row["evidence_depth"],
                                "check_status": (row.get("response") or {}).get("status"),
                                "non_status_assertions": [
                                    check["name"]
                                    for check in row["assertions"]
                                    if check["name"] != "http-status"
                                ],
                                "note": "Explicit recipe link, not automatic semantic completeness.",
                            }
                        )
    operations, unmatched = [], []
    aggregate = Counter()
    by_scope = defaultdict(Counter)
    for operation in backlog["operations"]:
        api = operation["api_id"]
        routes = operation["required_dimensions"]["method_paths"]
        buckets = [[] for _ in routes]
        trailing = bool(operation.get("path_normalization_evidence"))
        for reference, row in calls[api]:
            wire_path = row["request"]["path"].partition("?")[0]
            matched = best_routes(row["request"]["method"], wire_path, routes, trailing)
            if len(matched) == 1:
                buckets[matched[0]].append((reference, row))
            else:
                unmatched.append(
                    {
                        "ref": reference,
                        "api_id": api,
                        "method": row["request"]["method"],
                        "wire_path": wire_path,
                        "reason": "equally-specific source route ambiguity"
                        if matched
                        else "no exact source route",
                        "candidate_route_indexes": matched,
                    }
                )
        method_rows = []
        for route, entries in zip(routes, buckets):
            records = [row for _, row in entries]
            state = http_state(records)
            aggregate[state] += 1
            by_scope[operation["scope"]][state] += 1
            method_rows.append(
                {
                    **route,
                    "http_observation": state,
                    "evidence_refs": [ref for ref, _ in entries],
                    "http_status_counts": dict(
                        Counter(str((row.get("response") or {}).get("status")) for row in records)
                    ),
                    "expectation_states": dict(Counter(row["state"] for row in records)),
                    "semantic_completeness": "not-established",
                }
            )
        declared = set(operation["required_dimensions"]["query_params"])
        observed_names = {
            name
            for _, row in calls[api]
            for name, _ in parse_qsl(
                row["request"]["path"].partition("?")[2], keep_blank_values=True
            )
        }
        query_rows = []
        for name in sorted(declared | observed_names):
            groups = {}
            present = 0
            for reference, row in calls[api]:
                values = [
                    value
                    for key, value in parse_qsl(
                        row["request"]["path"].partition("?")[2], keep_blank_values=True
                    )
                    if key == name
                ]
                if not values:
                    continue
                present += 1
                status = (row.get("response") or {}).get("status")
                key = json.dumps([values, status, row["state"], media_mode(row)])
                group = groups.setdefault(
                    key,
                    {
                        "decoded_wire_values": [sample(value) for value in values],
                        "status": status,
                        "expectation_state": row["state"],
                        "media": media_mode(row),
                        "evidence_refs": [],
                    },
                )
                group["evidence_refs"].append(reference)
            query_rows.append(
                {
                    "name": name,
                    "declared_in_source": name in declared,
                    "present_requests": present,
                    "omitted_requests": len(calls[api]) - present,
                    "observations": list(groups.values()),
                    "semantic_status": "presence-and-responses-only; values/defaults/effects require review",
                }
            )
        operations.append(
            {
                "api_id": api,
                "scope": operation["scope"],
                "method_paths": method_rows,
                "query_parameters": query_rows,
                "independent_check_links": [item for item in effects if item["action_api"] == api],
                "complete": False,
            }
        )
    known_apis = {operation["api_id"] for operation in backlog["operations"]}
    for api in set(calls) - known_apis:
        for reference, row in calls[api]:
            unmatched.append(
                {
                    "ref": reference,
                    "api_id": api,
                    "method": row["request"]["method"],
                    "wire_path": row["request"]["path"].partition("?")[0],
                    "reason": "API ID absent from current source backlog",
                    "candidate_route_indexes": [],
                }
            )
    result = {
        "schema_version": 1,
        "kind": "observational-contract-matrix-not-support",
        "release": version,
        "source_commit": backlog["source_commit"],
        "backlog_sha256": hashlib.sha256(backlog_path.read_bytes()).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generator_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "attempts": attempts,
        "method_path_observation_counts": dict(aggregate),
        "method_path_observation_counts_by_scope": {
            scope: dict(counts) for scope, counts in by_scope.items()
        },
        "operations": operations,
        "unassigned_calls": unmatched,
        "complete_api_coverage": False,
        "limitations": [
            "Only independently indexed v2 observations; historical v1 remains separate.",
            "An HTTP 2xx observation can be an application-level refusal or a failed expectation.",
            "Only the most specific exact source route receives a request; ties stay unassigned.",
            "Compatibility media are separated from default media; no support is inferred.",
            "Query appearance, omitted values and linked recipe assertions do not establish semantics or defaults.",
            "Body/header/error/async/state/platform obligations remain open; no overall coverage percentage.",
        ],
    }
    (folder / "contract-matrix.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    lines = [
        f"# {version}: observed method/path obligations",
        "",
        "Derived only from indexed v2 raw HTTP attempts. No API is complete.",
        "2xx means an HTTP observation, including possible application refusals.",
        "",
        "| Observation category | Source method/path obligations |",
        "| --- | ---: |",
    ]
    lines += [f"| {name} | {count} |" for name, count in sorted(aggregate.items())]
    lines += [
        "",
        "Counts above include all source scopes, including excluded APIs. They are not a product denominator.",
        "",
        "| Scope | HTTP observation category | Obligations |",
        "| --- | --- | ---: |",
    ]
    for scope, counts in sorted(by_scope.items()):
        lines += [f"| {scope} | {state} | {count} |" for state, count in sorted(counts.items())]
    lines += [
        "",
        f"Unassigned actual requests: {len(unmatched)} (ambiguity or source mismatch retained).",
        "",
        "See [contract-matrix.json](contract-matrix.json) for exact method/path/query rows and raw references.",
        "A ref A:R selects zero-based attempt A then raw JSONL row R. Query semantics and defaults remain review obligations.",
        "",
    ]
    (folder / "contract-matrix.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {"release": version, "method_paths": dict(aggregate), "unassigned": len(unmatched)}
        )
    )


def validate_inputs(matrix):
    """Verify saved matrix references against actual source and raw bytes."""
    version = matrix["release"]
    backlog_path = ROOT / "docs/research/versions" / version / "contract-backlog.json"
    assert hashlib.sha256(backlog_path.read_bytes()).hexdigest() == matrix["backlog_sha256"]
    backlog = json.loads(backlog_path.read_text())
    assert backlog["source_commit"] == matrix["source_commit"]
    original_code = subprocess.check_output(
        ["git", "show", matrix["generator_git_sha"] + ":tools/research/contract_matrix.py"],
        cwd=ROOT,
    )
    assert hashlib.sha256(original_code).hexdigest() == matrix["generator_sha256"]
    attempts = []
    for attempt in matrix["attempts"]:
        source = (ROOT / attempt["source"]).resolve()
        assert source.is_relative_to(ROOT / "docs/research/runs" / version)
        content = source.read_bytes()
        assert hashlib.sha256(content).hexdigest() == attempt["sha256"]
        rows = [json.loads(line) for line in content.splitlines()]
        assert len(rows) == attempt["rows"]
        attempts.append(rows)

    def resolve(reference):
        attempt, row = map(int, reference.split(":"))
        assert attempt >= 0 and row >= 0
        return attempts[attempt][row]

    catalog = {operation["api_id"]: operation for operation in backlog["operations"]}
    assert {operation["api_id"] for operation in matrix["operations"]} == set(catalog)
    totals = Counter()
    grouped = defaultdict(Counter)
    for operation in matrix["operations"]:
        source = catalog[operation["api_id"]]
        assert operation["scope"] == source["scope"] and operation["complete"] is False
        routes = source["required_dimensions"]["method_paths"]
        assert [
            {name: row[name] for name in ["method", "path"]} for row in operation["method_paths"]
        ] == routes
        for number, route in enumerate(operation["method_paths"]):
            rows = []
            for reference in route["evidence_refs"]:
                row = resolve(reference)
                assert row["api_id"] == operation["api_id"]
                assert best_routes(
                    row["request"]["method"],
                    row["request"]["path"].partition("?")[0],
                    routes,
                    bool(source.get("path_normalization_evidence")),
                ) == [number]
                rows.append(row)
            assert http_state(rows) == route["http_observation"]
            totals[route["http_observation"]] += 1
            grouped[operation["scope"]][route["http_observation"]] += 1
        for parameter in operation["query_parameters"]:
            for observed in parameter["observations"]:
                for reference in observed["evidence_refs"]:
                    row = resolve(reference)
                    assert row["api_id"] == operation["api_id"]
                    values = [
                        sample(value)
                        for name, value in parse_qsl(
                            row["request"]["path"].partition("?")[2], keep_blank_values=True
                        )
                        if name == parameter["name"]
                    ]
                    assert values == observed["decoded_wire_values"]
                    assert (row.get("response") or {}).get("status") == observed["status"]
                    assert row["state"] == observed["expectation_state"]
                    assert media_mode(row) == observed["media"]
    assert dict(totals) == matrix["method_path_observation_counts"]
    assert {scope: dict(counts) for scope, counts in grouped.items()} == matrix[
        "method_path_observation_counts_by_scope"
    ]
    assert matrix["complete_api_coverage"] is False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("versions", nargs="+")
    args = parser.parse_args()
    for version in args.versions:
        build(version)


if __name__ == "__main__":
    main()
