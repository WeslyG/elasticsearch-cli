"""Exact ES6.3 Painless test context: legacy request shape and string results."""

PREPARED_VERSIONS = {"6.3.2"}


def samples():
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
    return result


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for method in ["GET", "POST"]:
        for name, _, status, _ in samples():
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
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Painless fixture is not prepared for this exact release")
    for method in ["get", "post"]:
        for name, body, status, expected in samples():
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
