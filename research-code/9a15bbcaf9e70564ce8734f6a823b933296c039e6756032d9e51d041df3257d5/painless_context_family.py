"""Exact7.2.1 experimental Painless metadata; no general script API coverage."""

from evidence_runner import OMITTED
from legacy_release_selection import REJECT_UNUSED_METADATA_BODY_RELEASES

PREPARED_VERSIONS = {
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
}


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
        ("unused-body", "", 200),
        ("list-after", "", 200),
    ]:
        if name == "unused-body" and version in REJECT_UNUSED_METADATA_BODY_RELEASES:
            status = 400
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
        if name == "unused-body" and catalog.version in REJECT_UNUSED_METADATA_BODY_RELEASES:
            assertions = [
                (
                    "unused metadata body rejected",
                    lambda d: d["error"]["type"],
                    "illegal_argument_exception",
                ),
                (
                    "specific body refusal",
                    lambda d: d["error"]["reason"],
                    "request [GET /_scripts/painless/_context] does not support having a body",
                ),
            ]
        elif name in {"list", "list-after", "unused-body"}:
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
            if name in {"list-after", "unused-body"}:
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
        result = catalog.execute(
            run,
            case.id,
            values={},
            body={"unused": True} if name == "unused-body" else OMITTED,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=name in {"list", "score", "filter", "list-after", "unused-body"},
        )
        print(case.id, result.state, result.status, flush=True)
        if name == "list" and result.state == "passed":
            listed = result.data["contexts"]
