"""Common wire contracts with real documents and explicit negative readbacks."""

from evidence_runner import OMITTED


def declare(add):
    graph = {}

    def case(
        name,
        api,
        path,
        method="GET",
        expected=(200,),
        deps=(),
        purpose="api-contract",
        unsupported=(),
    ):
        add(
            "wire." + name,
            api,
            method,
            path,
            expected=expected,
            purpose=purpose,
            unsupported=unsupported,
        )
        graph["wire." + name] = tuple("wire." + d for d in deps)

    case("create", "indices.create", "/{index}", "PUT", purpose="fixture-setup")
    for name, identifier in [("odd", "{odd_id}"), ("second", "second")]:
        case(
            "put-" + name,
            "index",
            "/{index}/_doc/" + identifier + "?refresh=true",
            "PUT",
            (201,),
            ("create",),
            "fixture-setup",
        )
    case("odd-readback", "get", "/{index}/_doc/{odd_id}", deps=("put-odd",), purpose="effect-check")
    both = ("put-odd", "put-second")
    for value in ["true", "false"]:
        case("pretty-" + value, "search", "/{index}/_search?pretty=" + value, deps=both)
        case("human-" + value, "indices.stats", "/{index}/_stats/store?human=" + value, deps=both)
    case(
        "pretty-invalid",
        "search",
        "/{index}/_search?pretty=not-a-boolean",
        expected=(400,),
        deps=both,
    )
    case(
        "human-invalid",
        "indices.stats",
        "/{index}/_stats/store?human=not-a-boolean",
        expected=(400,),
        deps=both,
    )
    case(
        "filter-include",
        "search",
        "/{index}/_search?filter_path=hits.total,hits.hits._id",
        deps=both,
    )
    case(
        "filter-exclude",
        "search",
        "/{index}/_search?filter_path=hits.hits.*,-hits.hits._source",
        deps=both,
    )
    for suffix, query in [
        ("omitted", ""),
        ("true", "?error_trace=true"),
        ("false", "?error_trace=false"),
    ]:
        case(
            "error-trace-" + suffix,
            "search",
            "/{index}/_search" + query,
            expected=(400,),
            deps=both,
        )
    for name in ["omitted", "null", "false", "malformed"]:
        case(
            "body-" + name,
            "search",
            "/{index}/_search",
            "POST",
            (200,) if name == "omitted" else (400,),
            both,
        )
    case(
        "unknown-param",
        "search",
        "/{index}/_search?es_cli_unknown_probe=true",
        expected=(400,),
        deps=both,
        unsupported=("es_cli_unknown_probe",),
    )
    case("wrong-content-type", "index", "/{index}/_doc/rejected", "PUT", (406,), ("create",))
    case(
        "rejected-absent",
        "get",
        "/{index}/_doc/rejected",
        expected=(404,),
        deps=("wrong-content-type",),
        purpose="effect-check",
    )
    case("cleanup", "indices.delete", "/{index}", "DELETE", (200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {"index": prefix + "-wire", "odd_id": "space /雪?#%+"}

    def call(
        name,
        body=OMITTED,
        assertions=(),
        verifies=(),
        semantic=False,
        content_type="application/json",
    ):
        spec = catalog.cases["wire." + name]
        result = catalog.execute(
            run,
            spec.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=spec.dependency_plan,
            verifies=["wire." + n for n in verifies],
            semantic=semantic,
            content_type=content_type,
        )
        print(spec.id, result.state, result.status, flush=True)
        return result

    def total(data):
        value = data["hits"]["total"]
        return value["value"] if isinstance(value, dict) else value

    def structured_error(data):
        return isinstance(data.get("error"), dict)

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {"n": {"type": "integer"}, "label": {"type": "keyword"}}},
        },
        [("acknowledged", lambda d: d["acknowledged"], True)],
    )
    try:
        call("put-odd", {"n": 1, "label": "привет / ? # % +"})
        call("put-second", {"n": 2, "label": "second"})
        call(
            "odd-readback",
            assertions=[
                ("encoded ID round trip", lambda d: d["_id"], values["odd_id"]),
                (
                    "unicode source round trip",
                    lambda d: d["_source"],
                    {"n": 1, "label": "привет / ? # % +"},
                ),
            ],
            verifies=["put-odd"],
            semantic=True,
        )
        for value in ["true", "false"]:
            call("pretty-" + value, assertions=[("same two documents", total, 2)])
            call(
                "human-" + value,
                assertions=[
                    (
                        "numeric bytes always available",
                        lambda d: type(d["_all"]["primaries"]["store"]["size_in_bytes"]).__name__,
                        "int",
                    ),
                    (
                        "human size presence",
                        lambda d: "size" in d["_all"]["primaries"]["store"],
                        value == "true",
                    ),
                ],
            )
        for name in ["pretty-invalid", "human-invalid"]:
            call(name, assertions=[("structured error", structured_error, True)])
        call(
            "filter-include",
            assertions=[
                ("only hits at root", lambda d: sorted(d), ["hits"]),
                ("selected total", total, 2),
                (
                    "only IDs in both hits",
                    lambda d: [sorted(h) for h in d["hits"]["hits"]],
                    [["_id"], ["_id"]],
                ),
            ],
        )
        call(
            "filter-exclude",
            assertions=[
                (
                    "both IDs remain",
                    lambda d: sorted(h["_id"] for h in d["hits"]["hits"]),
                    sorted([values["odd_id"], "second"]),
                ),
                (
                    "sources excluded",
                    lambda d: any("_source" in h for h in d["hits"]["hits"]),
                    False,
                ),
            ],
        )
        for suffix in ["omitted", "true", "false"]:
            call(
                "error-trace-" + suffix,
                {"query": {"es_cli_unknown_query": {}}},
                [
                    ("structured error", structured_error, True),
                    (
                        "stack trace presence",
                        lambda d: "stack_trace" in d["error"],
                        suffix == "true",
                    ),
                ],
            )
        for name, body in [
            ("omitted", OMITTED),
            ("null", None),
            ("false", False),
            ("malformed", b'{"query":'),
        ]:
            call(
                "body-" + name,
                body,
                [("two documents with omitted body", total, 2)]
                if name == "omitted"
                else [("structured body rejection", structured_error, True)],
            )
        call(
            "unknown-param",
            assertions=[
                ("structured error", structured_error, True),
                (
                    "unknown name appears in error",
                    lambda d: "es_cli_unknown_probe" in d["error"]["reason"],
                    True,
                ),
            ],
        )
        call(
            "wrong-content-type",
            {"n": 3},
            [("structured error", structured_error, True)],
            content_type="text/plain",
        )
        call(
            "rejected-absent",
            assertions=[("rejected write did not create document", lambda d: d["found"], False)],
            verifies=["wrong-content-type"],
            semantic=True,
        )
    finally:
        call("cleanup")
