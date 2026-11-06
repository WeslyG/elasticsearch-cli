"""Map legacy REST documentation to pinned source anchors; no scope promotion."""

import argparse
import hashlib
import json
import re
import tempfile
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from inventory import ROOT, complete_tree

PREPARED_DOC_RELEASES = frozenset(
    {
        "6.0.0",
        "6.0.1",
        "6.1.4",
        "6.2.4",
        "6.3.2",
        "6.4.3",
        "6.5.4",
        "6.6.2",
        "6.7.2",
        "6.8.23",
        "7.0.1",
        "7.1.1",
        "7.2.1",
        "7.3.2",
        "7.4.2",
        "7.5.2",
        "7.6.2",
        "7.7.1",
        "7.8.1",
        "7.9.3",
        "7.10.2",
    }
)

CACHE = Path(tempfile.gettempdir()) / "es-cli-research-http/legacy-docs"


def source(commit, entry):
    """Cache by verified Git blob identity, shared only for identical source bytes."""
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / entry["sha"]
    if target.exists():
        body = target.read_bytes()
    else:
        url = (
            "https://raw.githubusercontent.com/elastic/elasticsearch/"
            + commit
            + "/"
            + entry["path"]
        )
        request = urllib.request.Request(url, headers={"User-Agent": "es-cli-contract-research"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Oversized pinned document")
    blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    if blob != entry["sha"]:
        raise ValueError("Pinned Git blob mismatch: " + entry["path"])
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as output:
            output.write(body)
            temporary = Path(output.name)
        temporary.replace(target)
    return entry, body


def collect(version):
    folder = ROOT / "docs/research/versions" / version
    inventory_path = folder / "inventory.json"
    inventory = json.loads(inventory_path.read_text())
    commit = inventory["source_commit"]
    tree = complete_tree(commit)
    if tree.get("truncated"):
        raise ValueError("Complete pinned tree required")
    directories = (
        "docs/reference/docs/",
        "docs/reference/indices/",
        "docs/reference/cat/",
        "docs/reference/cluster/",
        "docs/reference/search/",
        "docs/reference/ingest/",
        "docs/reference/modules/",
        "docs/reference/snapshot-restore/",
    )
    entries = [
        entry
        for entry in tree["tree"]
        if entry["path"].endswith(".asciidoc")
        and (
            entry["path"].startswith(directories)
            or entry["path"] == "docs/painless/painless-execute-script.asciidoc"
            or entry["path"] == "docs/painless/painless-guide/painless-execute-script.asciidoc"
            or entry["path"] == "docs/reference/setup/secure-settings.asciidoc"
            or (entry["path"].startswith("docs/reference/") and entry["path"].count("/") == 2)
        )
    ]
    anchors = defaultdict(list)
    sources = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for entry, body in pool.map(lambda item: source(commit, item), entries):
            text = body.decode()
            digest = hashlib.sha256(body).hexdigest()
            sources.append({"path": entry["path"], "git_blob": entry["sha"], "sha256": digest})
            for match in re.finditer(r"^\[\[([^],\n]+)(?:,[^]\n]*)?\]\]", text, re.MULTILINE):
                line = text.count("\n", 0, match.start()) + 1
                anchors[match[1]].append(
                    {
                        "path": entry["path"],
                        "line": line,
                        "sha256": digest,
                        "url": "https://github.com/elastic/elasticsearch/blob/"
                        + commit
                        + "/"
                        + entry["path"]
                        + "#L"
                        + str(line),
                    }
                )
    backlog_path = folder / "contract-backlog.json"
    backlog = json.loads(backlog_path.read_text())
    definitions = {row["api"]: row["definition"] for row in inventory["records"]}
    rows = []
    for operation in backlog["operations"]:
        # Preserve reviewed legacy operations on a repeated collection.
        if operation.get("upstream_visibility", "unknown") != "unknown" or operation["scope"] in {
            "private",
            "excluded-xpack",
            "example-metadata",
        }:
            continue
        api = operation["api_id"]
        documentation = definitions[api].get("documentation")
        if isinstance(documentation, dict):
            documentation = documentation.get("url", "")
        parsed = urlsplit(documentation or "")
        anchor = parsed.fragment or Path(parsed.path).stem
        matches = anchors.get(anchor, [])
        rows.append(
            {
                "api_id": api,
                "upstream_documentation_url": documentation,
                "target_anchor": anchor,
                "pinned_anchor_matches": matches,
                "review_state": "anchor-found-review-required"
                if matches
                else "unresolved-documentation",
            }
        )
    result = {
        "schema_version": 1,
        "kind": "pinned-documentation-facts-not-scope-or-runtime-proof",
        "release": version,
        "source_commit": commit,
        "input_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [inventory_path, backlog_path]
        },
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": sources,
        "counts": dict(Counter(row["review_state"] for row in rows)),
        "operations": rows,
        "limitations": [
            "A documentation link or anchor alone does not establish public visibility.",
            "Review prose, module registration and exact routes before any scope decision.",
            "No runtime HTTP executions or API support are inferred.",
            "Only selected REST reference directories plus explicit Painless execute and secure-settings references scanned; unresolved is not absent.",
            "Upstream master URLs are metadata only; content fetched at exact release commit.",
        ],
    }
    destination = ROOT / "docs/research/source-analysis" / version / "documentation-facts.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"release": version, "documents": len(sources), "counts": result["counts"]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("versions", nargs="+")
    args = parser.parse_args()
    for version in args.versions:
        if version not in PREPARED_DOC_RELEASES:
            raise ValueError("Legacy documentation review prepared only for these exact releases")
        collect(version)


if __name__ == "__main__":
    main()
