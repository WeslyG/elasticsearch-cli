"""Reset system feature state in the isolated lab, proven with our synonym set."""

from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if version == "8.19.24":
            path = path.replace("?refresh=true", "")
        add("feature." + name, api, method, path, expected=expected, purpose=purpose)
        graph["feature." + name] = tuple("feature." + d for d in deps)

    case(
        "seed",
        "synonyms.put_synonym",
        "PUT",
        "/_synonyms/{set}?refresh=true",
        expected=(201,),
        purpose="fixture-setup",
    )
    case(
        "before",
        "synonyms.get_synonym",
        "GET",
        "/_synonyms/{set}",
        ("seed",),
        purpose="fixture-precondition",
    )
    case("reset", "features.reset_features", "POST", "/_features/_reset", ("before",))
    case(
        "state-absent",
        "synonyms.get_synonym",
        "GET",
        "/_synonyms/{set}",
        ("reset",),
        (404,),
        purpose="effect-check",
    )
    case(
        "descriptor-remains",
        "features.get_features",
        "GET",
        "/_features",
        ("reset",),
        purpose="effect-check",
    )
    case(
        "cleanup",
        "synonyms.delete_synonym",
        "DELETE",
        "/_synonyms/{set}",
        expected=(200, 404),
        purpose="cleanup",
    )
    return graph


def execute(run, catalog, prefix):
    values = {"set": prefix + "-feature-reset"}

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["feature." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["feature." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    call("seed", {"synonyms_set": [{"id": "one", "synonyms": "alpha, beta"}]})
    try:
        call("before", assertions=[("fixture system state present", lambda d: d["count"], 1)])
        call(
            "reset",
            assertions=[
                (
                    "our synonyms feature reset succeeded",
                    lambda d: next(
                        f["status"] for f in d["features"] if f["feature_name"] == "synonyms"
                    ),
                    "SUCCESS",
                )
            ],
        )
        call("state-absent", verifies=["reset"])
        call(
            "descriptor-remains",
            assertions=[
                (
                    "reset removes state, not available feature",
                    lambda d: any(f["name"] == "synonyms" for f in d["features"]),
                    True,
                )
            ],
            verifies=["reset"],
            semantic=True,
        )
    finally:
        call("cleanup")
