"""Pinned Painless contexts: legacy shapes, real mappings and native result types."""

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_RELEASES

PREPARED_VERSIONS = {
    "6.3.2",
    "6.4.3",
    "6.5.4",
    "6.6.2",
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
}


def samples(version="6.3.2"):
    arithmetic = {"script": {"source": "params.a + params.b", "params": {"a": 2, "b": 3}}}
    result = []
    for name, source, params, expected in [
        ("default", "params.a + params.b", {"a": 2, "b": 3}, "5"),
        ("changed-params", "params.a + params.b", {"a": 12, "b": 3}, "15"),
        ("fraction", "params.a / params.b", {"a": 1.0, "b": 2.0}, "0.5"),
        ("boolean", "params.a == 2", {"a": 2}, "true"),
        ("null", "return null;", {}, "null"),
        ("object", "['value': params.a]", {"a": 2}, "{value=2}"),
        ("list", "[params.a, params.b]", {"a": 2, "b": 3}, "[2, 3]"),
    ]:
        result.append((name, {"script": {"source": source, "params": params}}, 200, expected))
    result.append(("explicit-context", {**arithmetic, "context": {"painless_test": {}}}, 200, "5"))
    result.extend(
        [
            ("modern-string-context", {**arithmetic, "context": "painless_test"}, 400, None),
            ("unknown-context", {**arithmetic, "context": {"unknown": {}}}, 400, None),
            ("missing-script", {"context": {"painless_test": {}}}, 400, None),
        ]
    )
    if version in {
        "6.4.3",
        "6.5.4",
        "6.6.2",
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
    }:
        updated = []
        for name, body, status, expected in result:
            if name == "explicit-context":
                body = {**body, "context": "painless_test"}
            elif name == "modern-string-context":
                name = "legacy-object-context"
                body = {**arithmetic, "context": {"painless_test": {}}}
            elif name == "unknown-context":
                body = {**arithmetic, "context": "unknown"}
            updated.append((name, body, status, expected))
        result = updated
    return result


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for method in ["GET", "POST"]:
        for name, _, status, _ in samples(version):
            identifier = "painless-execute." + method.lower() + "." + name
            add(
                identifier,
                "scripts_painless_execute",
                method,
                "/_scripts/painless/_execute",
                expected=(status,),
                dimensions=("body.context-shape", "response.actual-result-type"),
            )
            graph[identifier] = ()

    if version in {
        "6.4.3",
        "6.5.4",
        "6.6.2",
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
    }:

        def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
            if version in EARLY_SEVEN_RELEASES or version in {
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
            }:
                path = path.replace("/fixture/", "/_doc/")
            identifier = "painless-execute.contexts." + name
            add(identifier, api, method, path, expected=expected, purpose=purpose)
            graph[identifier] = tuple("painless-execute.contexts." + item for item in deps)

        case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
        case(
            "before", "count", "GET", "/{index}/_count", ("create",), purpose="fixture-precondition"
        )
        for method in ["GET", "POST"]:
            for name in ["filter-true", "filter-false", "score-field", "score-query"]:
                case(
                    method.lower() + "." + name,
                    "scripts_painless_execute",
                    method,
                    "/_scripts/painless/_execute",
                    ("before",),
                )
            case(
                method.lower() + ".missing-setup",
                "scripts_painless_execute",
                method,
                "/_scripts/painless/_execute",
                ("before",),
                (500,),
            )
            case(
                method.lower() + ".empty-setup",
                "scripts_painless_execute",
                method,
                "/_scripts/painless/_execute",
                ("before",),
                (400,),
            )
        case("after", "count", "GET", "/{index}/_count", ("before",), purpose="effect-check")
        case(
            "not-persisted",
            "get",
            "GET",
            "/{index}/fixture/_id",
            ("after",),
            (404,),
            purpose="effect-check",
        )
        case(
            "cleanup",
            "indices.delete",
            "DELETE",
            "/{index}",
            expected=(200, 404),
            purpose="cleanup",
        )
        case(
            "absent",
            "indices.exists",
            "HEAD",
            "/{index}",
            ("cleanup",),
            (404,),
            purpose="effect-check",
        )

    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Painless fixture is not prepared for this exact release")
    for method in ["get", "post"]:
        for name, body, status, expected in samples(catalog.version):
            identifier = "painless-execute." + method + "." + name
            case = catalog.cases[identifier]
            assertions = (
                [
                    ("actual computed value", lambda data: data["result"], expected),
                    (
                        "legacy result stays a JSON string",
                        lambda data: type(data["result"]).__name__,
                        "str",
                    ),
                ]
                if status == 200
                else [
                    (
                        "invalid input has structured server error",
                        lambda data: (
                            isinstance(data.get("error"), dict)
                            and isinstance(data["error"].get("type"), str)
                        ),
                        True,
                    )
                ]
            )
            result = catalog.execute(
                run,
                case.id,
                values={},
                body=body,
                assertions=assertions,
                depends_on=case.dependency_plan,
                semantic=status == 200,
            )
            print(case.id, result.state, result.status, flush=True)

    if catalog.version in {
        "6.4.3",
        "6.5.4",
        "6.6.2",
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
    }:
        execute_contexts(run, catalog, prefix)


