"""Exact7.5 native default/final ingest precedence and mixed bulk outcomes."""

import json

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.5.2", "7.6.2", "7.7.1", "7.8.1"}


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
            call("put-" + tag, {"processors": processors})
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
