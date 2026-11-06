"""Composable/legacy template state and application, independent of any SDK."""

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_PILOTS


def declare(add, version="9.5.6"):
    legacy = version.startswith("6.")
    legacy_only = legacy or (version in EARLY_SEVEN_PILOTS and version not in {"7.9.3", "7.10.2"})
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if legacy_only and not name.startswith("legacy."):
            return
        add("template." + name, api, method, path, expected=expected, purpose=purpose)
        graph["template." + name] = tuple("template." + d for d in deps)

    for kind, base, put, get, exists, delete in [
        (
            "component",
            "/_component_template/{component}",
            "cluster.put_component_template",
            "cluster.get_component_template",
            "cluster.exists_component_template",
            "cluster.delete_component_template",
        ),
        (
            "modern",
            "/_index_template/{modern}",
            "indices.put_index_template",
            "indices.get_index_template",
            "indices.exists_index_template",
            "indices.delete_index_template",
        ),
        (
            "legacy",
            "/_template/{legacy}",
            "indices.put_template",
            "indices.get_template",
            "indices.exists_template",
            "indices.delete_template",
        ),
    ]:
        for method in ["PUT", "POST"]:
            deps = ("component.post",) if kind == "modern" else ()
            if method == "POST":
                deps = (*deps, kind + ".put")
            case(kind + "." + method.lower(), put, method, base, deps)
        case(kind + ".duplicate", put, "PUT", base + "?create=true", (kind + ".post",), (400,))
        case(kind + ".get", get, "GET", base, (kind + ".post",), purpose="effect-check")
        case(
            kind + ".all",
            get,
            "GET",
            base.rsplit("/", 1)[0],
            (kind + ".post",),
            purpose="effect-check",
        )
        case(kind + ".exists", exists, "HEAD", base, (kind + ".post",))
        deps = ("modern.delete",) if kind == "component" else ()
        case(kind + ".delete", delete, "DELETE", base, deps, expected=(200, 404), purpose="cleanup")
        case(
            kind + ".absent",
            exists,
            "HEAD",
            base,
            (kind + ".delete",),
            (404,),
            purpose="effect-check",
        )
    case(
        "simulate-named",
        "indices.simulate_template",
        "POST",
        "/_index_template/_simulate/{modern}",
        ("modern.post",),
    )
    case(
        "simulate-inline-conflict",
        "indices.simulate_template",
        "POST",
        "/_index_template/_simulate",
        ("modern.post",),
        (400,),
    )
    case(
        "simulate-inline",
        "indices.simulate_template",
        "POST",
        "/_index_template/_simulate",
        ("component.post",),
    )
    case(
        "simulate-index",
        "indices.simulate_index_template",
        "POST",
        "/_index_template/_simulate_index/{index}",
        ("modern.post",),
    )
    for kind, index in [("modern", "{index}"), ("legacy", "{legacy_index}")]:
        case(
            kind + ".create-index",
            "indices.create",
            "PUT",
            "/" + index,
            (kind + ".post",),
            purpose="fixture-setup",
        )
        case(
            kind + ".index-mapping",
            "indices.get_mapping",
            "GET",
            "/" + index + "/_mapping",
            (kind + ".create-index",),
            purpose="effect-check",
        )
        case(
            kind + ".index-settings",
            "indices.get_settings",
            "GET",
            "/" + index + "/_settings?flat_settings=true",
            (kind + ".create-index",),
            purpose="effect-check",
        )
        case(
            kind + ".index-delete",
            "indices.delete",
            "DELETE",
            "/" + index,
            expected=(200, 404),
            purpose="cleanup",
        )
    if version in {"7.9.3", "7.10.2"}:
        case(
            "component.in-use-delete",
            "cluster.delete_component_template",
            "DELETE",
            "/_component_template/{component}",
            ("modern.post",),
            (400,),
        )
        case(
            "component.in-use-readback",
            "cluster.get_component_template",
            "GET",
            "/_component_template/{component}",
            ("component.in-use-delete",),
        )
        case(
            "modern.missing-reference",
            "indices.put_index_template",
            "PUT",
            "/_index_template/{missing_template}",
            ("modern.post",),
            (400,),
        )
        case(
            "modern.missing-reference-absent",
            "indices.exists_index_template",
            "HEAD",
            "/_index_template/{missing_template}",
            ("modern.missing-reference",),
            (404,),
        )
        case(
            "modern.missing-reference-cleanup",
            "indices.delete_index_template",
            "DELETE",
            "/_index_template/{missing_template}",
            expected=(200, 404),
            purpose="cleanup",
        )
    return graph


