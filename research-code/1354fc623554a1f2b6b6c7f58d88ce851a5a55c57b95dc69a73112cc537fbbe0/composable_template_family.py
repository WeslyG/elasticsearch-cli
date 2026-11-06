"""Exact7.8 composable/component templates: real composition and early dangling refs."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.8.1"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    specs = [
        (
            "component-put",
            "cluster.put_component_template",
            "PUT",
            "/_component_template/{component}",
            (),
            (200,),
        ),
        (
            "component-get",
            "cluster.get_component_template",
            "GET",
            "/_component_template/{component}",
            ("component-put",),
            (200,),
        ),
        (
            "component-all",
            "cluster.get_component_template",
            "GET",
            "/_component_template",
            ("component-put",),
            (200,),
        ),
        (
            "component-head",
            "cluster.exists_component_template",
            "HEAD",
            "/_component_template/{component}",
            ("component-put",),
            (200,),
        ),
        (
            "component-create-refused",
            "cluster.put_component_template",
            "POST",
            "/_component_template/{component}?create=true",
            ("component-get",),
            (400,),
        ),
        (
            "component-unchanged",
            "cluster.get_component_template",
            "GET",
            "/_component_template/{component}",
            ("component-create-refused",),
            (200,),
        ),
        (
            "template-put",
            "indices.put_index_template",
            "PUT",
            "/_index_template/{template}",
            ("component-unchanged",),
            (200,),
        ),
        (
            "template-get",
            "indices.get_index_template",
            "GET",
            "/_index_template/{template}",
            ("template-put",),
            (200,),
        ),
        (
            "template-all",
            "indices.get_index_template",
            "GET",
            "/_index_template",
            ("template-put",),
            (200,),
        ),
        (
            "template-head",
            "indices.exists_index_template",
            "HEAD",
            "/_index_template/{template}",
            ("template-put",),
            (200,),
        ),
        (
            "template-create-refused",
            "indices.put_index_template",
            "POST",
            "/_index_template/{template}?create=true",
            ("template-get",),
            (400,),
        ),
        (
            "template-unchanged",
            "indices.get_index_template",
            "GET",
            "/_index_template/{template}",
            ("template-create-refused",),
            (200,),
        ),
        (
            "template-post",
            "indices.put_index_template",
            "POST",
            "/_index_template/{template}",
            ("template-unchanged",),
            (200,),
        ),
        (
            "template-version",
            "indices.get_index_template",
            "GET",
            "/_index_template/{template}",
            ("template-post",),
            (200,),
        ),
        (
            "simulate",
            "indices.simulate_index_template",
            "POST",
            "/_index_template/_simulate_index/{index}",
            ("template-version",),
            (200,),
        ),
        ("create-first", "indices.create", "PUT", "/{index}", ("simulate",), (200,)),
        (
            "settings-first",
            "indices.get_settings",
            "GET",
            "/{index}/_settings?flat_settings=true",
            ("create-first",),
            (200,),
        ),
        (
            "mapping-first",
            "indices.get_mapping",
            "GET",
            "/{index}/_mapping",
            ("create-first",),
            (200,),
        ),
        ("write", "index", "PUT", "/{index}/_doc/one?refresh=true", ("mapping-first",), (201,)),
        ("read", "get", "GET", "/{index}/_doc/one", ("write",), (200,)),
        (
            "component-delete-in-use",
            "cluster.delete_component_template",
            "DELETE",
            "/_component_template/{component}",
            ("read",),
            (200,),
        ),
        (
            "component-absent",
            "cluster.exists_component_template",
            "HEAD",
            "/_component_template/{component}",
            ("component-delete-in-use",),
            (404,),
        ),
        (
            "component-missing",
            "cluster.get_component_template",
            "GET",
            "/_component_template/{component}",
            ("component-delete-in-use",),
            (404,),
        ),
        (
            "dangling-template",
            "indices.get_index_template",
            "GET",
            "/_index_template/{template}",
            ("component-delete-in-use",),
            (200,),
        ),
        (
            "simulate-dangling",
            "indices.simulate_index_template",
            "POST",
            "/_index_template/_simulate_index/{second}",
            ("dangling-template",),
            (200,),
        ),
        ("old-data-retained", "get", "GET", "/{index}/_doc/one", ("simulate-dangling",), (200,)),
        (
            "component-restore",
            "cluster.put_component_template",
            "POST",
            "/_component_template/{component}",
            ("component-absent", "old-data-retained"),
            (200,),
        ),
        (
            "component-version",
            "cluster.get_component_template",
            "GET",
            "/_component_template/{component}",
            ("component-restore",),
            (200,),
        ),
        (
            "simulate-restored",
            "indices.simulate_index_template",
            "POST",
            "/_index_template/_simulate_index/{second}",
            ("component-version",),
            (200,),
        ),
        ("create-second", "indices.create", "PUT", "/{second}", ("simulate-restored",), (200,)),
        (
            "mapping-second",
            "indices.get_mapping",
            "GET",
            "/{second}/_mapping",
            ("create-second",),
            (200,),
        ),
        (
            "first-not-retrofitted",
            "indices.get_mapping",
            "GET",
            "/{index}/_mapping",
            ("mapping-second",),
            (200,),
        ),
        (
            "missing-put",
            "indices.put_index_template",
            "PUT",
            "/_index_template/{missing_template}",
            ("first-not-retrofitted",),
            (200,),
        ),
        (
            "missing-get",
            "indices.get_index_template",
            "GET",
            "/_index_template/{missing_template}",
            ("missing-put",),
            (200,),
        ),
        (
            "missing-component-absent",
            "cluster.exists_component_template",
            "HEAD",
            "/_component_template/{missing_component}",
            ("missing-put",),
            (404,),
        ),
        (
            "simulate-missing",
            "indices.simulate_index_template",
            "POST",
            "/_index_template/_simulate_index/{missing_index}",
            ("missing-get",),
            (200,),
        ),
    ]
    for name, api, method, path, deps, expected in specs:
        identifier = "composable-template." + name
        add(identifier, api, method, path, expected=expected)
        graph[identifier] = tuple("composable-template." + d for d in deps)
    for name, api, path in [
        ("index", "indices.delete", "/{index}"),
        ("second", "indices.delete", "/{second}"),
        ("template", "indices.delete_index_template", "/_index_template/{template}"),
        ("missing", "indices.delete_index_template", "/_index_template/{missing_template}"),
        ("component", "cluster.delete_component_template", "/_component_template/{component}"),
    ]:
        identifier = "composable-template.cleanup-" + name
        add(identifier, api, "DELETE", path, expected=(200, 404), purpose="fixture-cleanup")
        graph[identifier] = ()
    for name, api, path in [
        ("template", "indices.exists_index_template", "/_index_template/{template}"),
        ("component", "cluster.exists_component_template", "/_component_template/{component}"),
    ]:
        identifier = "composable-template.deleted-" + name
        add(identifier, api, "HEAD", path, expected=(404,), purpose="effect-check")
        graph[identifier] = ("composable-template.cleanup-" + name,)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Composable template fixture not prepared for exact release")
    values = {
        "component": prefix + "-component",
        "template": prefix + "-v2-template",
        "index": prefix + "-data-000001",
        "second": prefix + "-data-000002",
        "missing_template": prefix + "-missing-template",
        "missing_component": prefix + "-absent-component",
        "missing_index": prefix + "-missing-000001",
    }

    def call(name, body=OMITTED, assertions=(), verifies=()):
        case = catalog.cases["composable-template." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["composable-template." + d for d in verifies],
            semantic=bool(assertions),
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def component(data):
        return next(
            v["component_template"]
            for v in data["component_templates"]
            if v["name"] == values["component"]
        )

    def template(data, name="template"):
        return next(
            v["index_template"] for v in data["index_templates"] if v["name"] == values[name]
        )

    def component_body(version):
        props = {"n": {"type": "integer"}}
        if version == 2:
            props["future"] = {"type": "boolean"}
        return {
            "version": version,
            "_meta": {"research": True},
            "template": {
                "settings": {"index.number_of_replicas": 0},
                "mappings": {"properties": props},
                "aliases": {prefix + "-component-alias": {}},
            },
        }

    definition = {
        "index_patterns": [prefix + "-data-*"],
        "composed_of": [values["component"]],
        "priority": 100,
        "version": 1,
        "template": {
            "settings": {"index.number_of_shards": 1},
            "mappings": {"properties": {"tag": {"type": "keyword"}}},
            "aliases": {prefix + "-template-alias": {}},
        },
    }
    try:
        call("component-put", component_body(1))
        for name in ["component-get", "component-all"]:
            call(
                name,
                assertions=[
                    ("actual component version", lambda d: component(d)["version"], 1),
                    (
                        "typeless component mapping",
                        lambda d: component(d)["template"]["mappings"]["properties"]["n"]["type"],
                        "integer",
                    ),
                ],
                verifies=("component-put",),
            )
        call("component-head")
        call(
            "component-create-refused",
            component_body(99),
            [("create-only refusal", lambda d: "already exists" in str(d["error"]), True)],
        )
        call(
            "component-unchanged",
            assertions=[("refusal preserves component", lambda d: component(d)["version"], 1)],
            verifies=("component-create-refused",),
        )
        call("template-put", definition)
        for name in ["template-get", "template-all"]:
            call(
                name,
                assertions=[
                    (
                        "actual component reference",
                        lambda d: template(d)["composed_of"],
                        [values["component"]],
                    ),
                    ("actual version", lambda d: template(d)["version"], 1),
                ],
                verifies=("template-put",),
            )
        call("template-head")
        call(
            "template-create-refused",
            {**definition, "version": 99},
            [("create-only template refusal", lambda d: "already exists" in str(d["error"]), True)],
        )
        call(
            "template-unchanged",
            assertions=[("refusal preserves template", lambda d: template(d)["version"], 1)],
            verifies=("template-create-refused",),
        )
        call("template-post", {**definition, "version": 2})
        call(
            "template-version",
            assertions=[("POST update persisted", lambda d: template(d)["version"], 2)],
            verifies=("template-post",),
        )
        composed = [
            (
                "component mapping composed",
                lambda d: d["template"]["mappings"]["properties"]["n"]["type"],
                "integer",
            ),
            (
                "inline mapping composed",
                lambda d: d["template"]["mappings"]["properties"]["tag"]["type"],
                "keyword",
            ),
            (
                "both alias sources composed",
                lambda d: all(
                    a in d["template"]["aliases"]
                    for a in [prefix + "-component-alias", prefix + "-template-alias"]
                ),
                True,
            ),
        ]
        call("simulate", assertions=composed)
        call("create-first", {})
        call(
            "settings-first",
            assertions=[
                (
                    "component replicas applied to real index",
                    lambda d: d[values["index"]]["settings"]["index.number_of_replicas"],
                    "0",
                ),
                (
                    "inline shards applied to real index",
                    lambda d: d[values["index"]]["settings"]["index.number_of_shards"],
                    "1",
                ),
            ],
            verifies=("create-first", "component-put", "template-post"),
        )
        call(
            "mapping-first",
            assertions=[
                (
                    "real composed mapping",
                    lambda d: d[values["index"]]["mappings"]["properties"]["n"]["type"],
                    "integer",
                )
            ],
            verifies=("create-first",),
        )
        call("write", {"n": 42, "tag": "composed"})
        call(
            "read",
            assertions=[
                ("real document stored", lambda d: d["_source"], {"n": 42, "tag": "composed"})
            ],
            verifies=("write",),
        )
        call("component-delete-in-use")
        call("component-absent", verifies=("component-delete-in-use",))
        call("component-missing", verifies=("component-delete-in-use",))
        call(
            "dangling-template",
            assertions=[
                (
                    "early7.8 retains dangling component reference",
                    lambda d: template(d)["composed_of"],
                    [values["component"]],
                )
            ],
            verifies=("component-delete-in-use",),
        )
        call(
            "simulate-dangling",
            assertions=[
                (
                    "deleted component no longer contributes",
                    lambda d: "n" not in d["template"]["mappings"]["properties"],
                    True,
                ),
                (
                    "inline template still contributes",
                    lambda d: d["template"]["mappings"]["properties"]["tag"]["type"],
                    "keyword",
                ),
            ],
            verifies=("component-delete-in-use",),
        )
        call(
            "old-data-retained",
            assertions=[
                ("existing data survives component deletion", lambda d: d["_source"]["n"], 42)
            ],
            verifies=("component-delete-in-use",),
        )
        call("component-restore", component_body(2))
        call(
            "component-version",
            assertions=[("component restored as version2", lambda d: component(d)["version"], 2)],
            verifies=("component-restore",),
        )
        call(
            "simulate-restored",
            assertions=[
                (
                    "new field composed",
                    lambda d: d["template"]["mappings"]["properties"]["future"]["type"],
                    "boolean",
                )
            ],
            verifies=("component-restore",),
        )
        call("create-second", {})
        call(
            "mapping-second",
            assertions=[
                (
                    "new index sees restored component",
                    lambda d: d[values["second"]]["mappings"]["properties"]["future"]["type"],
                    "boolean",
                )
            ],
            verifies=("create-second", "component-restore"),
        )
        call(
            "first-not-retrofitted",
            assertions=[
                (
                    "existing index not retrofitted",
                    lambda d: "future" not in d[values["index"]]["mappings"]["properties"],
                    True,
                )
            ],
            verifies=("component-restore",),
        )
        missing = {
            "index_patterns": [prefix + "-missing-*"],
            "priority": 100,
            "composed_of": [values["missing_component"]],
            "template": {
                "settings": {"index.number_of_shards": 1, "index.number_of_replicas": 0},
                "mappings": {"properties": {"only": {"type": "keyword"}}},
            },
        }
        call("missing-put", missing)
        call(
            "missing-get",
            assertions=[
                (
                    "missing reference still stored",
                    lambda d: template(d, "missing_template")["composed_of"],
                    [values["missing_component"]],
                )
            ],
            verifies=("missing-put",),
        )
        call("missing-component-absent")
        call(
            "simulate-missing",
            assertions=[
                (
                    "missing component skipped while own mapping works",
                    lambda d: d["template"]["mappings"]["properties"],
                    {"only": {"type": "keyword"}},
                )
            ],
            verifies=("missing-put",),
        )
    finally:
        for name in ["index", "second", "template", "missing", "component"]:
            call("cleanup-" + name)
        for name in ["template", "component"]:
            call("deleted-" + name, verifies=("cleanup-" + name,))
