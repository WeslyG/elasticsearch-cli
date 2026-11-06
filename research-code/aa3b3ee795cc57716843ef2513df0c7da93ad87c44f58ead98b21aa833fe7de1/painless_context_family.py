"""Exact7.2.1 experimental Painless metadata; no general script API coverage."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.2.1"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for name, suffix, status in [
        ("list", "", 200),
        ("score", "?context=score", 200),
        ("filter", "?context=filter", 200),
        ("unknown", "?context=es_cli_missing_context", 400),
        ("empty", "?context=", 400),
        ("unused-body", "", 400),
        ("list-after", "", 200),
    ]:
        identifier = "painless-context." + name
        add(
            identifier,
            "scripts_painless_context",
            "GET",
            "/_scripts/painless/_context" + suffix,
            expected=(status,),
            dimensions=("query.context-selection", "response.actual-metadata"),
        )
        graph[identifier] = () if name == "list" else ("painless-context.list",)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Context metadata recipe not prepared for exact release")
    listed = None
    for name in ["list", "score", "filter", "unknown", "empty", "unused-body", "list-after"]:
        case = catalog.cases["painless-context." + name]
        assertions = []
        if name in {"list", "list-after"}:
            assertions = [
                (
                    "nonempty sorted distinct context names",
                    lambda d: (
                        isinstance(d.get("contexts"), list)
                        and len(d["contexts"]) > 0
                        and d["contexts"] == sorted(set(d["contexts"]))
                    ),
                    True,
                ),
                (
                    "executable contexts advertised",
                    lambda d: {"painless_test", "score", "filter"}.issubset(d["contexts"]),
                    True,
                ),
            ]
            if name == "list-after":
                assertions.append(
                    ("invalid requests did not alter contexts", lambda d: d["contexts"], listed)
                )
        elif name in {"score", "filter"}:
            assertions = [
                ("selected context identity", lambda d: d["name"], name),
                (
                    "public metadata arrays",
                    lambda d: all(
                        isinstance(d.get(k), list)
                        for k in [
                            "classes",
                            "imported_methods",
                            "class_bindings",
                            "instance_bindings",
                        ]
                    ),
                    True,
                ),
                (
                    "Math class available",
                    lambda d: any(c["name"] == "java.lang.Math" for c in d["classes"]),
                    True,
                ),
            ]
        elif name in {"unknown", "empty"}:
            selected = "es_cli_missing_context" if name == "unknown" else ""
            assertions = [
                (
                    "structured invalid context",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                ),
                (
                    "exact missing context",
                    lambda d: d["error"]["reason"],
                    "script context [" + selected + "] not found",
                ),
            ]
        else:
            assertions = [
                (
                    "unused body rejected",
                    lambda d: "does not support having a body" in d["error"]["reason"],
                    True,
                )
            ]
        result = catalog.execute(
            run,
            case.id,
            values={},
            body={"unused": True} if name == "unused-body" else OMITTED,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=name in {"list", "score", "filter", "list-after"},
        )
        print(case.id, result.state, result.status, flush=True)
        if name == "list" and result.state == "passed":
            listed = result.data["contexts"]
