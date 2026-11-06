"""Elasticsearch 8-only deprecated kNN and explicit v7 REST media contracts."""

from evidence_runner import OMITTED

COMPAT = "application/vnd.elasticsearch+json;compatible-with=7"


def declare(add, version="8.19.24"):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if version in {"8.0.1", "8.1.3", "8.2.3", "8.3.3"} and (
            name.startswith(("vector-", "knn-")) or name == "cleanup-vector"
        ):
            return
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
    if version in {
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
    }:
        for method in ["GET", "POST"]:
            case(
                "modern-" + method.lower(), "search", method, "/{index}/_search", ("vector-count",)
            )
        case(
            "modern-search-type",
            "search",
            "POST",
            "/{index}/_search?search_type=query_then_fetch",
            ("vector-count",),
            (400,),
        )
    if version in {
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
    }:
        for method in ["GET", "POST"]:
            case(
                "synthetic-" + method.lower(),
                "search",
                method,
                "/{index}/_search?force_synthetic_source=true",
                ("vector-count",),
            )
        case(
            "vector-mapping",
            "indices.get_mapping",
            "GET",
            "/{index}/_mapping",
            ("vector-count",),
            purpose="effect-check",
        )
    if version in {"8.7.1", "8.8.2", "8.9.2", "8.10.4", "8.11.4", "8.12.2", "8.13.4", "8.14.3"}:
        for method in ["GET", "POST"]:
            case(
                "multi-knn-" + method.lower(),
                "search",
                method,
                "/{index}/_search",
                ("vector-count",),
            )
        case(
            "multi-knn-array-error", "search", "POST", "/{index}/_search", ("vector-count",), (400,)
        )
        case("knn-vector-required", "search", "POST", "/{index}/_search", ("vector-count",), (400,))
    if version in {"8.8.2", "8.9.2", "8.10.4", "8.11.4", "8.12.2", "8.13.4", "8.14.3"}:
        for method in ["GET", "POST"]:
            case(
                "similarity-" + method.lower(),
                "search",
                method,
                "/{index}/_search",
                ("vector-count",),
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
    for name in ["voting-plain", "voting-compatible"]:
        case(
            name,
            "cluster.post_voting_config_exclusions_with_node_name_part",
            "POST",
            "/_cluster/voting_config_exclusions/{node_name}",
            expected=(400,),
        )
    case(
        "voting-preserved",
        "cluster.state",
        "GET",
        "/_cluster/state/metadata?filter_path=metadata.cluster_coordination",
        ("voting-plain", "voting-compatible"),
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
    focused = catalog.version in {"8.0.1", "8.1.3", "8.2.3", "8.3.3"}
    values = {
        "index": prefix + "-vectors",
        "template": prefix + "-compat",
        "pattern": prefix + "-compat-*",
        "applied": prefix + "-compat-001",
        "node_name": prefix + "-absent-node",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["compat8." + name]
        compatible = name in {"template-put", "template-post", "voting-compatible"}
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
    if not focused:
        call(
            "vector-create",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "v": {
                            "type": "dense_vector",
                            "dims": 2,
                            "index": True,
                            "similarity": "cosine",
                        },
                        "label": {"type": "keyword"},
                    }
                },
            },
            ack,
        )
    try:
        if not focused:
            call("vector-a", {"v": [1.0, 0.0], "label": "a"})
            call("vector-b", {"v": [0.0, 1.0], "label": "b"})
            call(
                "vector-count",
                assertions=[("two actual vector documents", lambda d: d["count"], 2)],
            )
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
                        (
                            "unit cosine score",
                            lambda d: d["hits"]["hits"][0]["_score"] >= 0.99,
                            True,
                        ),
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
                    (
                        "original stored vector",
                        lambda d: d["_source"],
                        {"v": [1.0, 0.0], "label": "a"},
                    )
                ],
            )
        if catalog.version in {
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
        }:
            for method in ["get", "post"]:
                call(
                    "modern-" + method,
                    {"knn": {**knn, "filter": {"term": {"label": "b"}}}},
                    [
                        (
                            "modern knn filter changes eligible nearest",
                            lambda d: [h["_id"] for h in d["hits"]["hits"]],
                            ["b"],
                        )
                    ],
                    semantic=True,
                )
            call(
                "modern-search-type",
                {"knn": knn},
                [
                    (
                        "explicit search_type with knn rejected",
                        lambda d: (
                            "cannot set [search_type] when using [knn] search" in str(d["error"])
                        ),
                        True,
                    )
                ],
            )
        if catalog.version in {
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
        }:
            for method in ["get", "post"]:
                call(
                    "synthetic-" + method,
                    {"query": {"ids": {"values": ["a"]}}, "size": 1},
                    [
                        (
                            "synthetic vector document identity",
                            lambda d: [h["_id"] for h in d["hits"]["hits"]],
                            ["a"],
                        ),
                        (
                            "synthetic vector source matches stored original",
                            lambda d: d["hits"]["hits"][0]["_source"],
                            {"label": "a", "v": [1.0, 0.0]},
                        ),
                    ],
                    verifies=["vector-a"],
                    semantic=True,
                )
            call(
                "vector-mapping",
                assertions=[
                    (
                        "vector mapping dims preserved",
                        lambda d: d[values["index"]]["mappings"]["properties"]["v"]["dims"],
                        2,
                    ),
                    (
                        "vector mapping indexed",
                        lambda d: d[values["index"]]["mappings"]["properties"]["v"]["index"],
                        True,
                    ),
                ],
                verifies=["vector-create"],
                semantic=True,
            )
        if catalog.version in {
            "8.7.1",
            "8.8.2",
            "8.9.2",
            "8.10.4",
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
        }:
            for method in ["get", "post"]:
                call(
                    "multi-knn-" + method,
                    {"size": 2, "knn": [knn, {**knn, "query_vector": [0.0, 1.0]}]},
                    [
                        (
                            "two knn clauses retrieve both actual nearest docs",
                            lambda d: sorted(h["_id"] for h in d["hits"]["hits"]),
                            ["a", "b"],
                        ),
                        ("multi knn no shard failure", lambda d: d["_shards"]["failed"], 0),
                    ],
                    verifies=["vector-a", "vector-b"],
                    semantic=True,
                )
            call(
                "multi-knn-array-error",
                {"knn": ["invalid"]},
                [
                    (
                        "non-object knn clause rejected",
                        lambda d: (
                            "within the knn search array only objects are allowed"
                            in str(d["error"])
                        ),
                        True,
                    )
                ],
            )
            call(
                "knn-vector-required",
                {"knn": {"field": "v", "k": 1, "num_candidates": 2}},
                [
                    (
                        "missing vector and builder diagnosed",
                        lambda d: (
                            "must be provided" in str(d["error"])
                            and "query_vector_builder" in str(d["error"])
                        ),
                        True,
                    )
                ],
            )
        if catalog.version in {"8.8.2", "8.9.2", "8.10.4", "8.11.4", "8.12.2", "8.13.4", "8.14.3"}:
            for method in ["get", "post"]:
                call(
                    "similarity-" + method,
                    {"knn": {**knn, "k": 2, "similarity": 0.1}},
                    [
                        (
                            "raw cosine cutoff excludes orthogonal document",
                            lambda d: [h["_id"] for h in d["hits"]["hits"]],
                            ["a"],
                        )
                    ],
                    verifies=["vector-a", "vector-b"],
                    semantic=True,
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
        call(
            "voting-plain",
            assertions=[
                ("default media legacy path rejected", lambda d: bool(d.get("error")), True)
            ],
        )
        call(
            "voting-compatible",
            assertions=[
                (
                    "removed path parameter is explicit",
                    lambda d: d["error"]["reason"],
                    "[node_name] has been removed, you must set [node_names] or [node_ids]",
                )
            ],
        )
        call(
            "voting-preserved",
            assertions=[
                (
                    "rejected legacy requests do not add exclusions",
                    lambda d: d["metadata"]["cluster_coordination"]["voting_config_exclusions"],
                    [],
                )
            ],
            verifies=["voting-plain", "voting-compatible"],
            semantic=True,
        )
    finally:
        for name in ["cleanup-vector", "cleanup-applied", "cleanup-template"]:
            if not focused or name != "cleanup-vector":
                call(name)
