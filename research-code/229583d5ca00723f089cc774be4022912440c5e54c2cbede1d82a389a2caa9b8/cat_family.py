"""CAT formats backed by actual index, alias, template and snapshot fixtures."""

from evidence_runner import OMITTED
from legacy_release_selection import EARLY_SEVEN_PILOTS

TABLES = [
    ("aliases", ["/_cat/aliases", "/_cat/aliases/{alias}"], "alias,index"),
    ("allocation", ["/_cat/allocation", "/_cat/allocation/_local"], "node,shards"),
    ("circuit_breaker", ["/_cat/circuit_breaker", "/_cat/circuit_breaker/request"], ""),
    (
        "component_templates",
        ["/_cat/component_templates", "/_cat/component_templates/{component}"],
        "name",
    ),
    ("count", ["/_cat/count", "/_cat/count/{index}"], "count"),
    ("fielddata", ["/_cat/fielddata", "/_cat/fielddata/text"], "field,size"),
    ("health", ["/_cat/health"], "status,node.total"),
    ("indices", ["/_cat/indices", "/_cat/indices/{index}"], "index,docs.count"),
    ("master", ["/_cat/master"], "node"),
    ("nodeattrs", ["/_cat/nodeattrs"], "node,attr,value"),
    ("nodes", ["/_cat/nodes"], "name,version"),
    ("pending_tasks", ["/_cat/pending_tasks"], ""),
    ("plugins", ["/_cat/plugins"], ""),
    ("recovery", ["/_cat/recovery", "/_cat/recovery/{index}"], "index,stage"),
    ("repositories", ["/_cat/repositories"], "id,type"),
    ("segments", ["/_cat/segments", "/_cat/segments/{index}"], "index,segment,docs.count"),
    ("shards", ["/_cat/shards", "/_cat/shards/{index}"], "index,shard,prirep,state"),
    ("snapshots", ["/_cat/snapshots", "/_cat/snapshots/{repository}"], "id,status,indices"),
    ("tasks", ["/_cat/tasks"], ""),
    ("templates", ["/_cat/templates", "/_cat/templates/{template}"], "name"),
    ("thread_pool", ["/_cat/thread_pool", "/_cat/thread_pool/write*"], "node_name,name,active"),
]


def tables_for(version):
    legacy = version.startswith("6.")
    result = []
    for table in TABLES:
        name, paths, columns = table
        if (
            legacy or version in {"7.17.29", "8.0.1", "8.1.3"} or version in EARLY_SEVEN_PILOTS
        ) and name in {
            "circuit_breaker",
            "component_templates",
        }:
            continue
        if (
            version
            in {
                "8.19.24",
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
                "8.16.6",
                "8.17.10",
                "8.18.8",
                "9.0.8",
            }
            and name == "circuit_breaker"
        ):
            continue
        if legacy:
            paths = [path.replace("/write*", "/bulk*") for path in paths]
        result.append((name, paths, columns))
    return result


def declare(add, version="9.5.6"):
    legacy = version.startswith("6.")
    limited_endpoints = legacy or version in EARLY_SEVEN_PILOTS
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        add("cat." + name, api, method, path, expected=expected, purpose=purpose)
        graph["cat." + name] = tuple("cat." + d for d in deps)

    case("create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    case(
        "seed", "bulk", "POST", "/{index}/_bulk?refresh=true", ("create",), purpose="fixture-setup"
    )
    case(
        "warm-fielddata",
        "search",
        "POST",
        "/{index}/_search",
        ("seed",),
        purpose="fixture-precondition",
    )
    case(
        "repository",
        "snapshot.create_repository",
        "PUT",
        "/_snapshot/{repository}",
        purpose="fixture-setup",
    )
    case(
        "snapshot",
        "snapshot.create",
        "PUT",
        "/_snapshot/{repository}/one?wait_for_completion=true",
        ("seed", "repository"),
        purpose="fixture-setup",
    )
    if not limited_endpoints:
        case(
            "component",
            "cluster.put_component_template",
            "PUT",
            "/_component_template/{component}",
            purpose="fixture-setup",
        )
    case(
        "template", "indices.put_template", "PUT", "/_template/{template}", purpose="fixture-setup"
    )
    for name, paths, columns in tables_for(version):
        for variant, path in enumerate(paths):
            for output in ["json", "text"]:
                query = "?format=json" if output == "json" else "?v=true"
                if columns:
                    query += "&h=" + columns
                case(
                    name + "." + str(variant) + "." + output,
                    "cat." + name,
                    "GET",
                    path + query,
                    ("warm-fielddata", "snapshot", "template")
                    if limited_endpoints
                    else ("warm-fielddata", "snapshot", "component", "template"),
                    expected=(400,)
                    if limited_endpoints
                    and version not in {"7.14.2", "7.15.2", "7.16.3"}
                    and name == "snapshots"
                    and variant == 0
                    else (200,),
                )
    case("help", "cat.help", "GET", "/_cat")
    for name, api, path in [
        ("snapshot", "snapshot.delete", "/_snapshot/{repository}/one"),
        ("repository", "snapshot.delete_repository", "/_snapshot/{repository}"),
        ("component", "cluster.delete_component_template", "/_component_template/{component}"),
        ("template", "indices.delete_template", "/_template/{template}"),
        ("index", "indices.delete", "/{index}"),
    ]:
        if limited_endpoints and name == "component":
            continue
        case("cleanup-" + name, api, "DELETE", path, expected=(200, 404), purpose="cleanup")
    return graph


