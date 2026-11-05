"""Managed synonyms proven by changes to real search results."""

import json

from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    eight = version == "8.19.24"
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        if eight:
            if api.startswith("synonyms."):
                path = path.replace("?refresh=true", "")
            if name == "remove-block":
                api, method, path = "indices.put_settings", "PUT", "/{index}/_settings"
        add("synonym." + name, api, method, path, expected=expected, purpose=purpose)
        graph["synonym." + name] = tuple("synonym." + d for d in deps)

    if eight:
        add(
            "synonym.refresh-probe",
            "synonyms.put_synonym",
            "PUT",
            "/_synonyms/{probe_set}?refresh=true",
            expected=(400,),
            unsupported=("refresh",),
        )
        graph["synonym.refresh-probe"] = ()
        case(
            "probe-absent",
            "synonyms.get_synonym",
            "GET",
            "/_synonyms/{probe_set}",
            ("refresh-probe",),
            (404,),
            purpose="effect-check",
        )
        case(
            "cleanup-probe",
            "synonyms.delete_synonym",
            "DELETE",
            "/_synonyms/{probe_set}",
            expected=(200, 404),
            purpose="cleanup",
        )
    case("put", "synonyms.put_synonym", "PUT", "/_synonyms/{set}?refresh=true", expected=(201,))
    case("get", "synonyms.get_synonym", "GET", "/_synonyms/{set}", ("put",), purpose="effect-check")
    case("list", "synonyms.get_synonyms_sets", "GET", "/_synonyms?from=0&size=100", ("put",))
    case(
        "get-rule",
        "synonyms.get_synonym_rule",
        "GET",
        "/_synonyms/{set}/primary",
        ("put",),
        purpose="effect-check",
    )
    case("create", "indices.create", "PUT", "/{index}", ("put",), purpose="fixture-setup")
    case(
        "seed", "bulk", "POST", "/{index}/_bulk?refresh=true", ("create",), purpose="fixture-setup"
    )
    case("before", "search", "POST", "/{index}/_search", ("seed",), purpose="effect-check")
    case(
        "update-rule",
        "synonyms.put_synonym_rule",
        "PUT",
        "/_synonyms/{set}/primary?refresh=true",
        ("before",),
    )
    case(
        "rule-readback",
        "synonyms.get_synonym_rule",
        "GET",
        "/_synonyms/{set}/primary",
        ("update-rule",),
        purpose="effect-check",
    )
    case("after", "search", "POST", "/{index}/_search", ("rule-readback",), purpose="effect-check")
    for method in ["GET", "POST"]:
        case(
            "reload." + method.lower(),
            "indices.reload_search_analyzers",
            method,
            "/{index}/_reload_search_analyzers",
            ("after",),
        )
    case(
        "delete-rule",
        "synonyms.delete_synonym_rule",
        "DELETE",
        "/_synonyms/{set}/primary?refresh=true",
        ("after",),
    )
    case(
        "rule-absent",
        "synonyms.get_synonym_rule",
        "GET",
        "/_synonyms/{set}/primary",
        ("delete-rule",),
        (404,),
        purpose="effect-check",
    )
    case(
        "without-rule",
        "search",
        "POST",
        "/{index}/_search",
        ("delete-rule",),
        purpose="effect-check",
    )
    case(
        "restore-rule",
        "synonyms.put_synonym_rule",
        "PUT",
        "/_synonyms/{set}/primary?refresh=true",
        ("without-rule",),
        (201,),
    )
    case(
        "restored-search",
        "search",
        "POST",
        "/{index}/_search",
        ("restore-rule",),
        purpose="effect-check",
    )
    case("block", "indices.add_block", "PUT", "/{index}/_block/write", ("seed",))
    case("remove-block", "indices.remove_block", "DELETE", "/{index}/_block/write", ("block",))
    case(
        "write-after-unblock", "index", "PUT", "/{index}/_doc/unblocked", ("remove-block",), (201,)
    )
    case(
        "unblock-readback",
        "get",
        "GET",
        "/{index}/_doc/unblocked",
        ("write-after-unblock",),
        purpose="effect-check",
    )
    case(
        "cleanup-index",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    case(
        "cleanup-set",
        "synonyms.delete_synonym",
        "DELETE",
        "/_synonyms/{set}",
        ("cleanup-index",),
        expected=(200, 404),
        purpose="cleanup",
    )
    case(
        "set-absent",
        "synonyms.get_synonym",
        "GET",
        "/_synonyms/{set}",
        ("cleanup-set",),
        (404,),
        purpose="effect-check",
    )
    return graph


def execute(run, catalog, prefix):
    eight = catalog.version == "8.19.24"
    values = {
        "index": prefix + "-synonyms",
        "set": prefix + "-synonym-set",
        "probe_set": prefix + "-refresh-probe",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False, ndjson=False):
        case = catalog.cases["synonym." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["synonym." + n for n in verifies],
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def ids(data):
        return sorted(h["_id"] for h in data["hits"]["hits"])

    query = {"query": {"match": {"title": "pc"}}}
    if eight:
        call(
            "refresh-probe",
            {"synonyms_set": [{"id": "probe", "synonyms": "a, b"}]},
            [("unknown refresh parameter", lambda d: "refresh" in str(d["error"]), True)],
        )
        call("probe-absent", verifies=["refresh-probe"])

    call(
        "put",
        {
            "synonyms_set": [
                {"id": "primary", "synonyms": "pc, laptop"},
                {"id": "secondary", "synonyms": "workstation, desktop"},
            ]
        },
    )
    try:
        call(
            "get",
            assertions=[
                (
                    "both rules saved",
                    lambda d: sorted(r["id"] for r in d["synonyms_set"]),
                    ["primary", "secondary"],
                )
            ],
            verifies=["put"],
            semantic=True,
        )
        call(
            "list",
            assertions=[
                (
                    "fixture set listed",
                    lambda d: any(r["synonyms_set"] == values["set"] for r in d["results"]),
                    True,
                )
            ],
        )
        call(
            "get-rule",
            assertions=[("rule text exact", lambda d: d["synonyms"], "pc, laptop")],
            verifies=["put"],
            semantic=True,
        )
        call(
            "create",
            {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "filter": {
                            "managed": {
                                "type": "synonym_graph",
                                "synonyms_set": values["set"],
                                "updateable": True,
                            }
                        },
                        "analyzer": {
                            "managed_search": {
                                "tokenizer": "standard",
                                "filter": ["lowercase", "managed"],
                            }
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "title": {
                            "type": "text",
                            "analyzer": "standard",
                            "search_analyzer": "managed_search",
                        }
                    }
                },
            },
            [("index created", lambda d: d["acknowledged"], True)],
        )
        parts = []
        for identifier in ["laptop", "desktop"]:
            parts.extend([{"index": {"_id": identifier}}, {"title": identifier}])
        call(
            "seed",
            ("\n".join(json.dumps(p) for p in parts) + "\n").encode(),
            [("seed no errors", lambda d: d["errors"], False)],
            ndjson=True,
        )
        call(
            "before",
            query,
            [("original expansion", ids, ["laptop"])],
            verifies=["put"],
            semantic=True,
        )
        call("update-rule", {"synonyms": "pc, desktop"})
        call(
            "rule-readback",
            assertions=[("updated rule text", lambda d: d["synonyms"], "pc, desktop")],
            verifies=["update-rule"],
            semantic=True,
        )
        call(
            "after",
            query,
            [("updated expansion switches result", ids, ["desktop"])],
            verifies=["update-rule"],
            semantic=True,
        )
        for method in ["get", "post"]:
            call(
                "reload." + method,
                assertions=[
                    (
                        "fixture analyzer reloaded",
                        lambda d: any(
                            r["index"] == values["index"]
                            and "managed_search" in r["reloaded_analyzers"]
                            for r in d["reload_details"]
                        ),
                        True,
                    )
                ],
            )
        call("delete-rule")
        call("rule-absent")
        call(
            "without-rule",
            query,
            [("removed expansion matches nothing", ids, [])],
            verifies=["delete-rule"],
            semantic=True,
        )
        call("restore-rule", {"synonyms": "pc, laptop"})
        call(
            "restored-search",
            query,
            [("restored expansion", ids, ["laptop"])],
            verifies=["restore-rule"],
            semantic=True,
        )
        call("block")
        call("remove-block", {"index.blocks.write": False} if eight else OMITTED)
        call("write-after-unblock", {"title": "fixture"})
        call(
            "unblock-readback",
            assertions=[("write persisted", lambda d: d["_source"]["title"], "fixture")],
            verifies=["remove-block", "write-after-unblock"],
            semantic=True,
        )
    finally:
        if eight:
            call("cleanup-probe")
        call("cleanup-index")
        call("cleanup-set")
        call("set-absent")
