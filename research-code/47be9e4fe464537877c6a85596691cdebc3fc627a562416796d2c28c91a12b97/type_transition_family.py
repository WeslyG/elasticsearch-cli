"""Exact ES6.7 typed/typeless wire shapes with independent mapping readback."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {
    "6.7.2",
    "6.8.23",
    "7.0.1",
    "7.1.1",
    "7.2.1",
    "7.3.2",
    "7.4.2",
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
}
MAPPING_VARIANTS = [
    ("post", "POST", "_mapping"),
    ("plural-put", "PUT", "_mappings"),
    ("plural-post", "POST", "_mappings"),
]


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        identifier = "type-transition." + name
        if version in {
            "6.8.23",
            "7.0.1",
            "7.1.1",
            "7.2.1",
            "7.3.2",
            "7.4.2",
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
        }:
            path = path.replace("/?", "?")
        add(identifier, api, method, path, expected=expected, purpose=purpose)
        graph[identifier] = tuple("type-transition." + item for item in deps)

    case(
        "nested-rejected",
        "indices.create",
        "PUT",
        "/{plain}?include_type_name=false",
        expected=(400,),
    )
    case(
        "rejected-absent",
        "indices.exists",
        "HEAD",
        "/{plain}",
        ("nested-rejected",),
        (404,),
        "effect-check",
    )
    case(
        "plain-create",
        "indices.create",
        "PUT",
        "/{plain}?include_type_name=false",
        ("rejected-absent",),
    )
    case(
        "plain-typed-view",
        "indices.get_mapping",
        "GET",
        "/{plain}/_mapping?include_type_name=true",
        ("plain-create",),
    )
    case(
        "plain-flat-view",
        "indices.get_mapping",
        "GET",
        "/{plain}/_mapping?include_type_name=false",
        ("plain-create",),
    )
    case(
        "typed-path-rejected",
        "indices.put_mapping",
        "PUT",
        "/{plain}/_mapping/_doc?include_type_name=false",
        ("plain-create",),
        (400,),
    )
    case(
        "rejected-field-absent",
        "indices.get_mapping",
        "GET",
        "/{plain}/_mapping?include_type_name=false",
        ("typed-path-rejected",),
        purpose="effect-check",
    )
    case(
        "plain-put",
        "indices.put_mapping",
        "PUT",
        "/{plain}/_mapping/?include_type_name=false",
        ("plain-create",),
    )
    case(
        "plain-put-readback",
        "indices.get_mapping",
        "GET",
        "/{plain}/_mapping?include_type_name=false",
        ("plain-put",),
        purpose="effect-check",
    )
    previous = "plain-put-readback"
    for name, method, endpoint in MAPPING_VARIANTS:
        case(
            name,
            "indices.put_mapping",
            method,
            "/{plain}/" + endpoint + "/?include_type_name=false",
            (previous,),
        )
        case(
            name + "-readback",
            "indices.get_mapping",
            "GET",
            "/{plain}/_mapping?include_type_name=false",
            (name,),
            purpose="effect-check",
        )
        previous = name + "-readback"
    case(
        "plain-write",
        "index",
        "PUT",
        "/{plain}/_doc/one?refresh=true",
        (previous,),
        (201,),
    )
    case(
        "plain-document",
        "get",
        "GET",
        "/{plain}/_doc/one",
        ("plain-write",),
        purpose="effect-check",
    )
    case("typed-create", "indices.create", "PUT", "/{typed}?include_type_name=true")
    case(
        "typed-view",
        "indices.get_mapping",
        "GET",
        "/{typed}/_mapping/fixture?include_type_name=true",
        ("typed-create",),
    )
    case(
        "typed-flat-view",
        "indices.get_mapping",
        "GET",
        "/{typed}/_mapping?include_type_name=false",
        ("typed-create",),
    )
    case(
        "typed-filter-rejected",
        "indices.get_mapping",
        "GET",
        "/{typed}/_mapping/fixture?include_type_name=false",
        ("typed-create",),
        (400,),
    )
    case(
        "typed-write", "index", "PUT", "/{typed}/fixture/one?refresh=true", ("typed-view",), (201,)
    )
    case(
        "typed-document",
        "get",
        "GET",
        "/{typed}/fixture/one",
        ("typed-write",),
        purpose="effect-check",
    )
    for name in ["plain", "typed"]:
        case(
            "cleanup-" + name,
            "indices.delete",
            "DELETE",
            "/{" + name + "}",
            expected=(200, 404),
            purpose="cleanup",
        )
        case(
            "absent-" + name,
            "indices.exists",
            "HEAD",
            "/{" + name + "}",
            ("cleanup-" + name,),
            (404,),
            "effect-check",
        )
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Type transition is not prepared for this exact release")
    values = {"plain": prefix + "-type-plain", "typed": prefix + "-type-custom"}
    properties = {"n": {"type": "integer"}}
    settings = {"number_of_shards": 1, "number_of_replicas": 0}

    def call(name, body=OMITTED, checks=()):
        case = catalog.cases["type-transition." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=checks,
            depends_on=case.dependency_plan,
            semantic=case.purpose == "effect-check",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def mapping(index, typed=False, type_name="_doc"):
        def extract(data):
            result = data[values[index]]["mappings"]
            return result[type_name]["properties"] if typed else result["properties"]

        return extract

    acknowledged = [("acknowledged", lambda data: data["acknowledged"], True)]
    try:
        call(
            "nested-rejected",
            {"settings": settings, "mappings": {"_doc": {"properties": properties}}},
            [
                (
                    "native nested mapping refusal",
                    lambda data: "include_type_name" in data["error"]["reason"],
                    True,
                )
            ],
        )
        call("rejected-absent")
        call(
            "plain-create",
            {"settings": settings, "mappings": {"properties": properties}},
            acknowledged,
        )
        call(
            "plain-typed-view",
            checks=[("internal type is _doc", mapping("plain", True), properties)],
        )
        call("plain-flat-view", checks=[("type wrapper omitted", mapping("plain"), properties)])
        call(
            "typed-path-rejected",
            {"properties": {"forbidden": {"type": "keyword"}}},
            [
                (
                    "native typed path refusal",
                    lambda data: "include_type_name" in data["error"]["reason"],
                    True,
                )
            ],
        )
        call(
            "rejected-field-absent",
            checks=[("rejected field not installed", mapping("plain"), properties)],
        )
        call("plain-put", {"properties": {"tag": {"type": "keyword"}}}, acknowledged)
        call(
            "plain-put-readback",
            checks=[
                (
                    "flat mapping update persisted",
                    mapping("plain"),
                    {**properties, "tag": {"type": "keyword"}},
                )
            ],
        )
        expected_fields = {**properties, "tag": {"type": "keyword"}}
        for name, _, _ in MAPPING_VARIANTS:
            field = name.replace("-", "_")
            call(name, {"properties": {field: {"type": "keyword"}}}, acknowledged)
            expected_fields[field] = {"type": "keyword"}
            call(
                name + "-readback",
                checks=[
                    (
                        "each exact method/path installed its unique field",
                        mapping("plain"),
                        dict(expected_fields),
                    )
                ],
            )
        call(
            "plain-write",
            {"n": 7, "tag": "synthetic"},
            [("document uses _doc type", lambda data: data["_type"], "_doc")],
        )
        call(
            "plain-document",
            checks=[
                (
                    "actual typed document persisted",
                    lambda data: data["_source"],
                    {"n": 7, "tag": "synthetic"},
                )
            ],
        )
        call(
            "typed-create",
            {"settings": settings, "mappings": {"fixture": {"properties": properties}}},
            acknowledged,
        )
        call(
            "typed-view",
            checks=[("custom mapping retained", mapping("typed", True, "fixture"), properties)],
        )
        call(
            "typed-flat-view",
            checks=[("custom mapping can be rendered flat", mapping("typed"), properties)],
        )
        call(
            "typed-filter-rejected",
            checks=[
                (
                    "type filter requires true",
                    lambda data: "include_type_name" in data["error"]["reason"],
                    True,
                )
            ],
        )
        call(
            "typed-write",
            {"n": 9},
            [("custom document type retained", lambda data: data["_type"], "fixture")],
        )
        call(
            "typed-document",
            checks=[("custom document persisted", lambda data: data["_source"], {"n": 9})],
        )
    finally:
        for name in ["plain", "typed"]:
            call("cleanup-" + name)
            call("absent-" + name)
