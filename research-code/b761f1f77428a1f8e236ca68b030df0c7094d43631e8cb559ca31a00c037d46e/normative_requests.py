"""Verify exact normative request examples without changing scope or runtime claims."""

import argparse
import hashlib
import json
import re
from urllib.parse import urlsplit

from catalog_backlog import normalized
from compare_sources import operations
from inventory import ROOT

KIND = "pinned-normative-request-bindings-not-runtime-or-scope-approval"


def read_json(path):
    return json.loads(path.read_text())


def request_matches(method, path, fragment):
    """Match one documented request against the declared route, keeping literals exact."""
    request = fragment.strip()
    if request.startswith(chr(96)) and request.endswith(chr(96)):
        request = request[1:-1]
    match = re.fullmatch(r"([A-Z]+)\s+(/?\S+)", request)
    if match is None or match[1] != method:
        return False
    target = urlsplit("/" + match[2].lstrip("/"))
    if target.fragment or target.scheme or target.netloc:
        return False
    parts = re.split(r"(\{[^{}]+\})", path)
    pattern = "".join("[^/?]+" if part.startswith("{") else re.escape(part) for part in parts)
    return re.fullmatch(pattern, target.path) is not None


def validate(root, version):
    folder = root / "docs/research/source-analysis" / version
    manifest = read_json(folder / "normative-request-bindings.json")
    inventory_path = root / "docs/research/versions" / version / "inventory.json"
    docs_path = folder / "documentation-facts.json"
    facts_path = folder / "route-scope-facts.json"
    inventory, docs, facts = map(read_json, [inventory_path, docs_path, facts_path])
    commit = inventory["source_commit"]
    if (
        manifest.get("kind") != KIND
        or manifest.get("release") != version
        or manifest.get("source_commit") != commit
        or docs.get("source_commit") != commit
        or facts.get("source_commit") != commit
    ):
        raise ValueError("Normative request evidence revision differs")
    expected = {str(path.relative_to(root)) for path in [inventory_path, docs_path, facts_path]}
    if set(manifest["input_sha256"]) != expected:
        raise ValueError("Normative request evidence must pin all exact inputs")
    for name, digest in manifest["input_sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Normative request evidence input changed")
    definitions = operations(inventory)
    documents = {row["path"]: row for row in docs["sources"]}
    ownership = {}
    for handler in facts["handlers"]:
        for route in handler["routes"]:
            identity = (route["method"], normalized(route["path"]))
            ownership.setdefault(identity, set()).add(handler["source"])
    seen = set()
    for binding in manifest["bindings"]:
        api, method, path = binding["api_id"], binding["method"], binding["path"]
        definition = definitions.get(api)
        if (
            definition is None
            or definition["scope"] == "excluded-xpack"
            or api.startswith("_internal.")
            or any(
                row["api"] == api and row["definition"].get("visibility") == "private"
                for row in inventory["records"]
            )
            or not any(
                route["path"] == path and method in route["methods"]
                for route in definition["routes"]
            )
        ):
            raise ValueError("Normative binding must target an eligible exact catalog route")
        owners = ownership.get((method, normalized(path)), set())
        if not owners or any(
            not owner.startswith(("server/", "core/", "modules/")) for owner in owners
        ):
            raise ValueError("Normative binding lacks eligible literal route ownership")
        identity = (api, method, path)
        if identity in seen:
            raise ValueError("Duplicate normative request route binding")
        seen.add(identity)
        proof = binding["documentation"]
        document = documents.get(proof["path"])
        local = (root / proof["local_source"]).resolve()
        allowed = (folder / "normative-reference-sources").resolve()
        if (
            document is None
            or proof.get("sha256") != document["sha256"]
            or proof.get("git_blob") != document["git_blob"]
            or not proof["path"].startswith(("docs/reference/", "docs/painless/"))
            or not local.is_relative_to(allowed)
            or local.stat().st_size > 2_000_000
        ):
            raise ValueError("Normative reference is outside exact retained source scope")
        body = local.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != document["sha256"]
            or hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            != document["git_blob"]
        ):
            raise ValueError("Normative reference bytes differ from pinned Git blob")
        lines = body.decode().splitlines()
        line = proof["line"]
        if (
            type(line) is not int
            or line < 1
            or line > len(lines)
            or lines[line - 1].strip() != proof["request_fragment"]
            or not request_matches(method, path, proof["request_fragment"])
        ):
            raise ValueError("Normative request line or method/path differs")
    return {"release": version, "verified_request_bindings": len(seen), "new_native_http": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    print(json.dumps(validate(ROOT, args.version)))


if __name__ == "__main__":
    main()
