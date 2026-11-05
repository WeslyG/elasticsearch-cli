"""Stored scripts, search templates and ingest transformations with readback."""

import json

from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    legacy = version.startswith("6.")
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if legacy and (name == "pipeline.stale" or name.startswith("painless.")):
            return
        if legacy:
            path = path.replace("?if_version=1", "").replace("/{index}/_doc/", "/{index}/fixture/")
            deps = tuple("pipeline.update" if d == "pipeline.stale" else d for d in deps)
        add("transform." + name, api, method, path, expected=expected, purpose=purpose)
        graph["transform." + name] = tuple("transform." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case("pipeline.put", "ingest.put_pipeline", "PUT", "/_ingest/pipeline/{pipeline}")
    case(
        "pipeline.update",
        "ingest.put_pipeline",
        "PUT",
        "/_ingest/pipeline/{pipeline}?if_version=1",
        ("pipeline.put",),
    )
    case(
        "pipeline.stale",
        "ingest.put_pipeline",
        "PUT",
        "/_ingest/pipeline/{pipeline}?if_version=1",
        ("pipeline.update",),
        (400,),
    )
    for name, path in [("named", "/_ingest/pipeline/{pipeline}"), ("all", "/_ingest/pipeline")]:
        case(
            "pipeline.get." + name,
            "ingest.get_pipeline",
            "GET",
            path,
            ("pipeline.stale",),
            purpose="effect-check",
        )
    for method in ["GET", "POST"]:
        for variant, path in [
            ("inline", "/_ingest/pipeline/_simulate"),
            ("stored", "/_ingest/pipeline/{pipeline}/_simulate"),
        ]:
            case(
                "simulate." + method.lower() + "." + variant,
                "ingest.simulate",
                method,
                path,
                ("pipeline.update",),
            )
    case(
        "simulate.verbose",
        "ingest.simulate",
        "POST",
        "/_ingest/pipeline/{pipeline}/_simulate?verbose=true",
        ("pipeline.update",),
    )
    case("simulate.on-failure", "ingest.simulate", "POST", "/_ingest/pipeline/_simulate")
    case(
        "pipeline.index",
        "index",
        "PUT",
        "/{index}/_doc/one?pipeline={pipeline}&refresh=true",
        ("create", "pipeline.update"),
        (201,),
    )
    case(
        "pipeline.readback",
        "get",
        "GET",
        "/{index}/_doc/one",
        ("pipeline.index",),
        purpose="effect-check",
    )
    case(
        "pipeline.invalid",
        "ingest.put_pipeline",
        "PUT",
        "/_ingest/pipeline/{badpipeline}",
        expected=(400,),
    )
    case(
        "pipeline.invalid-absent",
        "ingest.get_pipeline",
        "GET",
        "/_ingest/pipeline/{badpipeline}",
        ("pipeline.invalid",),
        (404,),
        purpose="effect-check",
    )
    previous = "pipeline.readback"
    for method in ["PUT", "POST"]:
        for variant, path in [
            ("base", "/_scripts/{script}"),
            ("context", "/_scripts/{script}/template"),
        ]:
            name = "script.put." + method.lower() + "." + variant
            case(name, "put_script", method, path, (previous,))
            case(
                name + ".get",
                "get_script",
                "GET",
                "/_scripts/{script}",
                (name,),
                purpose="effect-check",
            )
            previous = name + ".get"
    for method in ["GET", "POST"]:
        for variant, path in [
            ("inline", "/_render/template"),
            ("stored", "/_render/template/{script}"),
        ]:
            case(
                "render." + method.lower() + "." + variant,
                "render_search_template",
                method,
                path,
                (previous,),
            )
        for scope, base in [("global", ""), ("index", "/{index}")]:
            case(
                "search." + method.lower() + "." + scope,
                "search_template",
                method,
                base + "/_search/template",
                (previous, "pipeline.readback"),
            )
            case(
                "msearch." + method.lower() + "." + scope,
                "msearch_template",
                method,
                base + "/_msearch/template",
                (previous, "pipeline.readback"),
            )
        case(
            "painless." + method.lower(),
            "scripts_painless_execute",
            method,
            "/_scripts/painless/_execute",
        )
    case("script.deferred", "put_script", "PUT", "/_scripts/{deferredscript}")
    case(
        "script.deferred-get",
        "get_script",
        "GET",
        "/_scripts/{deferredscript}",
        ("script.deferred",),
        purpose="effect-check",
    )
    case(
        "script.deferred-delete",
        "delete_script",
        "DELETE",
        "/_scripts/{deferredscript}",
        expected=(200, 404),
        purpose="cleanup",
    )
    case("script.invalid", "put_script", "PUT", "/_scripts/{badscript}/score", expected=(400,))
    case(
        "script.invalid-absent",
        "get_script",
        "GET",
        "/_scripts/{badscript}",
        ("script.invalid",),
        (404,),
        purpose="effect-check",
    )
    case(
        "script.delete",
        "delete_script",
        "DELETE",
        "/_scripts/{script}",
        expected=(200, 404),
        purpose="cleanup",
    )
    case(
        "script.absent",
        "get_script",
        "GET",
        "/_scripts/{script}",
        ("script.delete",),
        (404,),
        purpose="effect-check",
    )
    case(
        "pipeline.delete",
        "ingest.delete_pipeline",
        "DELETE",
        "/_ingest/pipeline/{pipeline}",
        expected=(200, 404),
        purpose="cleanup",
    )
    case(
        "pipeline.absent",
        "ingest.get_pipeline",
        "GET",
        "/_ingest/pipeline/{pipeline}",
        ("pipeline.delete",),
        (404,),
        purpose="effect-check",
    )
    case("cleanup", "indices.delete", "DELETE", "/{index}", expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    legacy = catalog.version.startswith("6.")
    values = {
        "index": prefix + "-transform",
        "pipeline": prefix + "-pipeline",
        "badpipeline": prefix + "-invalid-pipeline",
        "script": prefix + "-script",
        "badscript": prefix + "-invalid-script",
        "deferredscript": prefix + "-deferred-script",
    }
    pipeline = values["pipeline"]
    source = '{"query":{"bool":{"filter":[{"term":{"_index":"{{index}}"}},{"term":{"n":{{n}}}}]}}}'
    processors = [
        {"set": {"field": "processed", "value": True}},
        {"script": {"source": "ctx.n += params.delta", "params": {"delta": 3}}},
    ]
    pipeline_body = {"version": 1, "processors": processors}

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
        case = catalog.cases["transform." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["transform." + n for n in verifies],
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]

    def typed(body):
        if legacy:
            body["mappings"] = {"fixture": body["mappings"]}
        return body

    call(
        "create",
        typed(
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {"n": {"type": "integer"}, "processed": {"type": "boolean"}}
                },
            }
        ),
        ack,
    )
    try:
        call("pipeline.put", pipeline_body, ack)
        call(
            "pipeline.update", {"processors": processors, **({"version": 2} if legacy else {})}, ack
        )
        if not legacy:
            call(
                "pipeline.stale",
                {"processors": []},
                [("version conflict", lambda d: d["error"]["type"], "illegal_argument_exception")],
            )
        for route in ["named", "all"]:
            call(
                "pipeline.get." + route,
                assertions=[
                    ("version incremented", lambda d: d[pipeline]["version"], 2),
                    (
                        "stale update did not remove processors",
                        lambda d: len(d[pipeline]["processors"]),
                        2,
                    ),
                ],
                verifies=["pipeline.update"] if legacy else ["pipeline.update", "pipeline.stale"],
                semantic=True,
            )
        documents = [
            {
                "_index": values["index"],
                "_id": "sim",
                "_source": {"n": 5},
                **({"_type": "fixture"} if legacy else {}),
            }
        ]
        for method in ["get", "post"]:
            for variant in ["inline", "stored"]:
                body = {"docs": documents}
                if variant == "inline":
                    body["pipeline"] = {"processors": processors}
                call(
                    "simulate." + method + "." + variant,
                    body,
                    [
                        (
                            "transformed source",
                            lambda d: d["docs"][0]["doc"]["_source"],
                            {"n": 8, "processed": True},
                        )
                    ],
                    semantic=True,
                )
        call(
            "simulate.verbose",
            {"docs": documents},
            [
                ("each processor reported", lambda d: len(d["docs"][0]["processor_results"]), 2),
                (
                    "final processor output",
                    lambda d: d["docs"][0]["processor_results"][-1]["doc"]["_source"]["n"],
                    8,
                ),
            ],
            semantic=True,
        )
        call(
            "simulate.on-failure",
            {
                "pipeline": {
                    "processors": [{"fail": {"message": "research fixture failure"}}],
                    "on_failure": [{"set": {"field": "recovered", "value": True}}],
                },
                "docs": documents,
            },
            [
                (
                    "failure handler applied",
                    lambda d: d["docs"][0]["doc"]["_source"]["recovered"],
                    True,
                )
            ],
            semantic=True,
        )
        call("pipeline.index", {"n": 5})
        call(
            "pipeline.readback",
            assertions=[
                (
                    "actual indexed transformation",
                    lambda d: d["_source"],
                    {"n": 8, "processed": True},
                )
            ],
            verifies=["pipeline.index"],
            semantic=True,
        )
        call(
            "pipeline.invalid",
            {"processors": [{"fixture_processor_does_not_exist": {}}]},
            [("invalid processor", lambda d: d["error"]["type"], "parse_exception")],
        )
        call("pipeline.invalid-absent")
        for method in ["put", "post"]:
            for variant in ["base", "context"]:
                stem = "script.put." + method + "." + variant
                call(stem, {"script": {"lang": "mustache", "source": source}}, ack)
                call(
                    stem + ".get",
                    assertions=[
                        ("stored language", lambda d: d["script"]["lang"], "mustache"),
                        ("stored source exact", lambda d: d["script"]["source"], source),
                    ],
                    verifies=[stem],
                    semantic=True,
                )
        parameters = {"index": values["index"], "n": 8}
        for method in ["get", "post"]:
            for variant in ["inline", "stored"]:
                body = {"params": parameters}
                if variant == "inline":
                    body["source"] = source
                call(
                    "render." + method + "." + variant,
                    body,
                    [
                        (
                            "rendered JSON exact",
                            lambda d: d["template_output"],
                            json.loads(
                                source.replace("{{index}}", values["index"]).replace("{{n}}", "8")
                            ),
                        )
                    ],
                    semantic=True,
                )
            for scope in ["global", "index"]:
                body = {"id": values["script"], "params": parameters}
                call(
                    "search." + method + "." + scope,
                    body,
                    [
                        (
                            "stored template matched transformed document",
                            lambda d: [h["_id"] for h in d["hits"]["hits"]],
                            ["one"],
                        )
                    ],
                    semantic=True,
                )
                parts = [
                    {"index": values["index"]},
                    body,
                    {"index": values["index"]},
                    {"id": values["script"], "params": {**parameters, "n": 9}},
                ]
                payload = ("\n".join(json.dumps(part) for part in parts) + "\n").encode()
                call(
                    "msearch." + method + "." + scope,
                    payload,
                    [
                        (
                            "matching template",
                            lambda d: [h["_id"] for h in d["responses"][0]["hits"]["hits"]],
                            ["one"],
                        ),
                        ("nonmatching template", lambda d: d["responses"][1]["hits"]["hits"], []),
                    ],
                    semantic=True,
                    ndjson=True,
                )
            if not legacy:
                call(
                    "painless." + method,
                    {"script": {"source": "params.a + params.b", "params": {"a": 2, "b": 3}}},
                    [("script evaluates", lambda d: d["result"], "5")],
                    semantic=True,
                )
        call(
            "script.deferred",
            {"script": {"lang": "painless", "source": "this is invalid syntax !!!"}},
            ack,
        )
        call(
            "script.deferred-get",
            assertions=[
                (
                    "uncompiled source stored",
                    lambda d: d["script"]["source"],
                    "this is invalid syntax !!!",
                )
            ],
            verifies=["script.deferred"],
            semantic=True,
        )
        call(
            "script.invalid",
            {"script": {"lang": "painless", "source": "this is invalid syntax !!!"}},
            [("compile error", lambda d: d["error"]["type"], "script_exception")],
        )
        call("script.invalid-absent")
    finally:
        call("script.deferred-delete")
        call("script.delete")
        call("script.absent")
        call("pipeline.delete")
        call("pipeline.absent")
        call("cleanup")
