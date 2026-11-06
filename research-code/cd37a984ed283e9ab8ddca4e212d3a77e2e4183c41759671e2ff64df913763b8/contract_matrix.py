"""Audit exact method/path and query-presence evidence; never infer API completeness."""

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl

from validate_attempt import review_attempt

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


def evidence_folders(version):
    for outcome in sorted(
        (ROOT / "docs/research/runs" / version).glob("*/attempts/*/driver-outcome.json")
    ):
        driver = json.loads(outcome.read_text())
        if driver["evidence_copied"] and (outcome.parent / "manifest.json").exists():
            yield outcome.parent, driver


def load_route_discrepancies(version, source_commit):
    path = ROOT / "docs/research/source-analysis" / version / "route-discrepancies.json"
    if not path.exists():
        return []
    content = path.read_bytes()
    facts = json.loads(content)
    assert facts["kind"] == "live-verified-wrong-api-routing-not-support"
    assert facts["release"] == version and facts["source_commit"] == source_commit
    sources = json.loads(path.with_name("route-scope-facts.json").read_text())
    assert sources["source_commit"] == source_commit
    handlers = {row["source"]: row for row in sources["handlers"]}
    registered = {row["handler_path"] for row in sources["registration"]["constructors"]}
    result = []
    for record in facts["records"]:
        assert (record["classification"], record["api_id"], record["method"], record["path"]) == (
            "typed-rank-indexer",
            "rank_eval",
            "POST",
            "/{index}/{type}/_rank_eval",
        ), "Unreviewed API routing classification"
        assert record["actual_handler_source"] in registered
        assert (
            handlers[record["actual_handler_source"]]["sha256"] == record["actual_handler_sha256"]
        )
        assert (
            handlers[record["intended_handler_source"]]["sha256"]
            == record["intended_handler_sha256"]
        )
        verification = record["verification"]
        folder = (ROOT / verification["attempt"]).resolve()
        assert folder.is_relative_to(ROOT / "docs/research/runs" / version)
        raw = (folder / "observations.jsonl").read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        assert checksum == verification["observations_sha256"], "Discrepancy raw bytes changed"
        index = json.loads((folder / "evidence-index.json").read_text())
        manifest = json.loads((folder / "manifest.json").read_text())
        provenance = json.loads((folder / "execution-provenance.json").read_text())
        driver = json.loads((folder / "driver-outcome.json").read_text())
        assert index["raw_observations_sha256"] == checksum == manifest["observations_sha256"]
        assert manifest["release"] == version and provenance["source_commit"] == source_commit
        assert driver["exit_code"] == 0 and driver["evidence_copied"]
        rows = [json.loads(line) for line in raw.splitlines()]
        by_id = {row["scenario_id"]: row for row in rows}
        assert len(rows) == len(by_id) and all(row["state"] == "passed" for row in rows)

        def body(name):
            return by_id["rank-eval." + name]["response"]["body"]["data"]

        request = by_id[verification["scenario_id"]]
        assert request["run_id"] == verification["attempt_id"]
        assert request["api_id"] == "rank_eval" and request["request"]["method"] == "POST"
        assert request["response"]["status"] == verification["status"] == 201
        assert (
            request["purpose"] == "route-discrepancy"
            and request["positive_semantic_evidence"] is False
        )
        indexed = request["response"]["body"]["data"]
        assert indexed["_id"] == "_rank_eval" and indexed["_type"] == "fixture"
        assert indexed["result"] == "created" and "quality_level" not in indexed
        assert request["request"]["path"] == "/" + indexed["_index"] + "/fixture/_rank_eval"
        assert body("typed-read")["_source"] == json.loads(request["request"]["body"]["text"])
        assert (
            body("typed-read")["_index"] == indexed["_index"]
            and body("typed-read")["found"] is True
        )
        assert body("count-after")["count"] == 2 and body("typed-count")["count"] == 3
        assert body("typed-refresh")["_shards"]["failed"] == 0
        assert (
            body("typed-delete")["result"] == "deleted"
            and body("typed-restored-count")["count"] == 2
        )
        result.append(
            {
                **record,
                "proof_ref": str(path.relative_to(ROOT)),
                "proof_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return result


def route_observation_state(rows, discrepancy=None):
    if discrepancy is None:
        return http_state(rows)
    proof = discrepancy["verification"]
    assert any(
        row["run_id"] == proof["attempt_id"]
        and row["scenario_id"] == proof["scenario_id"]
        and (row.get("response") or {}).get("status") == 201
        for row in rows
    ), "Discrepancy proof is absent from matrix observations"
    return "misrouted-2xx-observed"


def route_discrepancy(records, api, route):
    matches = [
        record
        for record in records
        if record["api_id"] == api
        and record["method"] == route["method"]
        and record["path"] == route["path"]
    ]
    assert len(matches) <= 1, "Duplicate API routing proof"
    return matches[0] if matches else None


def load_attribution(version, source_commit):
    path = ROOT / "docs/research/source-analysis" / version / "nodes-info-attribution.json"
    if not path.exists():
        return None
    content = path.read_bytes()
    fact = json.loads(content)
    if (
        fact["kind"] != "pinned-nodes-info-logical-route-attribution-not-new-http"
        or fact["release"] != version
        or fact["source_commit"] != source_commit
        or fact["api_id"] != "nodes.info"
    ):
        raise ValueError("Selector attribution source differs")
    source_facts = json.loads((path.parent / "route-scope-facts.json").read_text())
    handlers = {row["source"]: row["sha256"] for row in source_facts["handlers"]}
    if handlers.get(fact["handler"]["path"]) != fact["handler"]["sha256"]:
        raise ValueError("Selector attribution handler bytes differ")
    metric = fact["metric_source"]
    if metric.get("local_source"):
        metric_path = ROOT / metric["local_source"]
        if not metric_path.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError("Metric proof source escapes release directory")
        if hashlib.sha256(metric_path.read_bytes()).hexdigest() != metric["sha256"]:
            raise ValueError("Selector metric source bytes differ")
    allowed = set(metric["allowed_metrics"])
    if not {"jvm", "process"} <= allowed or "_local" in allowed:
        raise ValueError("Unexpected pinned metric membership proof")
    return {
        "source_ref": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(content).hexdigest(),
        "facts": fact,
    }


def attributed_routes(api, method, path, routes, trailing_slash=False, proof=None):
    candidates = best_routes(method, path, routes, trailing_slash)
    if len(candidates) < 2 or not proof or api != proof["facts"]["api_id"]:
        return candidates
    rules = [
        rule
        for rule in proof["facts"]["attributions"]
        if rule["method"] == method and rule["wire_path"] == path
    ]
    if not rules:
        return candidates
    if len(rules) != 1:
        raise ValueError("Conflicting selector attributions")
    selected = [index for index in candidates if routes[index]["path"] == rules[0]["source_path"]]
    if len(selected) != 1:
        raise ValueError("Attribution does not select one existing ambiguous source route")
    return selected


def build(version):
    folder = ROOT / "docs/research/versions" / version
    backlog_path = folder / "contract-backlog.json"
    backlog = json.loads(backlog_path.read_text())
    attempts, calls, effects = [], defaultdict(list), []
    rejected = []
    for source, driver in evidence_folders(version):
        audit = review_attempt(source)
        if audit["rejection"] is not None:
            rejected.append({"path": str(source.relative_to(ROOT)), **audit["rejection"]})
            continue
        summary = audit["summary"]
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
    attribution = load_attribution(version, backlog["source_commit"])
    discrepancies = load_route_discrepancies(version, backlog["source_commit"])
    attributed_calls = []
    for operation in backlog["operations"]:
        api = operation["api_id"]
        routes = operation["required_dimensions"]["method_paths"]
        buckets = [[] for _ in routes]
        trailing = bool(operation.get("path_normalization_evidence"))
        for reference, row in calls[api]:
            wire_path = row["request"]["path"].partition("?")[0]
            matched = attributed_routes(
                api, row["request"]["method"], wire_path, routes, trailing, attribution
            )
            if (
                len(matched) == 1
                and len(best_routes(row["request"]["method"], wire_path, routes, trailing)) > 1
            ):
                attributed_calls.append(
                    {
                        "ref": reference,
                        "api_id": api,
                        "wire_path": wire_path,
                        "source_path": routes[matched[0]]["path"],
                        "proof_sha256": attribution["sha256"],
                    }
                )
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
            discrepancy = route_discrepancy(discrepancies, api, route)
            state = route_observation_state(records, discrepancy)
            aggregate[state] += 1
            by_scope[operation["scope"]][state] += 1
            method_rows.append(
                {
                    **route,
                    "http_observation": state,
                    **({"route_discrepancy": discrepancy} if discrepancy else {}),
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
        "rejected_attempts_not_counted": rejected,
        "unassigned_calls": unmatched,
        "route_attribution_proof": attribution,
        "route_discrepancy_proofs": discrepancies,
        "source_attributed_calls": attributed_calls,
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
    current, expected_rejections = [], []
    for folder, _ in evidence_folders(version):
        audit = review_attempt(folder)
        if audit["rejection"] is not None:
            expected_rejections.append(
                {"path": str(folder.relative_to(ROOT)), **audit["rejection"]}
            )
        else:
            current.append(str((folder / "observations.jsonl").relative_to(ROOT)))
    assert matrix.get("rejected_attempts_not_counted", []) == expected_rejections
    assert [attempt["source"] for attempt in matrix["attempts"]] == current, (
        "Matrix does not include the current indexed attempt set"
    )
    attribution = load_attribution(version, backlog["source_commit"])
    discrepancies = load_route_discrepancies(version, backlog["source_commit"])
    assert matrix.get("route_attribution_proof") == attribution
    assert matrix.get("route_discrepancy_proofs", []) == discrepancies
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
            {name: row[name] for name in ["method", "path", "deprecated"] if name in row}
            for row in operation["method_paths"]
        ] == routes
        for number, route in enumerate(operation["method_paths"]):
            rows = []
            for reference in route["evidence_refs"]:
                row = resolve(reference)
                assert row["api_id"] == operation["api_id"]
                assert attributed_routes(
                    operation["api_id"],
                    row["request"]["method"],
                    row["request"]["path"].partition("?")[0],
                    routes,
                    bool(source.get("path_normalization_evidence")),
                    attribution,
                ) == [number]
                rows.append(row)
            discrepancy = route_discrepancy(discrepancies, operation["api_id"], route)
            assert route.get("route_discrepancy") == discrepancy
            assert route_observation_state(rows, discrepancy) == route["http_observation"]
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
