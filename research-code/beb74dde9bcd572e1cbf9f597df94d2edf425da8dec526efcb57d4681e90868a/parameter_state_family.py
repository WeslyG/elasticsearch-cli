"""Pinned ES7/8/9 settings/search parameter semantics with owned data and independent checks."""

from urllib.parse import urlencode

from evidence_runner import OMITTED

ES7_PARAMETER_RELEASES = {"7.0.1", "7.1.1", "7.2.1", "7.3.2", "7.17.29"}
PREPARED_VERSIONS = ES7_PARAMETER_RELEASES | {"8.19.24", "9.5.6"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(
        name, api, method, path, deps=(), expected=(200,), dimensions=(), purpose="api-contract"
    ):
        identifier = "parameter-state." + name
        add(
            identifier,
            api,
            method,
            path,
            expected=expected,
            dimensions=dimensions or ("response.success",),
            purpose=purpose,
        )
        graph[identifier] = tuple("parameter-state." + item for item in deps)

    def settings(name, query="", deps=("create",), expected=(200,), path="/{index}/_settings"):
        case(
            name,
            "indices.get_settings",
            "GET",
            path + query,
            deps,
            expected,
            ("query.indices.get_settings", "response.settings-shape"),
        )

    def search(name, query="", expected=(200,), deps=("count",)):
        case(
            name,
            "search",
            "POST",
            "/{index}/_search" + query,
            deps,
            expected,
            ("query.search", "response.search-shape"),
        )

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    settings("settings-omitted")
    settings("settings-flat-true", "?flat_settings=true")
    settings("settings-flat-false", "?flat_settings=false")
    settings("settings-defaults-true", "?include_defaults=true")
    settings("settings-defaults-false", "?include_defaults=false")
    settings("settings-flat-defaults", "?flat_settings=true&include_defaults=true")
    settings(
        "settings-ignore-true", "?ignore_unavailable=true", path="/{index},{missing}/_settings"
    )
    settings(
        "settings-ignore-false",
        "?ignore_unavailable=false",
        expected=(404,),
        path="/{index},{missing}/_settings",
    )
    settings("settings-wild-true", "?allow_no_indices=true", path="/{missing}*/_settings")
    settings(
        "settings-wild-false",
        "?allow_no_indices=false",
        expected=(404,),
        path="/{missing}*/_settings",
    )
    settings("settings-bad-flat", "?flat_settings=not-a-boolean", expected=(400,))
    case(
        "preserve-true",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings?preserve_existing=true",
        ("create",),
        dimensions=("query.preserve_existing",),
    )
    settings("preserve-true-effect", deps=("preserve-true",))
    case(
        "preserve-false",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings?preserve_existing=false",
        ("preserve-true-effect",),
        dimensions=("query.preserve_existing",),
    )
    settings("preserve-false-effect", deps=("preserve-false",))
    case(
        "preserve-bad",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings?preserve_existing=not-a-boolean",
        ("create",),
        (400,),
        ("query.preserve_existing.invalid",),
    )
    settings("preserve-bad-effect", deps=("preserve-bad",))
    case(
        "restore-refresh",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings",
        purpose="fixture-setup",
    )
    case("closed-create", "indices.create", "PUT", "/{closed}", purpose="fixture-setup")
    case(
        "close",
        "indices.close",
        "POST",
        "/{closed}/_close",
        ("closed-create",),
        purpose="fixture-setup",
    )
    for mode in ["open", "closed", "all", "none"]:
        settings(
            "expand-" + mode,
            "?expand_wildcards=" + mode,
            ("close",),
            (404,) if mode == "none" and version not in ES7_PARAMETER_RELEASES else (200,),
            "/{stem}*/_settings",
        )
    case(
        "seed",
        "bulk",
        "POST",
        "/{index}/_bulk?refresh=true",
        ("restore-refresh",),
        dimensions=("body.ndjson",),
        purpose="fixture-setup",
    )
    case("count", "count", "GET", "/{index}/_count", ("seed",), purpose="fixture-precondition")
    for name, query in [
        ("search-default", ""),
        ("window", "?from=5&size=3"),
        ("size-zero", "?size=0"),
        ("source-false", "?_source=false"),
        ("source-true", "?_source=true"),
        ("source-includes", "?_source_includes=n,category"),
        ("source-excludes", "?_source_excludes=note,stored"),
        ("source-interaction", "?_source_includes=n,category&_source_excludes=category"),
        ("stored-only", "?stored_fields=stored"),
        ("stored-and-source", "?stored_fields=stored&_source=true"),
        ("seq-true", "?seq_no_primary_term=true"),
        ("seq-false", "?seq_no_primary_term=false"),
        ("version-true", "?version=true"),
        ("version-false", "?version=false"),
        ("total-true", "?track_total_hits=true"),
        ("total-false", "?track_total_hits=false"),
        ("total-ten", "?track_total_hits=10"),
        ("total-zero", "?track_total_hits=0"),
        ("total-int", "?rest_total_hits_as_int=true&track_total_hits=true"),
        ("total-int-disabled", "?rest_total_hits_as_int=true&track_total_hits=false"),
        ("typed-keys-true", "?typed_keys=true"),
        ("typed-keys-false", "?typed_keys=false"),
        ("scores-true", "?track_scores=true"),
        ("scores-false", "?track_scores=false"),
        ("terminate-one", "?terminate_after=1&size=20"),
        ("terminate-zero", "?terminate_after=0&size=20"),
        ("query-string", "?" + urlencode({"q": "n:[5 TO 7]", "sort": "n:asc"})),
        ("explain-true", "?explain=true&track_scores=true"),
        ("explain-false", "?explain=false&track_scores=true"),
        ("profile-true", ""),
        ("profile-false", ""),
        ("size-sentinel", "?size=-1"),
        ("from-sentinel", "?from=-1"),
        ("size-sentinel-body", "?size=-1"),
        ("from-sentinel-body", "?from=-1"),
    ]:
        search(
            name,
            query,
            (400,) if version not in ES7_PARAMETER_RELEASES and "sentinel" in name else (200,),
        )
    for name, query in [
        ("bad-size", "?size=-2"),
        ("bad-from", "?from=-2"),
        ("bad-terminate", "?terminate_after=-1"),
        ("bad-total", "?track_total_hits=not-a-number"),
        ("bad-seq", "?seq_no_primary_term=not-a-boolean"),
        ("total-int-conflict", "?rest_total_hits_as_int=true&track_total_hits=10"),
    ]:
        search(name, query, (400,))
    case(
        "metadata-read",
        "get",
        "GET",
        "/{index}/_doc/0",
        ("seq-true", "version-true"),
        purpose="effect-check",
    )
    case(
        "explain-read",
        "explain",
        "GET",
        "/{index}/_explain/0",
        ("explain-true",),
        purpose="effect-check",
    )
    for name in ["cache-before", "cache-after-first", "cache-after-second", "cache-after-disabled"]:
        case(
            name,
            "indices.stats",
            "GET",
            "/{index}/_stats/request_cache",
            ("count",),
            purpose="effect-check",
        )
    search("cache-first", "?request_cache=true")
    search("cache-second", "?request_cache=true")
    search("cache-disabled", "?request_cache=false")
    for request, stats, previous in [
        ("cache-first", "cache-after-first", "cache-before"),
        ("cache-second", "cache-after-second", "cache-after-first"),
        ("cache-disabled", "cache-after-disabled", "cache-after-second"),
    ]:
        graph["parameter-state." + request] = ("parameter-state." + previous,)
        graph["parameter-state." + stats] = (
            "parameter-state." + request,
            "parameter-state.cache-before",
        )
    case("count-after", "count", "GET", "/{index}/_count", ("count",), purpose="effect-check")
    for name in ["index", "closed"]:
        case(
            "cleanup-" + name,
            "indices.delete",
            "DELETE",
            "/{" + name + "}",
            expected=(200, 404),
            purpose="cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Parameter fixture is not prepared for this exact release")
    stem = prefix + "-parameters"
    values = {
        "index": stem + "-open",
        "closed": stem + "-closed",
        "missing": stem + "-absent",
        "stem": stem,
    }

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        case = catalog.cases["parameter-state." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            content_type=content_type,
            verifies=["parameter-state." + item for item in verifies],
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def hits(data):
        return data["hits"]["hits"]

    def numbers(data):
        return [hit["_source"]["n"] for hit in hits(data)]

    def refresh_interval(data):
        return data[values["index"]]["settings"]["index"]["refresh_interval"]

    def error_is_named(data, value):
        error = data["error"]
        return (
            isinstance(error.get("type"), str) and bool(error["type"]) and value in error["reason"]
        )

    def no_source(data):
        return all("_source" not in hit for hit in hits(data)) and bool(hits(data))

    def exact_source_fields(data, fields):
        return all(set(hit["_source"]) == set(fields) for hit in hits(data)) and bool(hits(data))

    def aggregate_counts(data):
        return {
            bucket["key"]: bucket["doc_count"]
            for bucket in next(iter(data["aggregations"].values()))["buckets"]
        }

    def cache_counters(data):
        return data["indices"][values["index"]]["primaries"]["request_cache"]

    baseline = {"query": {"match_all": {}}, "sort": [{"n": "asc"}]}
    scored = {"query": {"term": {"category": "even"}}, "sort": [{"n": "asc"}], "size": 20}
    aggregates = {"size": 0, "aggs": {"by_category": {"terms": {"field": "category", "size": 10}}}}
    cached_query = {
        "size": 0,
        "query": {"term": {"category": "even"}},
        "aggs": {"cached_categories": {"terms": {"field": "category", "size": 10}}},
    }
    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"},
            "mappings": {
                "properties": {
                    "n": {"type": "integer", "store": True},
                    "category": {"type": "keyword"},
                    "stored": {"type": "keyword", "store": True},
                    "note": {"type": "text"},
                }
            },
        },
        assertions=[("fixture index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        call(
            "settings-omitted",
            assertions=[
                ("explicit setting readable", refresh_interval, "-1"),
                (
                    "defaults omitted by default",
                    lambda data: "defaults" not in data[values["index"]],
                    True,
                ),
            ],
            semantic=True,
        )
        call(
            "settings-flat-true",
            assertions=[
                (
                    "flat setting key",
                    lambda data: data[values["index"]]["settings"]["index.refresh_interval"],
                    "-1",
                )
            ],
            semantic=True,
        )
        call(
            "settings-flat-false",
            assertions=[("explicit false preserves nested shape", refresh_interval, "-1")],
            semantic=True,
        )
        call(
            "settings-defaults-true",
            assertions=[
                (
                    "unconfigured real default exposed",
                    lambda data: data[values["index"]]["defaults"]["index"]["max_result_window"],
                    "10000",
                )
            ],
            semantic=True,
        )
        call(
            "settings-defaults-false",
            assertions=[
                (
                    "explicit false omits defaults",
                    lambda data: "defaults" not in data[values["index"]],
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "settings-flat-defaults",
            assertions=[
                (
                    "default and flatten parameters interact",
                    lambda data: data[values["index"]]["defaults"]["index.max_result_window"],
                    "10000",
                )
            ],
            semantic=True,
        )
        call(
            "settings-ignore-true",
            assertions=[
                (
                    "missing literal dropped, owned index retained",
                    lambda data: sorted(data),
                    [values["index"]],
                )
            ],
            semantic=True,
        )
        call(
            "settings-ignore-false",
            assertions=[
                (
                    "missing literal rejected",
                    lambda data: data["error"]["type"],
                    "index_not_found_exception",
                )
            ],
        )
        call(
            "settings-wild-true",
            assertions=[("unmatched wildcard accepted as empty", lambda data: data, {})],
            semantic=True,
        )
        call(
            "settings-wild-false",
            assertions=[
                (
                    "unmatched wildcard rejected",
                    lambda data: data["error"]["type"],
                    "index_not_found_exception",
                )
            ],
        )
        call(
            "settings-bad-flat",
            assertions=[
                (
                    "invalid flat boolean identifies value",
                    lambda data: error_is_named(data, "not-a-boolean"),
                    True,
                )
            ],
        )
        call("preserve-true", {"index": {"refresh_interval": "30s"}})
        call(
            "preserve-true-effect",
            assertions=[("preserve_existing=true keeps explicit value", refresh_interval, "-1")],
            verifies=["preserve-true"],
            semantic=True,
        )
        call("preserve-false", {"index": {"refresh_interval": "30s"}})
        call(
            "preserve-false-effect",
            assertions=[("preserve_existing=false updates value", refresh_interval, "30s")],
            verifies=["preserve-false"],
            semantic=True,
        )
        call(
            "preserve-bad",
            {"index": {"refresh_interval": "60s"}},
            assertions=[
                (
                    "bad preserve boolean rejected",
                    lambda data: error_is_named(data, "not-a-boolean"),
                    True,
                )
            ],
        )
        call(
            "preserve-bad-effect",
            assertions=[("rejected update leaves setting unchanged", refresh_interval, "30s")],
            verifies=["preserve-bad"],
            semantic=True,
        )
        call("restore-refresh", {"index": {"refresh_interval": "-1"}})
        call("closed-create", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
        call(
            "close",
            assertions=[
                ("second owned index actually closed", lambda data: data["acknowledged"], True)
            ],
        )
        for mode, expected in [
            ("open", [values["index"]]),
            ("closed", [values["closed"]]),
            ("all", [values["index"], values["closed"]]),
        ]:
            call(
                "expand-" + mode,
                assertions=[
                    ("actual wildcard state selection", lambda data: sorted(data), sorted(expected))
                ],
                semantic=True,
            )
        call(
            "expand-none",
            assertions=[("ES7 none yields empty selection in get settings", lambda data: data, {})]
            if catalog.version in ES7_PARAMETER_RELEASES
            else [
                (
                    "native modern none rejects unexpanded wildcard",
                    lambda data: data["error"]["type"],
                    "index_not_found_exception",
                )
            ],
        )
        lines = []
        for number in range(20):
            lines.extend(
                [
                    '{"index":{"_id":"' + str(number) + '"}}',
                    '{"n":'
                    + str(number)
                    + ',"category":"'
                    + ("even" if number % 2 == 0 else "odd")
                    + '","stored":"value-'
                    + str(number)
                    + '","note":"alpha beta"}',
                ]
            )
        call(
            "seed",
            ("\n".join(lines) + "\n").encode(),
            content_type="application/x-ndjson",
            assertions=[
                ("all real documents indexed", lambda data: len(data["items"]), 20),
                ("bulk no partial errors", lambda data: data["errors"], False),
            ],
        )
        call(
            "count",
            assertions=[("twenty real searchable documents", lambda data: data["count"], 20)],
        )
        call(
            "search-default",
            baseline,
            assertions=[
                ("omitted size returns default ten", numbers, list(range(10))),
                (
                    "small default total is exact",
                    lambda data: data["hits"]["total"],
                    {"value": 20, "relation": "eq"},
                ),
                (
                    "seq metadata absent by default",
                    lambda data: all(
                        "_seq_no" not in hit and "_primary_term" not in hit for hit in hits(data)
                    ),
                    True,
                ),
                (
                    "versions absent by default",
                    lambda data: all("_version" not in hit for hit in hits(data)),
                    True,
                ),
            ],
            semantic=True,
        )
        call(
            "window",
            baseline,
            assertions=[("from and size select actual window", numbers, [5, 6, 7])],
            semantic=True,
        )
        call(
            "size-zero",
            baseline,
            assertions=[
                ("explicit zero has no hits", lambda data: hits(data), []),
                ("zero still counts documents", lambda data: data["hits"]["total"]["value"], 20),
            ],
            semantic=True,
        )
        call(
            "source-false",
            baseline,
            assertions=[("source false omits source", no_source, True)],
            semantic=True,
        )
        call(
            "source-true",
            baseline,
            assertions=[
                (
                    "source true has full field set",
                    lambda data: exact_source_fields(data, ["n", "category", "stored", "note"]),
                    True,
                )
            ],
            semantic=True,
        )
        for name in ["source-includes", "source-excludes"]:
            call(
                name,
                baseline,
                assertions=[
                    (
                        "source projection actual fields",
                        lambda data: exact_source_fields(data, ["n", "category"]),
                        True,
                    )
                ],
                semantic=True,
            )
        call(
            "source-interaction",
            baseline,
            assertions=[
                (
                    "exclude wins over included category",
                    lambda data: exact_source_fields(data, ["n"]),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "stored-only",
            baseline,
            assertions=[
                (
                    "stored value returned",
                    lambda data: hits(data)[0]["fields"]["stored"],
                    ["value-0"],
                ),
                ("stored_fields disables default source", no_source, True),
            ],
            semantic=True,
        )
        call(
            "stored-and-source",
            baseline,
            assertions=[
                (
                    "both stored field and source agree",
                    lambda data: [hits(data)[0]["fields"]["stored"], hits(data)[0]["_source"]["n"]],
                    [["value-0"], 0],
                )
            ],
            semantic=True,
        )
        sequence = call(
            "seq-true",
            baseline,
            assertions=[
                (
                    "sequence and term available",
                    lambda data: (
                        bool(hits(data))
                        and all(
                            type(hit["_seq_no"]) is int
                            and type(hit["_primary_term"]) is int
                            and hit["_primary_term"] >= 1
                            for hit in hits(data)
                        )
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "seq-false",
            baseline,
            assertions=[
                (
                    "explicit false omits sequence metadata",
                    lambda data: all(
                        "_seq_no" not in hit and "_primary_term" not in hit for hit in hits(data)
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        versioned = call(
            "version-true",
            baseline,
            assertions=[
                (
                    "initial versions returned",
                    lambda data: [hit["_version"] for hit in hits(data)],
                    [1] * 10,
                )
            ],
            semantic=True,
        )
        call(
            "version-false",
            baseline,
            assertions=[
                (
                    "explicit false omits versions",
                    lambda data: all("_version" not in hit for hit in hits(data)),
                    True,
                )
            ],
            semantic=True,
        )
        metadata = sequence.data["hits"]["hits"][0] if sequence.state == "passed" else {}
        version = (
            versioned.data["hits"]["hits"][0].get("_version")
            if versioned.state == "passed"
            else None
        )
        call(
            "metadata-read",
            assertions=[
                (
                    "independent sequence matches search",
                    lambda data: data["_seq_no"],
                    metadata.get("_seq_no"),
                ),
                (
                    "independent primary term matches",
                    lambda data: data["_primary_term"],
                    metadata.get("_primary_term"),
                ),
                ("independent version matches", lambda data: data["_version"], version),
            ],
            verifies=["seq-true", "version-true"],
            semantic=True,
        )
        call(
            "total-true",
            baseline,
            assertions=[
                (
                    "accurate count enabled",
                    lambda data: data["hits"]["total"],
                    {"value": 20, "relation": "eq"},
                )
            ],
            semantic=True,
        )
        call(
            "total-false",
            baseline,
            assertions=[
                ("false omits total object", lambda data: "total" not in data["hits"], True)
            ],
            semantic=True,
        )
        call(
            "total-ten",
            baseline,
            assertions=[
                (
                    "integer produces lower bound",
                    lambda data: data["hits"]["total"]["relation"],
                    "gte",
                ),
                (
                    "bounded count below full twenty",
                    lambda data: 10 <= data["hits"]["total"]["value"] < 20,
                    True,
                ),
            ],
            semantic=True,
        )
        call(
            "total-zero",
            baseline,
            assertions=[
                (
                    "zero is numeric lower bound, not false",
                    lambda data: (
                        isinstance(data["hits"].get("total"), dict)
                        and data["hits"]["total"]["relation"] == "gte"
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "total-int",
            baseline,
            assertions=[("legacy integer output", lambda data: data["hits"]["total"], 20)],
            semantic=True,
        )
        call(
            "total-int-disabled",
            baseline,
            assertions=[
                ("disabled integer uses minus-one sentinel", lambda data: data["hits"]["total"], -1)
            ],
            semantic=True,
        )
        for name, typed in [("typed-keys-true", True), ("typed-keys-false", False)]:
            call(
                name,
                aggregates,
                assertions=[
                    (
                        "aggregation name prefix follows flag",
                        lambda data, typed=typed: (
                            next(iter(data["aggregations"])).endswith("#by_category")
                            if typed
                            else set(data["aggregations"]) == {"by_category"}
                        ),
                        True,
                    ),
                    ("actual category counts retained", aggregate_counts, {"even": 10, "odd": 10}),
                ],
                semantic=True,
            )
        call(
            "scores-false",
            scored,
            assertions=[
                ("ten real even documents", numbers, list(range(0, 20, 2))),
                (
                    "field sort does not track scores",
                    lambda data: all(hit["_score"] is None for hit in hits(data)),
                    True,
                ),
            ],
            semantic=True,
        )
        call(
            "scores-true",
            scored,
            assertions=[
                ("ten real even documents", numbers, list(range(0, 20, 2))),
                (
                    "explicit scores positive",
                    lambda data: all(
                        isinstance(hit["_score"], (int, float))
                        and not isinstance(hit["_score"], bool)
                        and hit["_score"] > 0
                        for hit in hits(data)
                    ),
                    True,
                ),
            ],
            semantic=True,
        )
        call(
            "terminate-one",
            baseline,
            assertions=[
                ("single shard terminated early", lambda data: data["terminated_early"], True),
                ("only one collected document", lambda data: len(hits(data)), 1),
            ],
            semantic=True,
        )
        call(
            "terminate-zero",
            baseline,
            assertions=[("zero disables termination", numbers, list(range(20)))],
            semantic=True,
        )
        call(
            "query-string",
            assertions=[("URL-encoded query and sort values", numbers, [5, 6, 7])],
            semantic=True,
        )
        explained = call(
            "explain-true",
            scored,
            assertions=[
                (
                    "all matched hits have explanations",
                    lambda data: (
                        bool(hits(data)) and all("_explanation" in hit for hit in hits(data))
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "explain-false",
            scored,
            assertions=[
                (
                    "explicit false omits explanations",
                    lambda data: all("_explanation" not in hit for hit in hits(data)),
                    True,
                )
            ],
            semantic=True,
        )
        explanation = (
            explained.data["hits"]["hits"][0].get("_explanation", {}).get("value")
            if explained.state == "passed"
            else None
        )
        call(
            "explain-read",
            {"query": {"term": {"category": "even"}}},
            assertions=[
                (
                    "independent explain value agrees",
                    lambda data: data["explanation"]["value"],
                    explanation,
                )
            ],
            verifies=["explain-true"],
            semantic=True,
        )
        call(
            "profile-true",
            {**baseline, "profile": True},
            assertions=[
                (
                    "profile identifies owned shard",
                    lambda data: (
                        len(data["profile"]["shards"]) == 1
                        and values["index"] in data["profile"]["shards"][0]["id"]
                    ),
                    True,
                )
            ],
            semantic=True,
        )
        call(
            "profile-false",
            {**baseline, "profile": False},
            assertions=[("false omits profile", lambda data: "profile" not in data, True)],
            semantic=True,
        )
        if catalog.version in ES7_PARAMETER_RELEASES:
            for name in ["size-sentinel", "from-sentinel"]:
                call(
                    name,
                    baseline,
                    assertions=[("sentinel preserves default window", numbers, list(range(10)))],
                    semantic=True,
                )
            for name in ["size-sentinel-body", "from-sentinel-body"]:
                call(
                    name,
                    {**baseline, "from": 5, "size": 3},
                    assertions=[("sentinel preserves body window", numbers, [5, 6, 7])],
                    semantic=True,
                )
        else:
            for name in [
                "size-sentinel",
                "from-sentinel",
                "size-sentinel-body",
                "from-sentinel-body",
            ]:
                body = {**baseline, "from": 5, "size": 3} if name.endswith("-body") else baseline
                field = "size" if name.startswith("size-") else "from"
                call(
                    name,
                    body,
                    assertions=[
                        (
                            "native modern rejects negative pagination despite body",
                            lambda data, field=field: (
                                data["error"]["type"] == "illegal_argument_exception"
                                and field in data["error"]["reason"]
                            ),
                            True,
                        )
                    ],
                )
        for name, value in [
            ("bad-size", "-2"),
            ("bad-total", "not-a-number"),
            ("bad-seq", "not-a-boolean"),
        ]:
            call(
                name,
                baseline,
                assertions=[
                    (
                        "bad value explicitly rejected",
                        lambda data, value=value: error_is_named(data, value),
                        True,
                    )
                ],
            )
        call(
            "bad-from",
            baseline,
            assertions=[
                (
                    "negative from rejected by named field",
                    lambda data: (
                        data["error"]["type"] == "illegal_argument_exception"
                        and data["error"]["reason"]
                        == (
                            "[from] parameter cannot be negative"
                            if catalog.version in ES7_PARAMETER_RELEASES
                            else "[from] parameter cannot be negative but was [-2]"
                        )
                    ),
                    True,
                )
            ],
        )
        call(
            "bad-terminate",
            baseline,
            assertions=[
                (
                    "negative terminate_after rejected",
                    lambda data: (
                        data["error"]["type"] == "illegal_argument_exception"
                        and "terminate" in data["error"]["reason"].lower()
                    ),
                    True,
                )
            ],
        )
        call(
            "total-int-conflict",
            baseline,
            assertions=[
                (
                    "integer output refuses inexact threshold",
                    lambda data: (
                        data["error"]["type"] == "illegal_argument_exception"
                        and "rest_total_hits_as_int" in data["error"]["reason"]
                    ),
                    True,
                )
            ],
        )
        before = call(
            "cache-before",
            assertions=[
                (
                    "request-cache counters available",
                    lambda data: (
                        type(cache_counters(data)["hit_count"]) is int
                        and type(cache_counters(data)["miss_count"]) is int
                    ),
                    True,
                )
            ],
        )
        counters = cache_counters(before.data) if before.state == "passed" else {}
        expected_hit, expected_miss = counters.get("hit_count"), counters.get("miss_count")
        for request, stats, hit_delta, miss_delta in [
            ("cache-first", "cache-after-first", 0, 1),
            ("cache-second", "cache-after-second", 1, 1),
            ("cache-disabled", "cache-after-disabled", 1, 1),
        ]:
            call(
                request,
                cached_query,
                assertions=[("cache request actual result", aggregate_counts, {"even": 10})],
            )
            call(
                stats,
                assertions=[
                    (
                        "actual request cache hit delta",
                        lambda data: cache_counters(data)["hit_count"] - expected_hit,
                        hit_delta,
                    ),
                    (
                        "actual request cache miss delta",
                        lambda data: cache_counters(data)["miss_count"] - expected_miss,
                        miss_delta,
                    ),
                ],
                verifies=[request],
                semantic=True,
            )
        call(
            "count-after",
            assertions=[("all reads preserve twenty documents", lambda data: data["count"], 20)],
            semantic=True,
        )
    finally:
        call("cleanup-index")
        call("cleanup-closed")
