"""Exact ES7 system API body/timeout boundaries, separate from migration effects."""

from evidence_runner import OMITTED

OPERATIONS = {
    "features": ("features.get_features", "GET", "/_features"),
    "reset": ("features.reset_features", "POST", "/_features/_reset"),
    "status": ("migration.get_feature_upgrade_status", "GET", "/_migration/system_features"),
    "start": ("migration.post_feature_upgrade", "POST", "/_migration/system_features"),
}


def declare(add, version):
    if version != "7.17.29":
        return {}
    graph = {}
    for operation, (api, method, path) in OPERATIONS.items():
        for variant in [
            "omitted",
            "empty",
            "object",
            "null",
            "malformed",
            "unknown",
            "timeout",
            "bad-timeout",
        ]:
            suffix = ""
            unsupported = ()
            expected = (
                (400,)
                if variant in {"object", "null", "malformed", "unknown", "bad-timeout"}
                else (200,)
            )
            if variant == "unknown":
                suffix, unsupported = "?es_cli_unknown_probe=true", ("es_cli_unknown_probe",)
            elif variant in {"timeout", "bad-timeout"}:
                suffix = "?master_timeout=" + ("1s" if variant == "timeout" else "garbage")
                if operation == "reset":
                    expected, unsupported = (400,), ("master_timeout",)
            identifier = "system-wire." + operation + "." + variant
            add(
                identifier,
                api,
                method,
                path + suffix,
                expected=expected,
                unsupported=unsupported,
            )
            graph[identifier] = ()
    return graph


def execute(run, catalog, prefix):
    for operation in OPERATIONS:
        for variant in [
            "omitted",
            "empty",
            "object",
            "null",
            "malformed",
            "unknown",
            "timeout",
            "bad-timeout",
        ]:
            case = catalog.cases["system-wire." + operation + "." + variant]
            payload = {"empty": b"", "object": {}, "null": None, "malformed": b"{"}.get(
                variant, OMITTED
            )
            checks = []
            if case.expected == (400,):
                checks.append(
                    (
                        "typed argument error",
                        lambda data: data["error"]["type"],
                        "illegal_argument_exception",
                    )
                )
                if variant in {"object", "null", "malformed"}:
                    checks.append(
                        (
                            "body rejected before operation",
                            lambda data: (
                                "does not support having a body" in data["error"]["reason"]
                            ),
                            True,
                        )
                    )
                elif variant == "unknown" or operation == "reset":
                    name = "es_cli_unknown_probe" if variant == "unknown" else "master_timeout"
                    checks.append(
                        (
                            "unrecognized parameter identified",
                            lambda data, name=name: (
                                name in data["error"]["reason"]
                                and "unrecognized" in data["error"]["reason"]
                            ),
                            True,
                        )
                    )
                else:
                    checks.append(
                        (
                            "timeout parser identifies bad value",
                            lambda data: (
                                "master_timeout" in data["error"]["reason"]
                                and "garbage" in data["error"]["reason"]
                            ),
                            True,
                        )
                    )
            elif operation == "features":
                checks.append(
                    (
                        "tasks descriptor available",
                        lambda data: any(item["name"] == "tasks" for item in data["features"]),
                        True,
                    )
                )
            elif operation == "reset":
                checks.append(
                    (
                        "tasks reset succeeds",
                        lambda data: next(
                            item["status"]
                            for item in data["features"]
                            if item["feature_name"] == "tasks"
                        ),
                        "SUCCESS",
                    )
                )
            elif operation == "status":
                checks.append(
                    (
                        "no migration pending",
                        lambda data: data["migration_status"],
                        "NO_MIGRATION_NEEDED",
                    )
                )
            else:
                checks.append(
                    ("no-op does not start migration", lambda data: data["accepted"], False)
                )
            result = catalog.execute(
                run, case.id, body=payload, assertions=checks, depends_on=case.dependency_plan
            )
            print(case.id, result.state, result.status, flush=True)
