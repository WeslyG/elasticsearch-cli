"""Classify source evidence conservatively and build a dimension backlog."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from compare_sources import operations
from handler_route_extensions import load_route_extensions
from inventory import ROOT
from legacy_scope_docs import PREPARED_DOC_RELEASES
from source_catalog import effective_inventory

VERSIONS = ROOT / "docs/research/versions"


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def normalized(path, *, trailing_slash=False):
    value = re.sub(r"\{[^}]+\}", "{}", "/" + path.lstrip("/"))
    return (value.rstrip("/") or "/") if trailing_slash else value


def location(source):
    if source.startswith("x-pack/"):
        return "excluded-xpack"
    if source.startswith(("server/", "core/")):
        return "server"
    if source.startswith("modules/"):
        return "official-module"
    if source.startswith("plugins/"):
        return "official-plugin"
    return "unknown"


def classify_scope(api, definition, visibility, routes, duplicate=False):
    kinds = {location(p) for route in routes for p in route["handler_sources"]}
    if definition["source"].startswith(("plugins/examples/", "plugins/jvm-example/")):
        scope, basis = "example-metadata", "test-only spec path"
    elif visibility == "private" or api.startswith("_internal."):
        scope, basis = "private", "upstream visibility or explicit internal API namespace"
    elif definition["scope"] == "excluded-xpack":
        scope, basis = "excluded-xpack", "pinned spec located under x-pack"
    elif (
        routes and all(route["handler_sources"] for route in routes) and kinds == {"excluded-xpack"}
    ):
        scope, basis = "excluded-xpack", "all matched routes implemented only under x-pack"
    elif (
        visibility == "public"
        and routes
        and all(route["registered_core_sources"] for route in routes)
        and kinds <= {"server"}
    ):
        scope, basis = (
            "public-core-source",
            "public definition + literal server handler + ActionModule registration",
        )
    elif (
        visibility == "public"
        and routes
        and all(route["handler_sources"] for route in routes)
        and kinds == {"official-module"}
    ):
        scope, basis = (
            "public-module-candidate",
            "public definition + literal module routes; registration/runtime pending",
        )
    elif (
        routes
        and all(route["handler_sources"] for route in routes)
        and kinds == {"official-plugin"}
    ):
        scope, basis = (
            "official-plugin-candidate",
            "literal plugin source; runtime availability pending",
        )
    else:
        scope, basis = "unknown", "insufficient or mixed evidence; requires manual classification"
    if duplicate:
        scope, basis = "unknown", "duplicate API ID definitions require explicit reconciliation"
    return scope, basis


def validate_normalization_sources(version, proof):
    sources = proof.get("sources", [])
    if len(sources) != 2 or {Path(row["source"]).name for row in sources} != {
        "RestController.java",
        "PathTrie.java",
    }:
        raise ValueError("Trailing slash proof requires exact controller/trie sources")
    allowed = (ROOT / "docs/research/source-analysis" / version).resolve()
    for row in sources:
        local = (ROOT / row["local_source"]).resolve()
        if (
            not local.is_relative_to(allowed)
            or local.stat().st_size > 2_000_000
            or hashlib.sha256(local.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise ValueError("Path normalization proof differs from retained exact source")


def legacy_public_review(api, visibility, routes, review, documentation, module_review=None):
    core_ids = review.get("approved_public_api_ids", [])
    module_ids = review.get("approved_public_module_api_ids", [])
    if api not in core_ids + module_ids:
        return False
    if visibility != "unknown":
        raise ValueError("Legacy review cannot replace explicit upstream visibility")
    matches = [row for row in documentation["operations"] if row["api_id"] == api]
    if len(matches) != 1 or not matches[0]["pinned_anchor_matches"]:
        raise ValueError("Reviewed API lacks pinned documentation evidence: " + api)
    if api in core_ids:
        core_root = review.get("core_source_root", "core")
        if core_root not in {"core", "server"}:
            raise ValueError("Legacy core root must match actual core/server source")
        if not routes or any(
            not route["registered_core_sources"]
            or not route["handler_sources"]
            or any(not source.startswith(core_root + "/") for source in route["handler_sources"])
            for route in routes
        ):
            raise ValueError(
                "Legacy public review requires every exact registered core route: " + api
            )
    else:
        proofs = [
            item for item in (module_review or {}).get("operations", []) if item["api_id"] == api
        ]
        if len(proofs) != 1 or not routes:
            raise ValueError(
                "Legacy module review requires explicit registration/documentation proof"
            )
        proof = proofs[0]
        handlers = {source for route in routes for source in route["handler_sources"]}
        if (
            handlers != {proof["handler_path"]}
            or any(not route["handler_sources"] for route in routes)
            or not proof["handler_path"].startswith("modules/")
            or not proof["registration"]["path"].startswith(
                "/".join(proof["handler_path"].split("/")[:2]) + "/"
            )
            or proof["registration"]["constructor"].split(".")[0]
            != Path(proof["handler_path"]).stem
            or not proof["documentation"]["request_fragment"]
        ):
            raise ValueError("Legacy module registration differs from exact routes")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("versions", nargs="*")
    args = parser.parse_args()
    queue = args.versions or read(VERSIONS / "queue.json")["versions"]
    totals = []
    for version in queue:
        folder = VERSIONS / version
        inv = effective_inventory(read(folder / "inventory.json"))
        facts = read(
            ROOT / "docs/research/source-analysis" / version / "route-scope-facts.json", {}
        )
        if facts and facts["source_commit"] != inv["source_commit"]:
            raise ValueError("Source revisions differ: " + version)
        normalization_path = (
            ROOT / "docs/research/source-analysis" / version / "path-normalization.json"
        )
        normalization = read(normalization_path, {})
        if normalization and (
            normalization.get("release") != version
            or normalization.get("source_commit") != inv["source_commit"]
            or normalization.get("kind") != "source-path-normalization-proof-not-runtime-coverage"
        ):
            raise ValueError("Path normalization proof differs from pinned source: " + version)
        trailing_slash = normalization.get("trailing_slash_equivalence") is True
        if trailing_slash:
            validate_normalization_sources(version, normalization)
        parameter_release = (
            read(ROOT / "tools/research/query_parameter_facts.json", {})
            .get("releases", {})
            .get(version, {})
        )
        if parameter_release and parameter_release["source_commit"] != inv["source_commit"]:
            raise ValueError("Query parameter source revisions differ: " + version)
        parameter_facts = parameter_release.get("query_params", {})
        registered = {
            r["handler_path"] for r in facts.get("registration", {}).get("constructors", [])
        }
        sources = defaultdict(set)
        handlers = facts.get("handlers", [])
        if not handlers:
            handlers = read(folder / "server-route-ownership.json", {}).get("handlers", [])
        for handler in handlers:
            for route in handler["routes"]:
                sources[
                    (route["method"], normalized(route["path"], trailing_slash=trailing_slash))
                ].add(handler["source"])
        definitions = operations(inv)
        handler_extensions = load_route_extensions(version, inv["source_commit"])
        review_path = (
            ROOT / "docs/research/source-analysis" / version / "public-visibility-review.json"
        )
        review = read(review_path, {})
        documentation = {}
        module_review = {}
        if review:
            if (
                review.get("kind")
                != "explicit-legacy-public-documentation-review-not-runtime-support"
                or review.get("release") != version
                or review.get("source_commit") != inv["source_commit"]
                or version not in PREPARED_DOC_RELEASES
            ):
                raise ValueError("Legacy visibility review revision/scope differs")
            core_root = review.get("core_source_root", "core")
            if (
                core_root not in {"core", "server"}
                or facts.get("registration", {}).get("source", "").split("/")[0] != core_root
            ):
                raise ValueError("Legacy core root differs from pinned ActionModule source")

            required_inputs = {
                str((folder / "inventory.json").relative_to(ROOT)),
                str((review_path.parent / "route-scope-facts.json").relative_to(ROOT)),
                str((review_path.parent / "documentation-facts.json").relative_to(ROOT)),
            }
            if review.get("approved_public_module_api_ids"):
                required_inputs.add(
                    str((review_path.parent / "module-public-review.json").relative_to(ROOT))
                )
            if normalization:
                required_inputs.add(str(normalization_path.relative_to(ROOT)))
                required_inputs.update(
                    row["local_source"] for row in normalization.get("sources", [])
                )

            if set(review["input_sha256"]) != required_inputs:
                raise ValueError("Legacy review must pin every required exact source input")
            for name, checksum in review["input_sha256"].items():
                source = (ROOT / name).resolve()
                if not source.is_relative_to(ROOT / "docs/research"):
                    raise ValueError("Review input outside research")
                if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
                    raise ValueError("Legacy review source changed: " + name)
            approved = review["approved_public_api_ids"] + review.get(
                "approved_public_module_api_ids", []
            )
            if len(approved) != len(set(approved)) or set(approved) - set(definitions):
                raise ValueError("Duplicate or unknown reviewed API IDs")
            documentation = read(review_path.with_name("documentation-facts.json"))
            if review.get("approved_public_module_api_ids"):
                module_review = read(review_path.with_name("module-public-review.json"))
                if (
                    module_review["release"] != version
                    or module_review["source_commit"] != inv["source_commit"]
                ):
                    raise ValueError("Module registration review revision differs")
                handler_hashes = {row["source"]: row["sha256"] for row in facts["handlers"]}
                document_hashes = {row["path"]: row["sha256"] for row in documentation["sources"]}
                for item in module_review["operations"]:
                    if item["handler_sha256"] != handler_hashes.get(item["handler_path"]) or item[
                        "documentation"
                    ]["sha256"] != document_hashes.get(item["documentation"]["path"]):
                        raise ValueError("Module proof differs from pinned handler/reference bytes")
            if (
                documentation["release"] != version
                or documentation["source_commit"] != inv["source_commit"]
            ):
                raise ValueError("Reviewed documentation revision differs")
        raw_map = defaultdict(list)
        for row in inv["records"]:
            if row["api"] in definitions:
                raw_map[row["api"]].append(row)
        rows = []
        counts = Counter()
        dimension_count = 0
        common = next(
            (
                r["definition"]
                for r in inv["records"]
                if r["source_path"].endswith("/_common.json") and r["api"] == "params"
            ),
            {},
        )
        # Modern _common wraps global params in a top-level url object.
        modern_common = next(
            (
                r["definition"].get("params", {})
                for r in inv["records"]
                if r["source_path"].endswith("/_common.json")
                and r["api"] == "url"
                and isinstance(r["definition"], dict)
            ),
            {},
        )
        global_params = common or modern_common
        for api, definition in sorted(definitions.items()):
            records = raw_map[api]
            raw = records[0]["definition"]
            visibility = raw.get("visibility", "unknown")
            routes = []
            for route in definition["routes"]:
                for method in route["methods"]:
                    matches = sorted(
                        sources.get(
                            (method, normalized(route["path"], trailing_slash=trailing_slash)), []
                        )
                    )
                    routes.append(
                        {
                            "method": method,
                            "path": route["path"],
                            **(
                                {"deprecated": route["deprecated"]} if "deprecated" in route else {}
                            ),
                            "handler_sources": matches,
                            "registered_core_sources": [p for p in matches if p in registered],
                            "normalization": "added-leading-slash"
                            if not route["path"].startswith("/")
                            else "none",
                        }
                    )
            reviewed = legacy_public_review(
                api, visibility, routes, review, documentation, module_review
            )
            for extension in handler_extensions.get(api, []):
                if any(
                    row["method"] == extension["method"] and row["path"] == extension["path"]
                    for row in routes
                ):
                    raise ValueError("Handler extension duplicates upstream REST JSON route")
                routes.append(
                    {
                        "method": extension["method"],
                        "path": extension["path"],
                        "handler_sources": [extension["handler_source"]],
                        "registered_core_sources": (
                            [extension["handler_source"]]
                            if extension["handler_source"] in registered
                            else []
                        ),
                        "normalization": "pinned-handler-extension",
                        "source_extension": extension["proof"],
                    }
                )
            scope, basis = classify_scope(
                api, definition, "public" if reviewed else visibility, routes, len(records) > 1
            )
            if reviewed:
                if scope not in {"public-core-source", "public-module-candidate"}:
                    raise ValueError(
                        "Reviewed legacy API did not satisfy strict source classification"
                    )
                basis = (
                    "Reviewed pinned public REST reference + exact spec routes + literal core handlers + ActionModule registration; upstream visibility is absent."
                    if scope == "public-core-source"
                    else "Reviewed pinned public REST examples + exact module routes + module plugin registration; upstream visibility is absent; runtime availability remains separate."
                )
            counts[scope] += 1
            params = sorted(
                set(definition["params"]) | set(global_params) | set(parameter_facts.get(api, {}))
            )
            parts = sorted(
                {part for route in definition["routes"] for part in route.get("parts", {})}
                | {name for route in routes for name in re.findall(r"\{([^{}]+)\}", route["path"])}
            )
            media = raw.get("headers", {}) or {}
            if not isinstance(media, dict) or any(
                not isinstance(values, list) or not all(isinstance(value, str) for value in values)
                for values in media.values()
            ):
                raise ValueError("Unexpected request-media metadata: " + api)
            media_dimensions = [
                {"header": name, "media_type": value}
                for name, values in sorted(media.items())
                for value in values
            ]
            dimensions = {
                "method_paths": [
                    {
                        **{"method": r["method"], "path": r["path"]},
                        **({"deprecated": r["deprecated"]} if "deprecated" in r else {}),
                    }
                    for r in routes
                ],
                "request_media": media_dimensions,
                "query_params": params,
                "path_params": parts,
                "body": ["framing", "presence", "semantic-effect"]
                if raw.get("body") is not None
                else ["omitted"],
                "response": ["success", "expected-error", "independent-readback"],
            }
            dimensions_total = (
                len(routes)
                + len(params)
                + len(parts)
                + len(dimensions["body"])
                + 3
                + len(media_dimensions)
            )
            dimension_count += dimensions_total
            rows.append(
                {
                    "api_id": api,
                    "scope": scope,
                    "scope_basis": basis,
                    "upstream_visibility": visibility,
                    "definition_origin": records[0].get("definition_origin", "upstream-rest-json"),
                    "catalog_extension": records[0].get("catalog_extension"),
                    "scope_review_evidence": str(review_path.relative_to(ROOT))
                    if reviewed
                    else None,
                    "scope_review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()
                    if reviewed
                    else None,
                    "path_normalization_evidence": str(normalization_path.relative_to(ROOT))
                    if trailing_slash
                    else None,
                    "source_commit": inv["source_commit"],
                    "definitions": [
                        {"path": r["source_path"], "sha256": r["source_sha256"]} for r in records
                    ],
                    "routes": routes,
                    "required_dimensions": dimensions,
                    "dimension_count": dimensions_total,
                    "query_parameter_source_facts": parameter_facts.get(api, {}),
                    "request_media_types": media,
                    "deep_scenario_state": "not-planned",
                    "runtime_or_license_availability": "not-established-by-static-analysis",
                }
            )
        result = {
            "schema_version": 1,
            "release": version,
            "source_commit": inv["source_commit"],
            "classification_kind": "source-evidenced-not-runtime-support",
            "derived_catalog": inv.get("derived_catalog"),
            "scope_counts": dict(counts),
            "scope_denominator_verified": False,
            "dimension_count": dimension_count,
            "operations": rows,
            "limitations": [
                "Public-core-source is static classification, not runtime/paid-gate evidence.",
                "Unknowns remain in the research inventory; no total public-API percentage.",
                "Dimensions are obligations, not executable tests or inferred coverage.",
                "Query DSL combinations and all patches are not claimed.",
            ],
        }
        target = folder / "contract-backlog.json"
        target.write_text(json.dumps(result, indent=2) + "\n")
        totals.append(
            {
                "release": version,
                "operations": len(rows),
                "required_dimensions": dimension_count,
                "scope_counts": dict(counts),
            }
        )
    output = ROOT / "docs/research/audit/catalog-backlog-summary.json"
    previous = {row["release"]: row for row in read(output, {}).get("versions", [])}
    previous.update({row["release"]: row for row in totals})
    order = read(VERSIONS / "queue.json")["versions"]
    merged = [previous[version] for version in order if version in previous]
    output.write_text(json.dumps({"schema_version": 1, "versions": merged}, indent=2) + "\n")
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
