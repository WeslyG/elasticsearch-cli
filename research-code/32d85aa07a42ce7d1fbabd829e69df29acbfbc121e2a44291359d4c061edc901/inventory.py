"""Collect a pinned upstream REST inventory; never claims live coverage."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import time
import tempfile
from http.client import IncompleteRead

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://api.github.com/repos/elastic/elasticsearch"


def fetch(url):
    cache = Path(tempfile.gettempdir()) / "es-cli-research-http"
    cache.mkdir(exist_ok=True)
    target = cache / hashlib.sha256(url.encode()).hexdigest()
    if target.exists():
        return target.read_bytes()
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "elasticsearch-cli-research"})
            deadline = time.monotonic() + 90
            chunks = []
            size = 0
            with urllib.request.urlopen(request, timeout=20) as response:
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("HTTP source download total deadline exceeded")
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 20_000_000:
                        raise ValueError("Source response exceeds 20 MB limit")
                    chunks.append(chunk)
            body = b"".join(chunks)
            json.loads(body)
            with tempfile.NamedTemporaryFile(dir=cache, prefix=target.name + ".", suffix=".tmp", delete=False) as output:
                output.write(body)
                temporary = Path(output.name)
            temporary.replace(target)
            return body
        except (OSError, ValueError, IncompleteRead):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("unreachable")



def complete_tree(sha):
    """Walk smaller Git trees when GitHub truncates a recursive response."""
    tree = json.loads(fetch(BASE + "/git/trees/" + sha + "?recursive=1"))
    if not tree.get("truncated"):
        return tree
    direct = json.loads(fetch(BASE + "/git/trees/" + sha))
    if direct.get("truncated"):
        raise RuntimeError("Truncated direct tree: source enumeration incomplete")
    entries = []
    for item in direct["tree"]:
        entries.append(item)
        if item["type"] != "tree":
            continue
        nested = complete_tree(item["sha"])
        for child in nested["tree"]:
            entries.append(dict(child, path=item["path"] + "/" + child["path"]))
    return {"sha": sha, "tree": entries, "truncated": False,
            "enumeration": "complete-subtree-walk"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    ref = "refs/tags/v" + args.version
    try:
        remote = subprocess.check_output(
            ["git", "-c", "http.version=HTTP/1.1", "ls-remote",
             "https://github.com/elastic/elasticsearch.git", ref, ref + "^{}"],
            timeout=20, text=True,
        ).splitlines()
        resolved = dict(line.split(None, 1)[::-1] for line in remote)
        if ref not in resolved:
            raise RuntimeError("Requested exact release tag not found")
        sha = resolved.get(ref + "^{}", resolved[ref])
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        print("Git ref transport failed; using official commit API", flush=True)
        sha = json.loads(fetch(BASE + "/commits/v" + args.version))["sha"]
    tag = {"name": "v" + args.version}
    tree = complete_tree(sha)
    paths = [e["path"] for e in tree["tree"] if e["path"].endswith(".json")
             and "/rest-api-spec/api/" in e["path"]]
    out = ROOT / "docs/research/versions" / tag["name"][1:]
    out.mkdir(parents=True, exist_ok=True)
    records = []
    print("Release", tag["name"], "definition files", len(paths), flush=True)
    urls = ["https://raw.githubusercontent.com/elastic/elasticsearch/" + sha + "/" + path for path in sorted(paths)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        bodies = list(pool.map(fetch, urls))
    for number, (path, body) in enumerate(zip(sorted(paths), bodies), 1):
        if number % 25 == 0:
            print("Collected", number, "of", len(paths), flush=True)
        data = json.loads(body)
        for name, definition in data.items():
            records.append({"api": name, "source_path": path,
                            "source_sha256": hashlib.sha256(body).hexdigest(),
                            "definition": definition,
                            "scope": "excluded-xpack" if path.startswith("x-pack/") else "needs-classification",
                            "live_verification": "not-tested"})
    result = {"release": tag["name"][1:], "source_commit": sha,
              "source_tree_complete": True, "definition_file_count": len(paths),
              "records": records, "evidence_kind": "upstream-definition-only"}
    temporary = out / "inventory.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(out / "inventory.json")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}))
    print("records", len(records))


if __name__ == "__main__":
    main()