def execute_contexts(run, catalog, prefix):
    values = {"index": prefix + "-painless-contexts"}

    def call(name, body=OMITTED, assertions=(), semantic=False):
        case = catalog.cases["painless-execute.contexts." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    call(
        "create",
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": (
                {"properties": {"n": {"type": "integer"}}}
                if catalog.version in EARLY_SEVEN_RELEASES
                or catalog.version
                in {
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
                }
                else {"fixture": {"properties": {"n": {"type": "integer"}}}}
            ),
        },
        assertions=[("actual mapping index acknowledged", lambda data: data["acknowledged"], True)],
    )
    try:
        call(
            "before",
            assertions=[("mapping index initially empty", lambda data: data["count"], 0)],
            semantic=True,
        )
        setup = {"index": values["index"], "document": {"n": 7}}
        bodies = [
            (
                "filter-true",
                {
                    "context": "filter",
                    "script": {"source": "doc['n'].value > params.cutoff", "params": {"cutoff": 5}},
                    "context_setup": setup,
                },
                True,
                "bool",
            ),
            (
                "filter-false",
                {
                    "context": "filter",
                    "script": {
                        "source": "doc['n'].value > params.cutoff",
                        "params": {"cutoff": 10},
                    },
                    "context_setup": setup,
                },
                False,
                "bool",
            ),
            (
                "score-field",
                {
                    "context": "score",
                    "script": {"source": "doc['n'].value * params.factor", "params": {"factor": 3}},
                    "context_setup": setup,
                },
                21.0,
                "float",
            ),
            (
                "score-query",
                {
                    "context": "score",
                    "script": {"source": "_score * params.factor", "params": {"factor": 3}},
                    "context_setup": {
                        **setup,
                        "query": {"constant_score": {"filter": {"match_all": {}}, "boost": 2.0}},
                    },
                },
                6.0,
                "float",
            ),
        ]
        for method in ["get", "post"]:
            for name, body, expected, kind in bodies:
                call(
                    method + "." + name,
                    body,
                    assertions=[
                        ("actual mapped simulation result", lambda data: data["result"], expected),
                        (
                            "native context result type is preserved",
                            lambda data: type(data["result"]).__name__,
                            kind,
                        ),
                    ],
                    semantic=True,
                )
            call(
                method + ".missing-setup",
                {"context": "filter", "script": {"source": "return true;"}},
                assertions=[
                    (
                        "legacy missing setup triggers actual server null failure",
                        lambda data: data["error"]["type"],
                        "null_pointer_exception",
                    )
                ],
            )
            call(
                method + ".empty-setup",
                {"context": "filter", "script": {"source": "return true;"}, "context_setup": {}},
                assertions=[
                    (
                        "empty setup validates mandatory fields",
                        lambda data: data["error"]["type"],
                        "action_request_validation_exception",
                    )
                ],
            )
        call(
            "after",
            assertions=[("simulation docs were never persisted", lambda data: data["count"], 0)],
            semantic=True,
        )
        call(
            "not-persisted",
            assertions=[
                (
                    "in-memory simulation ID absent from real index",
                    lambda data: data["found"],
                    False,
                )
            ],
            semantic=True,
        )
    finally:
        call("cleanup")
        call("absent")
