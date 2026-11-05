"""Elasticsearch 8-only deprecated kNN and explicit v7 REST media contracts."""

from evidence_runner import OMITTED

COMPAT = "application/vnd.elasticsearch+json;compatible-with=7"


def declare(add):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("compat8." + name, api, method, path, expected=expected, purpose=purpose)
        graph["compat8." + name] = tuple("compat8." + d for d in deps)

    case("vector-create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    for name in ["a", "b"]:
        case(
            "vector-" + name,
            "index",
            "PUT",
            "/{index}/_doc/" + name + "?refresh=true",
            ("vector-create",),
            (201,),
        )
    case(
        "vector-count",
        "count",
        "GET",
        "/{index}/_count",
        ("vector-a", "vector-b"),
        purpose="fixture-precondition",
    )
    for method in ["GET", "POST"]:
        for kind in ["nearest", "filtered", "inner-filter-rejected"]:
            case(
                "knn-" + method.lower() + "-" + kind,
                "knn_search",
                method,
                "/{index}/_knn_search",
                ("vector-count",),
                expected=(400,) if kind == "inner-filter-rejected" else (200,),
            )
    case(
        "knn-bad-dimensions",
        "knn_search",
        "POST",
        "/{index}/_knn_search",
        ("vector-count",),
        (400,),
    )
    case(
        "vector-readback",
        "get",
        "GET",
        "/{index}/_doc/a",
        ("knn-bad-dimensions",),
        purpose="effect-check",
    )
    base = "/_template/{template}?template={pattern}"
    case("template-plain", "indices.put_template_with_param", "PUT", base, expected=(400,))
    case(
        "template-plain-absent",
        "indices.get_template",
        "GET",
        "/_template/{template}",
        ("template-plain",),
        (404,),
        "effect-check",
    )
    case("template-put", "indices.put_template_with_param", "PUT", base, ("template-plain-absent",))
    case("template-post", "indices.put_template_with_param", "POST", base, ("template-put",))
    case(
        "template-get",
        "indices.get_template",
        "GET",
        "/_template/{template}",
        ("template-post",),
        purpose="effect-check",
    )
    case("template-apply", "indices.create", "PUT", "/{applied}", ("template-get",))
    case(
        "template-mapping",
        "indices.get_mapping",
        "GET",
        "/{applied}/_mapping",
        ("template-apply",),
        purpose="effect-check",
    )
    for name, api, path in [
        ("cleanup-vector", "indices.delete", "/{index}"),
        ("cleanup-applied", "indices.delete", "/{applied}"),
        ("cleanup-template", "indices.delete_template", "/_template/{template}"),
    ]:
        case(name, api, "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    values = {
        "index": prefix + "-vectors",
        "template": prefix + "-compat",
        "pattern": prefix + "-compat-*",
        "applied": prefix + "-compat-001",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["compat8." + name]
        compatible = name in {"template-put", "template-post"}
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["compat8." + n for n in verifies],
            semantic=semantic,
            content_type=COMPAT if compatible else "application/json",
            headers={"Accept": COMPAT} if compatible else None,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    call(
        "vector-create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "v": {"type": "dense_vector", "dims": 2, "index": True, "similarity": "cosine"},
                    "label": {"type": "keyword"},
                }
            },
        },
        ack,
    )
    try:
        call("vector-a", {"v": [1.0, 0.0], "label": "a"})
        call("vector-b", {"v": [0.0, 1.0], "label": "b"})
        call("vector-count", assertions=[("two actual vector documents", lambda d: d["count"], 2)])
        knn = {"field": "v", "query_vector": [1.0, 0.0], "k": 1, "num_candidates": 2}
        for method in ["get", "post"]:
            call(
                "knn-" + method + "-inner-filter-rejected",
                {"knn": {**knn, "filter": {"term": {"label": "b"}}}},
                [
                    (
                        "legacy knn rejects nested modern filter",
                        lambda d: "unknown field [filter]" in str(d["error"]),
                        True,
                    )
                ],
            )

            call(
                "knn-" + method + "-nearest",
                {"knn": knn},
                [
                    (
                        "nearest actual document",
                        lambda d: [h["_id"] for h in d["hits"]["hits"]],
                        ["a"],
                    ),
                    ("unit cosine score", lambda d: d["hits"]["hits"][0]["_score"] >= 0.99, True),
                ],
                semantic=True,
            )
            call(
                "knn-" + method + "-filtered",
                {"knn": knn, "filter": {"term": {"label": "b"}}},
                [
                    (
                        "filter changes nearest eligible document",
                        lambda d: [h["_id"] for h in d["hits"]["hits"]],
                        ["b"],
                    ),
                ],
                semantic=True,
            )
        call(
            "knn-bad-dimensions",
            {"knn": {**knn, "query_vector": [1.0, 0.0, 0.0]}},
            [
                (
                    "dimension mismatch reported",
                    lambda d: "dimension" in str(d["error"]).lower(),
                    True,
                )
            ],
        )
        call(
            "vector-readback",
            assertions=[
                ("original stored vector", lambda d: d["_source"], {"v": [1.0, 0.0], "label": "a"})
            ],
        )
        template = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {"compat_field": {"type": "keyword"}}},
        }
        call(
            "template-plain",
            template,
            [("default media request rejected", lambda d: bool(d["error"]), True)],
        )
        call("template-plain-absent", verifies=["template-plain"])
        call("template-put", {**template, "version": 1}, ack)
        call("template-post", {**template, "version": 2}, ack)
        call(
            "template-get",
            assertions=[
                ("compat POST version persisted", lambda d: d[values["template"]]["version"], 2),
                (
                    "query template became index pattern",
                    lambda d: d[values["template"]]["index_patterns"],
                    [values["pattern"]],
                ),
            ],
            verifies=["template-put", "template-post"],
            semantic=True,
        )
        call("template-apply", {}, ack)
        call(
            "template-mapping",
            assertions=[
                (
                    "compat template actually applies to new index",
                    lambda d: d[values["applied"]]["mappings"]["properties"]["compat_field"][
                        "type"
                    ],
                    "keyword",
                )
            ],
            verifies=["template-post", "template-apply"],
            semantic=True,
        )
    finally:
        for name in ["cleanup-vector", "cleanup-applied", "cleanup-template"]:
            call(name)
