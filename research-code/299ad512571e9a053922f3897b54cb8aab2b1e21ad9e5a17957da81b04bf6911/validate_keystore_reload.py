"""Independently verify saved native keystore read/error/recovery evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from secure_reload_family import PARSED_BODY_RELEASES
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
        "7.6.2",
        "7.7.1",
        "7.8.1",
        "7.9.3",
        "7.10.2",
        "7.11.2",
        "7.12.1",
        "7.13.4",
        "7.14.2",
        "7.15.2",
        "7.16.3",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
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
    parsed = summary["release"] in PARSED_BODY_RELEASES
    expected_rows = 17 if parsed else 14
    assert len(rows) == expected_rows and all(row["state"] == "passed" for row in rows)
    cases = {row["scenario_id"].removeprefix("secure-reload."): row for row in rows}

    def body(name):
        return cases[name]["response"]["body"]["data"]

    ids = fixture["observed_elasticsearch_node_ids"]
    assert len(ids) == 1
    good = [
        "all-good",
        "local-good",
        "empty-bytes",
        "timeout-good",
        "restored-local",
        "restored-all",
    ]
    good += (
        ["parsed-empty-object", "parsed-empty-password"]
        if parsed
        else ["ignored-object", "ignored-null", "ignored-malformed"]
    )
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
    null_case = "parsed-null" if parsed else "ignored-null"
    malformed_case = "parsed-malformed" if parsed else "ignored-malformed"
    assert cases[null_case]["request"]["body"]["text"] == "null"
    assert cases[malformed_case]["request"]["body"]["text"] == "{"
    if parsed:
        for name in ["parsed-null", "parsed-malformed", "parsed-unknown"]:
            expected_status = (
                500 if name == "parsed-malformed" and summary["release"] in {"8.2.3"} else 400
            )
            assert cases[name]["response"]["status"] == expected_status and isinstance(
                body(name)["error"], dict
            )
            if expected_status == 500:
                assert body(name)["error"]["type"] == "x_content_e_o_f_exception"
        assert "es_cli_unknown" in str(body("parsed-unknown")["error"])
        assert cases["parsed-wrong-password"]["response"]["status"] == 200
        assert body("parsed-wrong-password")["_nodes"] == {"total": 1, "successful": 1, "failed": 0}
        assert sorted(body("parsed-wrong-password")["nodes"]) == ids
        for info in body("parsed-wrong-password")["nodes"].values():
            assert info["reload_exception"]["type"] == "security_exception"
            assert "Provided keystore password was incorrect" in info["reload_exception"]["reason"]
        assert (
            cases["parsed-wrong-password"]["request"]["body"]["text"]
            == '{"secure_settings_password":"public-fixture-incorrect-password"}'
        )
        assert not cases["parsed-wrong-password"]["positive_semantic_evidence"]
    result = {
        "kind": "validated-keystore-file-read-error-recovery-not-consumer-rotation",
        "release": summary["release"],
        "validator_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observations_sha256": summary["raw_observations_sha256"],
        "fixture_sha256": hashlib.sha256(
            (folder / "keystore-reload-fixture.json").read_bytes()
        ).hexdigest(),
        "http_verified": expected_rows,
        "http200_with_reload_exception": 3 if parsed else 2,
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