def execute(run, catalog, prefix):
    legacy = catalog.version.startswith("6.")
    limited_endpoints = legacy or catalog.version in EARLY_SEVEN_PILOTS
    values = {
        "index": prefix + "-cat",
        "alias": prefix + "-cat-alias",
        "repository": prefix + "-cat-repo",
        "component": prefix + "-cat-component",
        "template": prefix + "-cat-template",
    }

    def call(name, body=OMITTED, assertions=(), semantic=False, ndjson=False):
        case = catalog.cases["cat." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            content_type="application/x-ndjson" if ndjson else "application/json",
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    index_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "aliases": {values["alias"]: {}},
        "mappings": {"properties": {"text": {"type": "text", "fielddata": True}}},
    }
    if legacy:
        index_body["mappings"] = {"fixture": index_body["mappings"]}
    call("create", index_body, ack)
    try:
        payload = b'{"index":{"_id":"one"}}\n{"text":"fixture"}\n{"index":{"_id":"two"}}\n{"text":"fixture"}\n{"index":{"_id":"three"}}\n{"text":"fixture"}\n'
        if legacy:
            payload = payload.replace(b'{"index":{', b'{"index":{"_type":"fixture",')
        call("seed", payload, [("no bulk errors", lambda d: d["errors"], False)], ndjson=True)
        call(
            "warm-fielddata",
            {"size": 0, "aggs": {"words": {"terms": {"field": "text"}}}},
            [
                (
                    "fielddata-backed aggregation sees three docs",
                    lambda d: d["aggregations"]["words"]["buckets"][0]["doc_count"],
                    3,
                )
            ],
        )
        call(
            "repository",
            {"type": "fs", "settings": {"location": "/tmp/es-snapshots/" + values["repository"]}},
            ack,
        )
        call(
            "snapshot",
            {"indices": values["index"], "include_global_state": False},
            [("snapshot succeeded", lambda d: d["snapshot"]["state"], "SUCCESS")],
        )
        if not limited_endpoints:
            call("component", {"template": {"settings": {"number_of_replicas": 0}}}, ack)
        call(
            "template",
            {"index_patterns": [prefix + "-cat-template-*"], "settings": {"number_of_replicas": 0}},
            ack,
        )
        for name, paths, _columns in tables_for(catalog.version):
            for variant, _path in enumerate(paths):
                if (
                    limited_endpoints
                    and catalog.version not in {"7.14.2", "7.15.2", "7.16.3"}
                    and name == "snapshots"
                    and variant == 0
                ):
                    checks = [
                        (
                            "repository required by legacy CAT snapshots",
                            lambda d: "repository" in d["error"]["reason"],
                            True,
                        )
                    ]
                    call(name + "." + str(variant) + ".json", assertions=checks)
                    call(name + "." + str(variant) + ".text", assertions=checks)
                    continue
                assertions = [("JSON table is an array", lambda d: isinstance(d, list), True)]
                marker = None
                if name == "aliases":

                    def marker(d):
                        return any(
                            r["alias"] == values["alias"] and r["index"] == values["index"]
                            for r in d
                        )
                elif name in {"indices", "segments", "shards", "recovery"}:

                    def marker(d):
                        return any(r["index"] == values["index"] for r in d)
                elif name == "component_templates":

                    def marker(d):
                        return any(r["name"] == values["component"] for r in d)
                elif name == "templates":

                    def marker(d):
                        return any(r["name"] == values["template"] for r in d)
                elif name == "repositories":

                    def marker(d):
                        return any(r["id"] == values["repository"] and r["type"] == "fs" for r in d)
                elif name == "snapshots":

                    def marker(d):
                        return any(r["id"] == "one" and r["status"] == "SUCCESS" for r in d)
                elif name == "nodes":

                    def marker(d):
                        return any(
                            r["name"] == "es-cli-anchor" and r["version"] == catalog.version
                            for r in d
                        )
                elif name == "master":

                    def marker(d):
                        return any(r["node"] == "es-cli-anchor" for r in d)
                elif name == "fielddata":

                    def marker(d):
                        return any(r["field"] == "text" for r in d)
                elif name == "count" and variant == 1:

                    def marker(d):
                        return len(d) == 1 and int(d[0]["count"]) == 3

                if marker:
                    assertions.append(("fixture facts present", marker, True))
                call(
                    name + "." + str(variant) + ".json",
                    assertions=assertions,
                    semantic=marker is not None,
                )
                call(
                    name + "." + str(variant) + ".text",
                    assertions=[
                        (
                            "human table is nonempty text with header",
                            lambda d: isinstance(d, str) and bool(d.strip()),
                            True,
                        )
                    ],
                )
        call(
            "help",
            assertions=[
                (
                    "CAT help lists routes",
                    lambda d: isinstance(d, str) and "/_cat/indices" in d,
                    True,
                )
            ],
        )
    finally:
        for name in ["snapshot", "repository", "component", "template", "index"]:
            if limited_endpoints and name == "component":
                continue
            call("cleanup-" + name)
