"""Exact7.7 default release gates; negative GET observations, no enabled API claims."""

PREPARED_VERSIONS = {"7.7.1"}


def declare(add, version):
    if version not in PREPARED_VERSIONS:
        return {}
    graph = {}
    for name, api, path in [
        ("identity", "info", "/"),
        ("component-all", "cluster.get_component_template", "/_component_template"),
        ("component-named", "cluster.get_component_template", "/_component_template/{name}"),
        ("data-stream-all", "indices.get_data_streams", "/_data_streams"),
        ("data-stream-named", "indices.get_data_streams", "/_data_streams/{name}"),
    ]:
        identifier = "feature-gates." + name
        add(
            identifier,
            api,
            "GET",
            path,
            expected=(200,) if name == "identity" else (400, 404, 405),
            purpose="fixture-precondition" if name == "identity" else "default-feature-gate-probe",
        )
        graph[identifier] = () if name == "identity" else ("feature-gates.identity",)
    return graph


def execute(run, catalog, prefix):
    if catalog.version not in PREPARED_VERSIONS:
        raise ValueError("Default gate probes not prepared for exact release")
    for name in [
        "identity",
        "component-all",
        "component-named",
        "data-stream-all",
        "data-stream-named",
    ]:
        case = catalog.cases["feature-gates." + name]
        checks = (
            [
                (
                    "exact default release version",
                    lambda d: d["version"]["number"],
                    catalog.version,
                ),
                ("release build, not snapshot", lambda d: d["version"]["build_snapshot"], False),
                (
                    "pinned source prefix",
                    lambda d: (
                        isinstance(d["version"]["build_hash"], str)
                        and 7 <= len(d["version"]["build_hash"]) <= 40
                        and catalog.inventory["source_commit"].startswith(
                            d["version"]["build_hash"]
                        )
                    ),
                    True,
                ),
            ]
            if name == "identity"
            else [
                (
                    "default route gives an explicit error, not metadata success",
                    lambda d: isinstance(d.get("error"), (str, dict)),
                    True,
                ),
            ]
        )
        result = catalog.execute(
            run,
            case.id,
            values={"name": prefix + "-gated-absent"},
            assertions=checks,
            depends_on=case.dependency_plan,
            semantic=False,
        )
        print(case.id, result.state, result.status, flush=True)
