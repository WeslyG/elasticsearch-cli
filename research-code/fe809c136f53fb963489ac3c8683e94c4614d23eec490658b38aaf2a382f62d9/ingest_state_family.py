"""Exact7.5 native default/final ingest precedence and mixed bulk outcomes."""

import json

from evidence_runner import OMITTED

PREPARED_VERSIONS = {
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
    "8.4.3",
    "8.5.3",
}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "ingest-state." + name
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("ingest-state." + d for d in deps)

    for tag in ["default", "explicit", "final", "drop"]:
        case(
            "put-" + tag,
            "ingest.put_pipeline",
            "PUT",
            "/_ingest/pipeline/{" + tag + "}",
            purpose="fixture-setup",
        )
    case(
        "create",
        "indices.create",
        "PUT",
        "/{index}",
        tuple("put-" + t for t in ["default", "explicit", "final", "drop"]),
        purpose="fixture-setup",
    )
    if version in {"7.16.3", "8.0.1", "8.1.3", "8.2.3", "8.3.3", "8.4.3", "8.5.3"}:
        for name, method, path, deps, expected in [
            ("version-before", "GET", "/_ingest/pipeline/{default}", ("create",), (200,)),
            (
                "version-invalid",
                "PUT",
                "/_ingest/pipeline/{default}?if_version=oops",
                ("version-before",),
                (400,),
            ),
            (
                "version-conflict",
                "PUT",
                "/_ingest/pipeline/{default}?if_version=9",
                ("version-invalid",),
                (400,),
            ),
            (
                "version-same",
                "PUT",
                "/_ingest/pipeline/{default}?if_version=10",
                ("version-conflict",),
                (400,),
            ),
            (
                "version-update",
                "PUT",
                "/_ingest/pipeline/{default}?if_version=10",
                ("version-same",),
                (200,),
            ),
            ("version-after", "GET", "/_ingest/pipeline/{default}", ("version-update",), (200,)),
            (
                "version-stale",
                "PUT",
                "/_ingest/pipeline/{default}?if_version=10",
                ("version-after",),
                (400,),
            ),
            (
                "delete-used-default",
                "DELETE",
                "/_ingest/pipeline/{default}",
                ("version-stale",),
                (400,),
            ),
            (
                "delete-used-final",
                "DELETE",
                "/_ingest/pipeline/{final}",
                ("delete-used-default",),
                (400,),
            ),
            (
                "version-preserved",
                "GET",
                "/_ingest/pipeline/{default}",
                ("delete-used-final",),
                (200,),
            ),
        ]:
            case(
                name,
                "ingest.get_pipeline"
                if method == "GET"
                else "ingest.delete_pipeline"
                if method == "DELETE"
                else "ingest.put_pipeline",
                method,
                path,
                deps,
                expected,
            )
    for name, query in [
        ("default", ""),
        ("none", "&pipeline=_none"),
        ("explicit", "&pipeline={explicit}"),
    ]:
        case(
            "write-" + name,
            "index",
            "PUT",
            "/{index}/_doc/" + name + "?refresh=true" + query,
            ("create",),
            (201,),
        )
        case(
            "read-" + name,
            "get",
            "GET",
            "/{index}/_doc/" + name,
            ("write-" + name,),
            purpose="effect-check",
        )
    case(
        "bulk",
        "bulk",
        "POST",
        "/{index}/_bulk?refresh=true",
        ("read-default", "read-none", "read-explicit"),
    )
    for name, status in [("ok", 200), ("bad", 404), ("drop", 404)]:
        case(
            "bulk-read-" + name,
            "get",
            "GET",
            "/{index}/_doc/" + name,
            ("bulk",),
            (status,),
            "effect-check",
        )
    case("count", "count", "GET", "/{index}/_count", ("bulk",), purpose="effect-check")
    case("disable-final", "indices.put_settings", "PUT", "/{index}/_settings", ("count",))
    case(
        "settings",
        "indices.get_settings",
        "GET",
        "/{index}/_settings?flat_settings=true",
        ("disable-final",),
        purpose="effect-check",
    )
    case(
        "write-disabled",
        "index",
        "PUT",
        "/{index}/_doc/disabled?refresh=true",
        ("settings",),
        (201,),
    )
    case(
        "read-disabled",
        "get",
        "GET",
        "/{index}/_doc/disabled",
        ("write-disabled",),
        purpose="effect-check",
    )
    case(
        "cleanup-index",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="fixture-cleanup",
    )
    for tag in ["default", "explicit", "final", "drop"]:
        case(
            "cleanup-" + tag,
            "ingest.delete_pipeline",
            "DELETE",
            "/_ingest/pipeline/{" + tag + "}",
            expected=(200, 404),
            purpose="fixture-cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Ingest state fixture not prepared for exact release")
    values = {"index": prefix + "-ingest-state"}
    values.update(
        {tag: prefix + "-ingest-" + tag for tag in ["default", "explicit", "final", "drop"]}
    )

    def call(name, body=OMITTED, assertions=(), verifies=(), ndjson=False):
        case = catalog.cases["ingest-state." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["ingest-state." + d for d in verifies],
            semantic=bool(assertions),
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def append(tag):
        return {"script": {"source": "ctx.steps += params.tag", "params": {"tag": tag}}}

    try:
        for tag, processors in [
            ("default", [append("D")]),
            ("explicit", [append("P")]),
            (
                "final",
                [
                    append("F"),
                    {
                        "fail": {
                            "if": "ctx.bad == true",
                            "message": "final rejected research document",
                        }
                    },
                ],
            ),
            ("drop", [{"drop": {}}]),
        ]:
            body = {"processors": processors}
            if (
                catalog.version in {"7.16.3", "8.0.1", "8.1.3", "8.2.3", "8.3.3", "8.4.3", "8.5.3"}
                and tag == "default"
            ):
                body["version"] = 10
            call("put-" + tag, body)
        call(
            "create",
            {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "index.default_pipeline": values["default"],
                    "index.final_pipeline": values["final"],
                }
            },
        )
        if catalog.version in {"7.16.3", "8.0.1", "8.1.3", "8.2.3", "8.3.3", "8.4.3", "8.5.3"}:
            original = {"processors": [append("D")]}
            changed = {"processors": [{"set": {"field": "steps", "value": "WRONG"}}]}
            check10 = [
                ("pipeline version remains10", lambda d: d[values["default"]]["version"], 10)
            ]
            check11 = [
                (
                    "pipeline version auto-increments11",
                    lambda d: d[values["default"]]["version"],
                    11,
                ),
                (
                    "updated metadata preserved",
                    lambda d: d[values["default"]]["_meta"],
                    {"research": "version11"},
                ),
                (
                    "processors remain unchanged",
                    lambda d: d[values["default"]]["processors"],
                    original["processors"],
                ),
            ]
            call("version-before", assertions=check10)
            call(
                "version-invalid",
                changed,
                [
                    (
                        "if_version must be integer",
                        lambda d: "must be an integer" in d["error"]["reason"],
                        True,
                    )
                ],
            )
            call(
                "version-conflict",
                changed,
                [
                    (
                        "version mismatch is400 not409",
                        lambda d: d["error"]["type"],
                        "illegal_argument_exception",
                    ),
                    (
                        "current version reported",
                        lambda d: "current version is [10]" in d["error"]["reason"],
                        True,
                    ),
                ],
            )
            call(
                "version-same",
                {**original, "version": 10},
                [
                    (
                        "same explicit version refused",
                        lambda d: "same version [10]" in d["error"]["reason"],
                        True,
                    )
                ],
            )
            call("version-update", {**original, "_meta": {"research": "version11"}})
            call("version-after", assertions=check11, verifies=("version-update",))
            call(
                "version-stale",
                changed,
                [
                    (
                        "stale version refused",
                        lambda d: "current version is [11]" in d["error"]["reason"],
                        True,
                    )
                ],
            )
            for name, role in [("delete-used-default", "default"), ("delete-used-final", "final")]:
                call(
                    name,
                    assertions=[
                        (
                            "used pipeline cannot be deleted",
                            lambda d, role=role: (
                                "cannot be deleted" in d["error"]["reason"]
                                and role + " pipeline" in d["error"]["reason"]
                            ),
                            True,
                        )
                    ],
                )
            call(
                "version-preserved",
                assertions=check11,
                verifies=("version-stale", "delete-used-default", "delete-used-final"),
            )
        for name, expected in [("default", "DF"), ("none", "F"), ("explicit", "PF")]:
            call("write-" + name, {"steps": ""})
            call(
                "read-" + name,
                assertions=[("actual pipeline order", lambda d: d["_source"]["steps"], expected)],
                verifies=("write-" + name,),
            )
        lines = []
        for name in ["ok", "bad", "drop"]:
            meta = {"_id": name}
            if name == "drop":
                meta["pipeline"] = values["drop"]
            lines.extend([{"index": meta}, {"steps": "", "bad": name == "bad"}])
        call(
            "bulk",
            ("\n".join(json.dumps(v) for v in lines) + "\n").encode(),
            [
                ("per-item failure reported", lambda d: d["errors"], True),
                (
                    "response order matches requests",
                    lambda d: [i["index"]["_id"] for i in d["items"]],
                    ["ok", "bad", "drop"],
                ),
                ("good item created", lambda d: d["items"][0]["index"]["status"], 201),
                (
                    "final pipeline error is explicit",
                    lambda d: (
                        d["items"][1]["index"]["status"] >= 400
                        and "final rejected research document"
                        in str(d["items"][1]["index"]["error"])
                    ),
                    True,
                ),
                ("dropped item is noop", lambda d: d["items"][2]["index"]["result"], "noop"),
            ],
            ndjson=True,
        )
        call(
            "bulk-read-ok",
            assertions=[("default then final persisted", lambda d: d["_source"]["steps"], "DF")],
            verifies=("bulk",),
        )
        for name in ["bad", "drop"]:
            call(
                "bulk-read-" + name,
                assertions=[("refused or dropped document absent", lambda d: d["found"], False)],
                verifies=("bulk",),
            )
        call(
            "count",
            assertions=[("only four documents persisted", lambda d: d["count"], 4)],
            verifies=("bulk",),
        )
        call("disable-final", {"index.final_pipeline": "_none"})
        call(
            "settings",
            assertions=[
                (
                    "dynamic final pipeline setting",
                    lambda d: d[values["index"]]["settings"]["index.final_pipeline"],
                    "_none",
                )
            ],
            verifies=("disable-final",),
        )
        call("write-disabled", {"steps": "", "bad": True})
        call(
            "read-disabled",
            assertions=[
                (
                    "only default executes after disabling final",
                    lambda d: d["_source"]["steps"],
                    "D",
                )
            ],
            verifies=("disable-final", "write-disabled"),
        )
    finally:
        call("cleanup-index")
        for tag in ["default", "explicit", "final", "drop"]:
            call("cleanup-" + tag)
