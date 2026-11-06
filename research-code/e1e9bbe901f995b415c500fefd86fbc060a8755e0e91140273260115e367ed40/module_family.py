"""Remaining local module contracts; provider configuration is not download coverage."""

from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    seven = version in {
        "7.15.2",
        "7.16.3",
        "7.17.29",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
        "8.9.2",
        "8.10.4",
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
        "9.2.8",
        "9.3.8",
        "9.4.9",
    }
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if seven and not (
            name
            in {
                "info",
                "ping",
                "create",
                "pipeline",
                "seed",
                "grok",
                "painless-contexts",
                "painless-score",
                "geo-stats",
                "cleanup-pipeline",
                "cleanup-index",
                "source-present",
                "source-absent",
            }
            or name.startswith(("field-", "rank."))
        ):
            return
        if seven and name in {"source-present", "source-absent"}:
            deps = ("seed",)
            path = path.replace("/actual", "/a")
        add("module." + name, api, method, path, expected=expected, purpose=purpose)
        graph["module." + name] = tuple("module." + d for d in deps)

    case("info", "info", "GET", "/")
    case("ping", "ping", "HEAD", "/")
    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "pipeline",
        "ingest.put_pipeline",
        "PUT",
        "/_ingest/pipeline/{pipeline}",
        purpose="fixture-setup",
    )
    case(
        "seed",
        "create",
        "PUT",
        "/{index}/_create/a?refresh=true",
        ("create",),
        (201,),
        purpose="fixture-setup",
    )
    case(
        "field-before",
        "indices.field_usage_stats",
        "GET",
        "/{index}/_field_usage_stats",
        ("seed",),
        purpose="fixture-precondition",
    )
    case(
        "field-query",
        "search",
        "POST",
        "/{index}/_search?request_cache=false",
        ("field-before",),
        purpose="fixture-setup",
    )
    case(
        "field-after",
        "indices.field_usage_stats",
        "GET",
        "/{index}/_field_usage_stats",
        ("field-query",),
        purpose="effect-check",
    )
    for method in ["GET", "POST"]:
        for scope, base in [("global", ""), ("index", "/{index}")]:
            case(
                "rank." + method.lower() + "." + scope,
                "rank_eval",
                method,
                base + "/_rank_eval",
                ("seed",),
            )
            case(
                "simulate." + method.lower() + "." + scope,
                "simulate.ingest",
                method,
                "/_ingest" + base + "/_simulate?pipeline={pipeline}",
                ("seed", "pipeline"),
            )
    case(
        "pipeline-unchanged",
        "ingest.get_pipeline",
        "GET",
        "/_ingest/pipeline/{pipeline}",
        (
            "simulate.get.global",
            "simulate.get.index",
            "simulate.post.global",
            "simulate.post.index",
        ),
        purpose="effect-check",
    )
    case(
        "actual-index",
        "create",
        "PUT",
        "/{index}/_create/actual?pipeline={pipeline}&refresh=true",
        ("pipeline-unchanged",),
        (201,),
    )
    case(
        "actual-readback",
        "get",
        "GET",
        "/{index}/_doc/actual",
        ("actual-index",),
        purpose="effect-check",
    )
    case("source-present", "exists_source", "HEAD", "/{index}/_source/actual", ("actual-index",))
    case(
        "source-absent",
        "exists_source",
        "HEAD",
        "/{index}/_source/missing",
        ("actual-index",),
        (404,),
    )
    case("resolve-all", "indices.resolve_cluster", "GET", "/_resolve/cluster")
    case(
        "resolve-index", "indices.resolve_cluster", "GET", "/_resolve/cluster/{index}", ("create",)
    )
    case(
        "resolve-missing",
        "indices.resolve_cluster",
        "GET",
        "/_resolve/cluster/{index}-missing",
        ("create",),
    )
    case(
        "resolve-missing-lenient",
        "indices.resolve_cluster",
        "GET",
        "/_resolve/cluster/{index}-missing?ignore_unavailable=true&allow_no_indices=true",
        ("create",),
    )
    case(
        "grok",
        "ingest.processor_grok",
        "GET",
        "/_ingest/processor/grok?filter_path=patterns.IP,patterns.NUMBER",
    )
    case("painless-contexts", "scripts_painless_context", "GET", "/_scripts/painless/_context")
    case(
        "painless-score",
        "scripts_painless_context",
        "GET",
        "/_scripts/painless/_context?context=score&filter_path=name,classes.name",
    )
    case("geo-stats", "ingest.geo_ip_stats", "GET", "/_ingest/geoip/stats")
    case(
        "geo-invalid-name",
        "ingest.put_geoip_database",
        "PUT",
        "/_ingest/geoip/database/{database}",
        expected=(400,),
    )
    case(
        "geo-create",
        "ingest.put_geoip_database",
        "PUT",
        "/_ingest/geoip/database/{database}",
        purpose="configuration-contract-not-provider-integration",
    )
    for name, base in [("geo", "geoip"), ("location", "ip_location")]:
        for scope, suffix in [("all", ""), ("named", "/{database}")]:
            case(
                name + "-get." + scope,
                "ingest.get_" + ("geoip" if name == "geo" else "ip_location") + "_database",
                "GET",
                "/_ingest/" + base + "/database" + suffix,
                ("geo-create",),
                purpose="effect-check",
            )
    case(
        "location-update",
        "ingest.put_ip_location_database",
        "PUT",
        "/_ingest/ip_location/database/{database}",
        ("geo-create",),
        purpose="configuration-contract-not-provider-integration",
    )
    case(
        "location-readback",
        "ingest.get_geoip_database",
        "GET",
        "/_ingest/geoip/database/{database}",
        ("location-update",),
        purpose="effect-check",
    )
    case(
        "location-noop",
        "ingest.put_ip_location_database",
        "PUT",
        "/_ingest/ip_location/database/{database}",
        ("location-update",),
        purpose="configuration-contract-not-provider-integration",
    )
    case(
        "noop-readback",
        "ingest.get_ip_location_database",
        "GET",
        "/_ingest/ip_location/database/{database}",
        ("location-noop",),
        purpose="effect-check",
    )
    case(
        "location-delete",
        "ingest.delete_ip_location_database",
        "DELETE",
        "/_ingest/ip_location/database/{database}",
        ("location-update",),
    )
    case(
        "location-absent",
        "ingest.get_geoip_database",
        "GET",
        "/_ingest/geoip/database/{database}",
        ("location-delete",),
        purpose="effect-check",
    )
    case(
        "geo-recreate",
        "ingest.put_geoip_database",
        "PUT",
        "/_ingest/geoip/database/{database}",
        ("location-delete",),
        purpose="configuration-contract-not-provider-integration",
    )
    case(
        "geo-delete",
        "ingest.delete_geoip_database",
        "DELETE",
        "/_ingest/geoip/database/{database}",
        ("geo-recreate",),
    )
    case(
        "geo-absent",
        "ingest.get_ip_location_database",
        "GET",
        "/_ingest/ip_location/database/{database}",
        ("geo-delete",),
        purpose="effect-check",
    )
    for name, api, path in [
        ("database", "ingest.delete_geoip_database", "/_ingest/geoip/database/{database}"),
        ("pipeline", "ingest.delete_pipeline", "/_ingest/pipeline/{pipeline}"),
        ("index", "indices.delete", "/{index}"),
    ]:
        case("cleanup-" + name, api, "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix, focused=False):
    seven = catalog.version in {
        "7.15.2",
        "7.16.3",
        "7.17.29",
        "8.0.1",
        "8.1.3",
        "8.2.3",
        "8.3.3",
        "8.4.3",
        "8.5.3",
        "8.6.2",
        "8.7.1",
        "8.8.2",
        "8.9.2",
        "8.10.4",
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
        "9.2.8",
        "9.3.8",
        "9.4.9",
    }
    values = {
        "index": prefix + "-module",
        "pipeline": prefix + "-simulate",
        "database": prefix + "-geo-config",
    }
    index = values["index"]

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["module." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["module." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]

    def field_reads(data):
        return sum(shard["stats"]["all_fields"]["any"] for shard in data[index]["shards"])

    def database(data):
        return next(item for item in data["databases"] if item["id"] == values["database"])

    def resolve():
        call(
            "resolve-all",
            assertions=[("cluster resolution object", lambda d: isinstance(d, dict), True)],
        )
        call(
            "resolve-index",
            assertions=[
                (
                    "local match",
                    lambda d: any(v.get("matching_indices") is True for v in d.values()),
                    True,
                )
            ],
        )
        call(
            "resolve-missing",
            assertions=[
                (
                    "missing index reported as nested error",
                    lambda d: any("error" in v for v in d.values()),
                    True,
                )
            ],
        )
        call(
            "resolve-missing-lenient",
            assertions=[
                (
                    "lenient resolution has no match",
                    lambda d: any(v.get("matching_indices") is False for v in d.values()),
                    True,
                )
            ],
        )

    def provider():
        call(
            "geo-invalid-name",
            {"name": "GeoLite2-City", "maxmind": {"account_id": "0"}},
            [
                (
                    "unsupported name validation",
                    lambda d: d["error"]["type"],
                    "action_request_validation_exception",
                )
            ],
        )
        config = {"name": "asn", "ipinfo": {}}
        call("geo-create", config, ack)
        for name in ["geo", "location"]:
            for scope in ["all", "named"]:
                call(
                    name + "-get." + scope,
                    assertions=[
                        ("configuration name", lambda d: database(d)["database"]["name"], "asn"),
                        (
                            "provider kind saved",
                            lambda d: "ipinfo" in database(d)["database"],
                            True,
                        ),
                    ],
                    verifies=["geo-create"],
                    semantic=True,
                )
        updated = {"name": "country", "ipinfo": {}}
        call("location-update", updated, ack)
        call(
            "location-readback",
            assertions=[
                (
                    "alias updates same configuration",
                    lambda d: database(d)["database"]["name"],
                    "country",
                ),
                ("version incremented", lambda d: database(d)["version"], 2),
            ],
            verifies=["location-update"],
            semantic=True,
        )
        call("location-noop", updated, ack)
        call(
            "noop-readback",
            assertions=[("noop preserves version", lambda d: database(d)["version"], 2)],
            verifies=["location-noop"],
            semantic=True,
        )
        call("location-delete", assertions=ack)
        call(
            "location-absent",
            assertions=[("removed config not returned", lambda d: d["databases"], [])],
            verifies=["location-delete"],
            semantic=True,
        )
        call("geo-recreate", config, ack)
        call("geo-delete", assertions=ack)
        call(
            "geo-absent",
            assertions=[("configuration absent across alias", lambda d: d["databases"], [])],
            verifies=["geo-delete"],
            semantic=True,
        )

    call(
        "info",
        assertions=[("exact running version", lambda d: d["version"]["number"], catalog.version)],
    )
    call("ping")
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {"n": {"type": "integer"}, "marker": {"type": "keyword"}}},
        },
        ack,
    )
    try:
        if focused:
            resolve()
            provider()
            return
        call("pipeline", {"processors": [{"set": {"field": "marker", "value": "stored"}}]}, ack)
        call("seed", {"n": 1})
        if seven:
            call("source-present")
            call("source-absent")
        response = call(
            "field-before",
            assertions=[("field reads counter", lambda d: field_reads(d) >= 0, True)],
        )
        baseline = field_reads(response.data) if response.passed else 0
        call(
            "field-query",
            {"query": {"range": {"n": {"gte": 1}}}, "sort": [{"n": "asc"}]},
            [("actual matching ID", lambda d: [h["_id"] for h in d["hits"]["hits"]], ["a"])],
        )
        call(
            "field-after",
            assertions=[
                ("search increased tracked field reads", lambda d: field_reads(d) > baseline, True)
            ],
            verifies=["field-query"],
            semantic=True,
        )
        for method in ["get", "post"]:
            for scope in ["global", "index"]:
                rank = {
                    "requests": [
                        {
                            "id": "precision-fixture",
                            "request": {
                                "query": {
                                    "bool": {
                                        "filter": [{"term": {"_index": index}}, {"term": {"n": 1}}]
                                    }
                                },
                                "size": 1,
                            },
                            "ratings": [{"_index": index, "_id": "a", "rating": 1}],
                        }
                    ],
                    "metric": {"precision": {"k": 1, "relevant_rating_threshold": 1}},
                }
                call(
                    "rank." + method + "." + scope,
                    rank,
                    [("precision at one", lambda d: d["metric_score"], 1.0)],
                    semantic=True,
                )
                if seven:
                    continue
                doc = {"_id": "simulated", "_source": {"n": 1}}
                if scope == "global":
                    doc["_index"] = index
                call(
                    "simulate." + method + "." + scope,
                    {
                        "docs": [doc],
                        "pipeline_substitutions": {
                            values["pipeline"]: {
                                "processors": [{"set": {"field": "marker", "value": "simulated"}}]
                            }
                        },
                    },
                    [
                        (
                            "substituted pipeline result",
                            lambda d: d["docs"][0]["doc"]["_source"]["marker"],
                            "simulated",
                        )
                    ],
                    semantic=True,
                )
        if not seven:
            call(
                "pipeline-unchanged",
                assertions=[
                    (
                        "stored pipeline did not change",
                        lambda d: d[values["pipeline"]]["processors"][0]["set"]["value"],
                        "stored",
                    )
                ],
                verifies=[
                    "simulate.get.global",
                    "simulate.get.index",
                    "simulate.post.global",
                    "simulate.post.index",
                ],
                semantic=True,
            )
            call("actual-index", {"n": 2})
            call(
                "actual-readback",
                assertions=[
                    (
                        "actual indexing uses stored pipeline",
                        lambda d: d["_source"]["marker"],
                        "stored",
                    )
                ],
                verifies=["actual-index"],
                semantic=True,
            )
            call("source-present")
            call("source-absent")
            resolve()
        call(
            "grok",
            assertions=[
                (
                    "two requested builtin patterns",
                    lambda d: sorted(d["patterns"]),
                    ["IP", "NUMBER"],
                )
            ],
        )
        call(
            "painless-contexts",
            assertions=[("score context available", lambda d: "score" in d["contexts"], True)],
        )
        call(
            "painless-score",
            assertions=[
                ("requested score context", lambda d: d["name"], "score"),
                ("context classes described", lambda d: len(d["classes"]) > 0, True),
            ],
        )
        call(
            "geo-stats",
            assertions=[("downloader stats object", lambda d: isinstance(d["stats"], dict), True)],
        )
        if not seven:
            provider()
    finally:
        if not seven:
            call("cleanup-database")
        call("cleanup-pipeline")
        call("cleanup-index")