def execute(run, catalog, prefix):
    legacy = catalog.version.startswith("6.")
    legacy_only = legacy or (
        catalog.version in EARLY_SEVEN_PILOTS and catalog.version not in {"7.9.3", "7.10.2"}
    )
    values = {
        "component": prefix + "-component",
        "modern": prefix + "-modern",
        "legacy": prefix + "-legacy",
        "index": prefix + "-modern-001",
        "legacy_index": prefix + "-legacy-001",
        "missing_template": prefix + "-missing-template",
    }
    component = values["component"]
    modern_body = {
        "index_patterns": [prefix + "-modern-*"],
        "composed_of": [component],
        "priority": 101,
        "version": 2,
        "template": {"mappings": {"properties": {"n": {"type": "integer"}}}},
    }
    bodies = {
        "component": {
            "version": 2,
            "template": {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {"properties": {"category": {"type": "keyword"}}},
            },
        },
        "modern": modern_body,
        "legacy": {
            "index_patterns": [prefix + "-legacy-*"],
            "version": 2,
            "order": 1,
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {"legacy_field": {"type": "keyword"}}},
        },
    }

    if legacy:
        bodies["legacy"]["mappings"] = {"fixture": bodies["legacy"]["mappings"]}

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["template." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["template." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]

    def entry(data, kind):
        if kind == "legacy":
            return data[values[kind]]
        key = "component_templates" if kind == "component" else "index_templates"
        value = "component_template" if kind == "component" else "index_template"
        return next(row[value] for row in data[key] if row["name"] == values[kind])

    try:
        for kind in ["legacy"] if legacy_only else ["component", "modern", "legacy"]:
            call(kind + ".put", {**bodies[kind], "version": 1}, ack)
            call(kind + ".post", bodies[kind], ack)
            call(
                kind + ".duplicate",
                bodies[kind],
                [("duplicate rejected", lambda d: "already exists" in str(d["error"]), True)],
            )
            for route in ["get", "all"]:
                call(
                    kind + "." + route,
                    assertions=[
                        ("POST version read back", lambda d, k=kind: entry(d, k)["version"], 2)
                    ],
                    verifies=[kind + ".post"],
                    semantic=True,
                )
            call(kind + ".exists")
        if catalog.version in {"7.9.3", "7.10.2"}:
            call(
                "component.in-use-delete",
                assertions=[
                    (
                        "used component cannot be removed",
                        lambda d: "cannot be removed" in str(d["error"]),
                        True,
                    )
                ],
            )
            call(
                "component.in-use-readback",
                assertions=[
                    ("used component still stored", lambda d: entry(d, "component")["version"], 2)
                ],
                verifies=["component.in-use-delete"],
                semantic=True,
            )
            call(
                "modern.missing-reference",
                {
                    **modern_body,
                    "index_patterns": [prefix + "-missing-*"],
                    "composed_of": [prefix + "-absent-component"],
                },
                [("missing component rejected", lambda d: "do not exist" in str(d["error"]), True)],
            )
            call("modern.missing-reference-absent", verifies=["modern.missing-reference"])
        if not legacy_only:
            checks = [
                (
                    "own mapping resolved",
                    lambda d: d["template"]["mappings"]["properties"]["n"]["type"],
                    "integer",
                ),
                (
                    "component mapping resolved",
                    lambda d: d["template"]["mappings"]["properties"]["category"]["type"],
                    "keyword",
                ),
                (
                    "component setting resolved",
                    lambda d: str(d["template"]["settings"]["index"]["number_of_replicas"]),
                    "0",
                ),
            ]
            call(
                "simulate-named",
                assertions=checks,
                verifies=["modern.post", "component.post"],
                semantic=True,
            )
            call(
                "simulate-inline-conflict",
                modern_body,
                [
                    (
                        "same-priority overlap rejected",
                        lambda d: d["error"]["type"],
                        "illegal_argument_exception",
                    )
                ],
            )
            call(
                "simulate-inline",
                {**modern_body, "priority": 102},
                checks,
                verifies=["component.post"],
                semantic=True,
            )
            call(
                "simulate-index",
                assertions=checks,
                verifies=["modern.post", "component.post"],
                semantic=True,
            )
        for kind in ["legacy"] if legacy_only else ["modern", "legacy"]:
            index = values["index" if kind == "modern" else "legacy_index"]
            call(kind + ".create-index", {}, ack)
            fields = (
                {"category": "keyword", "n": "integer"}
                if kind == "modern"
                else {"legacy_field": "keyword"}
            )
            call(
                kind + ".index-mapping",
                assertions=[
                    (
                        "template fields applied",
                        lambda d, i=index: {
                            key: value["type"]
                            for key, value in (
                                d[i]["mappings"]["fixture"] if legacy else d[i]["mappings"]
                            )["properties"].items()
                        },
                        fields,
                    )
                ],
                verifies=[kind + ".post", kind + ".create-index"],
                semantic=True,
            )
            call(
                kind + ".index-settings",
                assertions=[
                    (
                        "template replicas applied",
                        lambda d, i=index: d[i]["settings"]["index.number_of_replicas"],
                        "0",
                    )
                ],
                verifies=[kind + ".post", kind + ".create-index"],
                semantic=True,
            )
    finally:
        if catalog.version in {"7.9.3", "7.10.2"}:
            call("modern.missing-reference-cleanup")
        for kind in ["legacy"] if legacy_only else ["modern", "legacy"]:
            call(kind + ".index-delete")
        for kind in ["legacy"] if legacy_only else ["modern", "legacy", "component"]:
            call(kind + ".delete")
            call(kind + ".absent")
