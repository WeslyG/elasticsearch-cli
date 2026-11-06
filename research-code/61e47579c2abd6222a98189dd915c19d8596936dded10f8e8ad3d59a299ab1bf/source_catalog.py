"""Load explicitly reviewed source-only APIs without changing upstream inventories."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from compare_sources import operations
from handler_route_extensions import core_registration
from inventory import ROOT
from java_routes import extract_routes, without_comments

KIND = "pinned-source-only-catalog-extension-not-runtime-support"


def read(path):
    return json.loads(path.read_text())


def retained(root, folder, record):
    local = (root / record["local_source"]).resolve()
    if not local.is_relative_to((folder / "derived-catalog-sources").resolve()):
        raise ValueError("Derived catalog source outside exact release")
    body = local.read_bytes()
    if (
        len(body) > 2_000_000
        or hashlib.sha256(body).hexdigest() != record["sha256"]
        or hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        != record["git_blob"]
    ):
        raise ValueError("Derived catalog source bytes differ")
    return body.decode()


def effective_inventory(inventory, root=ROOT):
    """Accept an upstream inventory and return a separate, provenance-marked copy."""
    version = inventory["release"]
    folder = root / "docs/research/source-analysis" / version
    manifest_path = folder / "derived-catalog.json"
    if not manifest_path.exists():
        return inventory
    manifest = read(manifest_path)
    inventory_path = root / "docs/research/versions" / version / "inventory.json"
    docs_path, facts_path = folder / "documentation-facts.json", folder / "route-scope-facts.json"
    docs, facts = read(docs_path), read(facts_path)
    commit = inventory["source_commit"]
    if (
        manifest.get("kind") != KIND
        or manifest.get("release") != version
        or manifest.get("source_commit") != commit
        or inventory != read(inventory_path)
        or docs["source_commit"] != commit
        or facts["source_commit"] != commit
    ):
        raise ValueError("Derived catalog revision or upstream inventory differs")
    inputs = {str(p.relative_to(root)) for p in [inventory_path, docs_path, facts_path]}
    if set(manifest["input_sha256"]) != inputs:
        raise ValueError("Derived catalog must pin all exact inputs")
    for name, digest in manifest["input_sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Derived catalog input changed")
    from normative_requests import request_matches

    upstream = operations(inventory)
    occupied = {
        (method, route["path"])
        for item in upstream.values()
        for route in item["routes"]
        for method in route["methods"]
    }
    handlers = {row["source"]: row["sha256"] for row in facts["handlers"]}
    documents = {row["path"]: row for row in docs["sources"]}
    registration = manifest["registration"]
    registration_text = retained(root, folder, registration)
    if (
        registration["path"] != facts["registration"]["source"]
        or registration["sha256"] != facts["registration"]["sha256"]
        or registration["path"] != "server/src/main/java/org/elasticsearch/action/ActionModule.java"
    ):
        raise ValueError("Derived catalog core registration differs")
    records, seen = [], set(upstream)
    for item in manifest["operations"]:
        api, definition = item["api_id"], item["definition"]
        handler, document = item["handler"], item["documentation"]
        if (
            api in seen
            or api.startswith("_internal.")
            or definition.get("visibility") in {"private", "public"}
        ):
            raise ValueError("Derived catalog ID collision or invented visibility")
        seen.add(api)
        if (
            not handler["path"].startswith("server/")
            or handler["sha256"] != handlers.get(handler["path"])
            or not document["path"].startswith("docs/reference/")
            or document["path"] not in documents
            or document["sha256"] != documents[document["path"]]["sha256"]
            or document["git_blob"] != documents[document["path"]]["git_blob"]
        ):
            raise ValueError("Derived handler/reference differs from exact source facts")
        handler_text = retained(root, folder, handler)
        document_text = retained(root, folder, document)
        if not core_registration(without_comments(registration_text), Path(handler["path"]).stem):
            raise ValueError("Derived handler lacks unconditional core registration")
        routes = extract_routes(handler_text)["routes"]
        params = definition.get("params", {})
        if set(params) != set(item.get("parameter_proofs", {})):
            raise ValueError("Derived parameters require exact source bindings")
        lines = handler_text.splitlines()
        for name, proof in item.get("parameter_proofs", {}).items():
            line = proof["line"]
            if (
                type(line) is not int
                or not 1 <= line <= len(lines)
                or lines[line - 1].strip() != proof["fragment"]
                or not re.search(
                    r'\.param(?:AsBoolean)?\(\s*"' + re.escape(name) + r'"', proof["fragment"]
                )
            ):
                raise ValueError("Derived parameter has no exact handler read")
        declared = definition["url"]["paths"]
        if len(declared) != 1 or len(declared[0]["methods"]) != 1:
            raise ValueError("Each derived record requires one explicit method/path")
        route = declared[0]
        method, path = route["methods"][0], route["path"]
        identity = (method, path)
        if identity in occupied or not any(
            row["method"] == method and row["path"] == path for row in routes
        ):
            raise ValueError("Derived route collision or nonliteral handler path")
        occupied.add(identity)
        doc_lines = document_text.splitlines()
        line = document["line"]
        if (
            type(line) is not int
            or not 1 <= line <= len(doc_lines)
            or doc_lines[line - 1].strip() != document["request_fragment"]
            or not request_matches(method, path, document["request_fragment"])
        ):
            raise ValueError("Derived route lacks exact normative request")
        records.append(
            {
                "api": api,
                "source_path": handler["path"],
                "source_sha256": handler["sha256"],
                "definition": definition,
                "scope": "needs-classification",
                "definition_origin": "reviewed-source-only-catalog-extension",
                "catalog_extension": {
                    "manifest": str(manifest_path.relative_to(root)),
                    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "source_commit": commit,
                    "documentation_url": definition["documentation"]["url"],
                    "runtime_support_inferred": False,
                },
            }
        )
    result = copy.deepcopy(inventory)
    result["records"].extend(records)
    result["derived_catalog"] = {
        "upstream_operation_count": len(upstream),
        "derived_operation_count": len(records),
        "manifest": str(manifest_path.relative_to(root)),
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    return result


def catalog_input_names(inventory, root=ROOT):
    effective = effective_inventory(inventory, root)
    catalog = effective.get("derived_catalog")
    if catalog is None:
        return set()
    manifest = read(root / catalog["manifest"])
    names = {
        catalog["manifest"],
        *manifest["input_sha256"],
        manifest["registration"]["local_source"],
    }
    for item in manifest["operations"]:
        names.update(item[key]["local_source"] for key in ["handler", "documentation"])
    return names


def freeze_catalog_inputs(inventory, destination, root=ROOT):
    """Freeze only exact required source inputs; never substitute the upstream inventory."""
    import shutil

    names = catalog_input_names(inventory, root)
    if not names:
        return None
    frozen = destination / "catalog-inputs"
    hashes = {}
    for name in sorted(names):
        source = root / name
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "kind": "frozen-derived-catalog-inputs-not-runtime-support",
        "release": inventory["release"],
        "source_commit": inventory["source_commit"],
        "files": hashes,
    }


def validate_frozen_catalog(folder, metadata, *, git_sha=None, git_root=ROOT):
    """Check all copied bytes and replay source validation in the isolated snapshot."""
    import subprocess

    if metadata.get("kind") != "frozen-derived-catalog-inputs-not-runtime-support":
        raise ValueError("Unexpected frozen catalog input kind")
    frozen = (folder / "catalog-inputs").resolve()
    for name, digest in metadata["files"].items():
        source = (frozen / name).resolve()
        if not source.is_relative_to(frozen) or not name.startswith("docs/research/"):
            raise ValueError("Frozen catalog source escaped input root")
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Frozen catalog input bytes changed")
        if git_sha is not None:
            committed = subprocess.check_output(["git", "show", git_sha + ":" + name], cwd=git_root)
            if body != committed:
                raise ValueError("Frozen catalog input differs from producer Git revision")
    version = metadata["release"]
    inventory = read(frozen / "docs/research/versions" / version / "inventory.json")
    if inventory["source_commit"] != metadata["source_commit"]:
        raise ValueError("Frozen catalog source revision differs")
    if set(metadata["files"]) != catalog_input_names(inventory, frozen):
        raise ValueError("Frozen catalog must contain exactly the required inputs")
    return effective_inventory(inventory, frozen).get("derived_catalog")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    inventory = read(ROOT / "docs/research/versions" / args.version / "inventory.json")
    print(
        json.dumps(
            {
                "release": args.version,
                **effective_inventory(inventory).get("derived_catalog", {}),
                "new_native_http": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
