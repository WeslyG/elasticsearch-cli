"""Exact7.6 native script metadata and advertised executable context contracts."""

from evidence_runner import OMITTED

PREPARED_VERSIONS = {"7.6.2"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for name, api, path in [
        ("contexts", "get_script_context", "/_script_context"),
        ("languages", "get_script_languages", "/_script_language"),
        ("contexts-body", "get_script_context", "/_script_context"),
        ("languages-body", "get_script_languages", "/_script_language"),
        ("painless", "scripts_painless_context", "/_scripts/painless/_context"),
        ("contexts-unknown", "get_script_context", "/_script_context?es_cli_unknown=true"),
        ("languages-unknown", "get_script_languages", "/_script_language?es_cli_unknown=true"),
    ]:
        unknown = name.endswith("-unknown")
        identifier = "script-info." + name
        add(
            identifier,
            api,
            "GET",
            path,
            expected=(400,) if unknown else (200,),
            unsupported=("es_cli_unknown",) if unknown else (),
        )
        graph[identifier] = (
            ()
            if name in {"contexts", "languages"}
            else ("script-info.contexts", "script-info.languages")
        )
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Script metadata not prepared for exact release")

    def call(name, body=OMITTED, assertions=(), verifies=()):
        case = catalog.cases["script-info." + name]
        result = catalog.execute(
            run,
            case.id,
            values={},
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["script-info." + d for d in verifies],
            semantic=bool(assertions),
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def signature(data, name):
        context = next(c for c in data["contexts"] if c["name"] == name)
        return next(m["return_type"] for m in context["methods"] if m["name"] == "execute")

    contexts = call(
        "contexts",
        assertions=[
            (
                "distinct context names",
                lambda d: len({c["name"] for c in d["contexts"]}) == len(d["contexts"]) > 0,
                True,
            ),
            ("score execute return type", lambda d: signature(d, "score"), "double"),
            ("filter execute return type", lambda d: signature(d, "filter"), "boolean"),
            (
                "method metadata shape",
                lambda d: all(
                    isinstance(m["name"], str)
                    and isinstance(m["return_type"], str)
                    and all(
                        isinstance(p["type"], str) and isinstance(p["name"], str)
                        for p in m["params"]
                    )
                    for c in d["contexts"]
                    for m in c["methods"]
                ),
                True,
            ),
        ],
    )
    languages = call(
        "languages",
        assertions=[
            (
                "inline and stored allowed",
                lambda d: set(d["types_allowed"]) == {"inline", "stored"},
                True,
            ),
            (
                "Painless contexts advertised",
                lambda d: {"filter", "score", "painless_test"}.issubset(
                    next(
                        v["contexts"] for v in d["language_contexts"] if v["language"] == "painless"
                    )
                ),
                True,
            ),
        ],
    )
    call(
        "contexts-body",
        {"unused": True},
        [
            (
                "unused body retains context definitions",
                lambda d: d,
                contexts.data if contexts.passed else None,
            ),
        ],
        verifies=("contexts",),
    )
    call(
        "languages-body",
        {"unused": True},
        [
            (
                "unused body retains language definitions",
                lambda d: d,
                languages.data if languages.passed else None,
            ),
        ],
        verifies=("languages",),
    )
    known = {c["name"] for c in contexts.data["contexts"]} if contexts.passed else set()
    allowed = (
        set(
            next(
                v["contexts"]
                for v in languages.data["language_contexts"]
                if v["language"] == "painless"
            )
        )
        if languages.passed
        else set()
    )
    call(
        "painless",
        assertions=[
            (
                "Painless metadata names agree with language advertisement",
                lambda d: sorted(set(d["contexts"])),
                sorted(allowed),
            ),
            (
                "Painless advertised contexts have core signatures",
                lambda d: set(d["contexts"]).issubset(known),
                True,
            ),
        ],
        verifies=("contexts", "languages"),
    )
    for name in ["contexts-unknown", "languages-unknown"]:
        call(
            name,
            assertions=[
                (
                    "unknown query explicitly refused",
                    lambda d: "es_cli_unknown" in str(d["error"]),
                    True,
                )
            ],
        )
