"""Exact7.10/7.11 alias must_exist parser boundary and independent state reads."""

from evidence_runner import OMITTED
from legacy_release_selection import ALIAS_REMOVE_MUST_EXIST_RELEASES as REMOVE_MUST_EXIST_RELEASES

PREPARED_VERSIONS = {
    "7.10.2",
    "7.11.2",
    "7.12.1",
    "7.13.4",
    "7.14.2",
    "7.15.2",
    "7.16.3",
    "7.17.29",
}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    supported = version in REMOVE_MUST_EXIST_RELEASES
    specs = [
        ("create", "indices.create", "PUT", "/{index}", (), (200,)),
        ("initial", "indices.get_alias", "GET", "/{index}/_alias/{alias}", ("create",), (200,)),
        (
            "absent-before",
            "indices.exists_alias",
            "HEAD",
            "/{index}/_alias/{missing_alias}",
            ("initial",),
            (404,),
        ),
        (
            "missing-true",
            "indices.update_aliases",
            "POST",
            "/_aliases",
            ("absent-before",),
            (404,) if supported else (400,),
        ),
        (
            "after-true",
            "indices.get_alias",
            "GET",
            "/{index}/_alias/{alias}",
            ("missing-true",),
            (200,),
        ),
        (
            "missing-false",
            "indices.update_aliases",
            "POST",
            "/_aliases",
            ("after-true",),
            (404,) if supported else (400,),
        ),
        (
            "after-false",
            "indices.get_alias",
            "GET",
            "/{index}/_alias/{alias}",
            ("missing-false",),
            (200,),
        ),
        ("add-invalid", "indices.update_aliases", "POST", "/_aliases", ("after-false",), (400,)),
        (
            "after-invalid",
            "indices.get_alias",
            "GET",
            "/{index}/_alias/{alias}",
            ("add-invalid",),
            (200,),
        ),
        (
            "remove-existing",
            "indices.update_aliases",
            "POST",
            "/_aliases",
            ("after-invalid",),
            (200,) if supported else (400,),
        ),
        (
            "existing-state",
            "indices.exists_alias",
            "HEAD",
            "/{index}/_alias/{alias}",
            ("remove-existing",),
            (404,) if supported else (200,),
        ),
        ("restore", "indices.update_aliases", "POST", "/_aliases", ("existing-state",), (200,)),
        ("restored", "indices.get_alias", "GET", "/{index}/_alias/{alias}", ("restore",), (200,)),
        ("cleanup", "indices.delete", "DELETE", "/{index}", (), (200, 404)),
    ]
    if supported:
        specs.extend(
            [
                (
                    "missing-default",
                    "indices.update_aliases",
                    "POST",
                    "/_aliases",
                    ("absent-before",),
                    (404,),
                ),
                (
                    "after-default",
                    "indices.get_alias",
                    "GET",
                    "/{index}/_alias/{alias}",
                    ("missing-default",),
                    (200,),
                ),
                (
                    "mixed-false",
                    "indices.update_aliases",
                    "POST",
                    "/_aliases",
                    ("after-false",),
                    (200,),
                ),
                (
                    "after-mixed",
                    "indices.get_alias",
                    "GET",
                    "/{index}/_alias/{alias}",
                    ("mixed-false",),
                    (200,),
                ),
            ]
        )
    graph = {}
    for name, api, method, path, deps, expected in specs:
        identifier = "alias-guard." + name
        add(
            identifier,
            api,
            method,
            path,
            expected=expected,
            purpose="fixture-cleanup" if name == "cleanup" else "api-contract",
        )
        graph[identifier] = tuple("alias-guard." + d for d in deps)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Alias guard fixture not source-prepared for exact release")
    supported = catalog.version in REMOVE_MUST_EXIST_RELEASES
    values = {
        "index": prefix + "-alias-guard",
        "alias": prefix + "-guard-alias",
        "missing_alias": prefix + "-absent-alias",
    }

    def call(name, body=OMITTED, assertions=(), verifies=()):
        case = catalog.cases["alias-guard." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            verifies=["alias-guard." + d for d in verifies],
            semantic=bool(assertions),
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def action(kind, alias, must_exist=OMITTED):
        value = {"index": values["index"], "alias": alias}
        if must_exist is not OMITTED:
            value["must_exist"] = must_exist
        return {"actions": [{kind: value}]}

    unchanged = [
        (
            "original alias still present",
            lambda d: sorted(d[values["index"]]["aliases"]),
            [values["alias"]],
        )
    ]
    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    parser_error = [
        ("must_exist rejected by parser", lambda d: "must_exist" in str(d["error"]), True)
    ]
    try:
        call(
            "create",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "aliases": {values["alias"]: {}},
            },
            ack,
        )
        call("initial", assertions=unchanged, verifies=("create",))
        call("absent-before")
        absent = [
            ("empty alias expansion", lambda d: d["error"]["type"], "aliases_not_found_exception")
        ]
        if supported:
            call("missing-default", action("remove", values["missing_alias"]), absent)
            call("after-default", assertions=unchanged, verifies=("missing-default",))
        call(
            "missing-true",
            action("remove", values["missing_alias"], True),
            [
                (
                    "required alias absent",
                    lambda d: d["error"]["type"],
                    "resource_not_found_exception",
                )
            ]
            if supported
            else parser_error,
        )
        call("after-true", assertions=unchanged, verifies=("missing-true",))
        call(
            "missing-false",
            action("remove", values["missing_alias"], False),
            absent if supported else parser_error,
        )
        call("after-false", assertions=unchanged, verifies=("missing-false",))
        if supported:
            mixed = action("remove", values["missing_alias"], False)
            mixed["actions"] += action("add", values["alias"])["actions"]
            call("mixed-false", mixed, ack)
            call("after-mixed", assertions=unchanged, verifies=("mixed-false",))
        call("add-invalid", action("add", values["alias"], False), parser_error)
        call("after-invalid", assertions=unchanged, verifies=("add-invalid",))
        call(
            "remove-existing",
            action("remove", values["alias"], True),
            ack if supported else parser_error,
        )
        call("existing-state", verifies=("remove-existing",))
        call("restore", action("add", values["alias"]), ack)
        call("restored", assertions=unchanged, verifies=("restore",))
    finally:
        call("cleanup")
