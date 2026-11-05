"""Independently verify saved native keystore read/error/recovery evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from validate_attempt import validate


def validate_keystore(folder):
    folder = Path(folder).resolve()
    summary = validate(folder)
    assert summary["release"] in {
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
    }
    fixture = json.loads((folder / "keystore-reload-fixture.json").read_text())
    allowed = {
        "kind",
        "lab_id",
        "node_container_id",
        "keystore_path",
        "keystore_bytes_exported",
        "restored",
        "original_size",
        "original_sha256",
        "original_permissions",
        "backup_directory",
        "backup_sha256",
        "observed_elasticsearch_node_ids",
        "corrupt_sha256",
        "corruption_applied",
        "restored_sha256",
        "restored_permissions",
        "backup_removed",
        "api_recovery_verified",
    }
    assert set(fixture) == allowed, "Unexpected fixture fields; never publish keystore contents"
    assert fixture["kind"] == "owned-keystore-read-error-recovery-not-credential-rotation"
    assert fixture["corruption_applied"] is True
    assert fixture["keystore_path"] == "/usr/share/elasticsearch/config/elasticsearch.keystore"
    assert fixture["keystore_bytes_exported"] is False
    assert (
        fixture["restored"] is fixture["backup_removed"] is fixture["api_recovery_verified"] is True
    )
    assert fixture["original_sha256"] == fixture["backup_sha256"] == fixture["restored_sha256"]
    assert fixture["original_permissions"] == fixture["restored_permissions"]
    assert fixture["corrupt_sha256"] == hashlib.sha256(b"es-cli-invalid-keystore").hexdigest()
    assert fixture["corrupt_sha256"] != fixture["original_sha256"]
    assert 0 < fixture["original_size"] <= 1_048_576
    rows = [json.loads(line) for line in (folder / "observations.jsonl").read_text().splitlines()]
    rows = [row for row in rows if row["scenario_id"].startswith("secure-reload.")]
    assert len(rows) == 14 and all(row["state"] == "passed" for row in rows)
    cases = {row["scenario_id"].removeprefix("secure-reload."): row for row in rows}

    def body(name):
        return cases[name]["response"]["body"]["data"]

    ids = fixture["observed_elasticsearch_node_ids"]
    assert len(ids) == 1
    good = [
        "all-good",
        "local-good",
        "empty-bytes",
        "ignored-object",
        "ignored-null",
        "ignored-malformed",
        "timeout-good",
        "restored-local",
        "restored-all",
    ]
    for name in good:
        data = body(name)
        assert cases[name]["response"]["status"] == 200
        assert data["cluster_name"] == fixture["lab_id"] and sorted(data["nodes"]) == ids
        assert data["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
        assert all(
            info["name"] == "es-cli-anchor" and "reload_exception" not in info
            for info in data["nodes"].values()
        )
    for name in ["corrupt-local", "corrupt-all"]:
        data = body(name)
        assert cases[name]["response"]["status"] == 200
        assert data["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
        assert sorted(data["nodes"]) == ids
        assert cases[name]["positive_semantic_evidence"] is False
        for info in data["nodes"].values():
            error = info["reload_exception"]
            assert error["type"] == "corrupt_index_exception"
            assert "codec header mismatch" in error["reason"]
            assert str(int.from_bytes(b"es-c", "big")) in error["reason"], (
                "Server did not read the injected fixture header"
            )
    assert body("missing-node")["_nodes"] == {"total": 0, "successful": 0, "failed": 0}
    assert (
        body("missing-node")["nodes"] == {}
        and cases["missing-node"]["positive_semantic_evidence"] is False
    )
    for name, field in [("timeout-bad", "garbage"), ("unknown-query", "es_cli_unknown")]:
        assert cases[name]["response"]["status"] == 400 and field in body(name)["error"]["reason"]
    assert cases["all-good"]["request"]["body"]["presence"] == "omitted"
    assert cases["empty-bytes"]["request"]["body"]["length"] == 0
    assert cases["ignored-null"]["request"]["body"]["text"] == "null"
    assert cases["ignored-malformed"]["request"]["body"]["text"] == "{"
    result = {
        "kind": "validated-keystore-file-read-error-recovery-not-consumer-rotation",
        "release": summary["release"],
        "observations_sha256": summary["raw_observations_sha256"],
        "fixture_sha256": hashlib.sha256(
            (folder / "keystore-reload-fixture.json").read_bytes()
        ).hexdigest(),
        "http_verified": 14,
        "http200_with_reload_exception": 2,
        "original_bytes_permissions_restored": True,
        "backup_removed": True,
        "keystore_bytes_exported": False,
        "remaining": [
            "Actual reloadable-plugin credential rotation",
            "Password-protected store",
            "Multi-node and native TLS for this API",
        ],
    }
    (folder / "keystore-reload-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    print(json.dumps(validate_keystore(parser.parse_args().folder)))


if __name__ == "__main__":
    main()
