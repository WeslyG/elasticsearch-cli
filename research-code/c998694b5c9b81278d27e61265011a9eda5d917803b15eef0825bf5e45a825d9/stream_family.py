"""Data stream metadata, dry run, rollover and alias migration effects."""

from evidence_runner import OMITTED


def declare(add, version="9.5.6"):
    seven = version in {
        "7.17.29",
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
    old_mapping = version in {
        "7.17.29",
        "8.19.24",
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
    graph = {}

    def case(name, api, method, path, deps=(), expected=(200,), purpose="api-contract"):
        mapping_cases = {
            "put-mapping",
            "get-mapping",
            "dry-mapping",
            "dry-mapping-readback",
            "backing-mapping",
        }
        settings_cases = {
            "put-settings",
            "get-settings",
            "dry-settings",
            "dry-settings-readback",
            "backing-settings",
        }
        if old_mapping and name in mapping_cases:
            return
        if seven and (
            name in settings_cases
            or "options" in name
            or (
                "lifecycle" in name
                and version not in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}
            )
        ):
            return
        if version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
            if name == "lifecycle-stats":
                return
            if name == "put-lifecycle":
                deps = ("lifecycle-initial",)
            if name == "delete-lifecycle":
                deps = ("get-lifecycle", "explain-lifecycle")
            if name == "remove-backing":
                deps = ("lifecycle-document-preserved",)
        if name == "rollover":
            deps = tuple(
                d
                for d in deps
                if not (old_mapping and d in mapping_cases) and not (seven and d in settings_cases)
            )
        if (
            version
            in {
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
            and name == "add-backing"
        ):
            deps = ("detached-count", "detached-document")
        add("stream." + name, api, method, path, expected=expected, purpose=purpose)
        graph["stream." + name] = tuple("stream." + d for d in deps)

    case(
        "template",
        "indices.put_index_template",
        "PUT",
        "/_index_template/{template}",
        purpose="fixture-setup",
    )
    case("create", "indices.create_data_stream", "PUT", "/_data_stream/{stream}", ("template",))
    case(
        "initial",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{stream}",
        ("create",),
        purpose="effect-check",
    )
    case("all", "indices.get_data_stream", "GET", "/_data_stream", ("create",))
    case("index", "create", "PUT", "/{stream}/_create/one?refresh=true", ("initial",), (201,))
    case("count", "count", "GET", "/{stream}/_count", ("index",), purpose="effect-check")
    case(
        "put-mapping",
        "indices.put_data_stream_mappings",
        "PUT",
        "/_data_stream/{stream}/_mappings",
        ("initial",),
    )
    case(
        "get-mapping",
        "indices.get_data_stream_mappings",
        "GET",
        "/_data_stream/{stream}/_mappings",
        ("put-mapping",),
        purpose="effect-check",
    )
    case(
        "dry-mapping",
        "indices.put_data_stream_mappings",
        "PUT",
        "/_data_stream/{stream}/_mappings?dry_run=true",
        ("put-mapping",),
    )
    case(
        "dry-mapping-readback",
        "indices.get_data_stream_mappings",
        "GET",
        "/_data_stream/{stream}/_mappings",
        ("dry-mapping",),
        purpose="effect-check",
    )
    if version == "8.19.24":
        case(
            "settings-rejected",
            "indices.put_data_stream_settings",
            "PUT",
            "/_data_stream/{stream}/_settings",
            ("initial",),
        )
        case(
            "settings-rejected-readback",
            "indices.get_data_stream_settings",
            "GET",
            "/_data_stream/{stream}/_settings",
            ("settings-rejected",),
            purpose="effect-check",
        )
        case(
            "old-backing-settings",
            "indices.get_settings",
            "GET",
            "/{oldbacking}/_settings?flat_settings=true",
            ("rollover",),
            purpose="effect-check",
        )
    case(
        "put-settings",
        "indices.put_data_stream_settings",
        "PUT",
        "/_data_stream/{stream}/_settings",
        ("initial",),
    )
    case(
        "get-settings",
        "indices.get_data_stream_settings",
        "GET",
        "/_data_stream/{stream}/_settings",
        ("put-settings",),
        purpose="effect-check",
    )
    case(
        "dry-settings",
        "indices.put_data_stream_settings",
        "PUT",
        "/_data_stream/{stream}/_settings?dry_run=true",
        ("put-settings",),
    )
    case(
        "dry-settings-readback",
        "indices.get_data_stream_settings",
        "GET",
        "/_data_stream/{stream}/_settings",
        ("dry-settings",),
        purpose="effect-check",
    )
    case(
        "rollover",
        "indices.rollover",
        "POST",
        "/{stream}/_rollover?wait_for_active_shards=all",
        ("get-mapping", "get-settings", "count"),
    )
    case(
        "rolled-stream",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{stream}",
        ("rollover",),
        purpose="effect-check",
    )
    case(
        "backing-mapping",
        "indices.get_mapping",
        "GET",
        "/{backing}/_mapping",
        ("rolled-stream",),
        purpose="effect-check",
    )
    case(
        "backing-settings",
        "indices.get_settings",
        "GET",
        "/{backing}/_settings?flat_settings=true",
        ("rolled-stream",),
        purpose="effect-check",
    )
    for name, path in [("all", "/_data_stream/_stats"), ("named", "/_data_stream/{stream}/_stats")]:
        case("stats." + name, "indices.data_streams_stats", "GET", path, ("rolled-stream",))
    case(
        "put-lifecycle",
        "indices.put_data_lifecycle",
        "PUT",
        "/_data_stream/{stream}/_lifecycle",
        ("create",),
    )
    case(
        "get-lifecycle",
        "indices.get_data_lifecycle",
        "GET",
        "/_data_stream/{stream}/_lifecycle?include_defaults=true",
        ("put-lifecycle",),
        purpose="effect-check",
    )
    case(
        "explain-lifecycle",
        "indices.explain_data_lifecycle",
        "GET",
        "/{oldbacking}/_lifecycle/explain",
        ("put-lifecycle", "initial"),
    )
    case(
        "lifecycle-stats",
        "indices.get_data_lifecycle_stats",
        "GET",
        "/_lifecycle/stats",
        ("put-lifecycle",),
    )
    case(
        "delete-lifecycle",
        "indices.delete_data_lifecycle",
        "DELETE",
        "/_data_stream/{stream}/_lifecycle",
        ("put-lifecycle",),
    )
    case(
        "lifecycle-removed",
        "indices.get_data_lifecycle",
        "GET",
        "/_data_stream/{stream}/_lifecycle",
        ("delete-lifecycle",),
        purpose="effect-check",
    )
    case(
        "put-options",
        "indices.put_data_stream_options",
        "PUT",
        "/_data_stream/{stream}/_options",
        ("create",),
    )
    case(
        "get-options",
        "indices.get_data_stream_options",
        "GET",
        "/_data_stream/{stream}/_options",
        ("put-options",),
        purpose="effect-check",
    )
    case(
        "delete-options",
        "indices.delete_data_stream_options",
        "DELETE",
        "/_data_stream/{stream}/_options",
        ("put-options",),
    )
    case(
        "options-removed",
        "indices.get_data_stream_options",
        "GET",
        "/_data_stream/{stream}/_options",
        ("delete-options",),
        purpose="effect-check",
    )
    case(
        "remove-backing",
        "indices.modify_data_stream",
        "POST",
        "/_data_stream/_modify",
        ("rolled-stream",),
    )
    case(
        "removed-backing-readback",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{stream}",
        ("remove-backing",),
        purpose="effect-check",
    )
    case(
        "add-backing",
        "indices.modify_data_stream",
        "POST",
        "/_data_stream/_modify",
        ("removed-backing-readback",),
    )
    case(
        "added-backing-readback",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{stream}",
        ("add-backing",),
        purpose="effect-check",
    )
    if version in {
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
        case(
            "detached-count",
            "count",
            "GET",
            "/{stream}/_count",
            ("removed-backing-readback",),
            purpose="effect-check",
        )
        case(
            "detached-document",
            "get",
            "GET",
            "/{oldbacking}/_doc/one",
            ("removed-backing-readback",),
            purpose="effect-check",
        )
        case(
            "reattached-count",
            "count",
            "GET",
            "/{stream}/_count",
            ("added-backing-readback",),
            purpose="effect-check",
        )
    case(
        "promote-regular",
        "indices.promote_data_stream",
        "POST",
        "/_data_stream/_promote/{stream}",
        ("create",),
    )
    case(
        "promoted-state",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{stream}",
        ("promote-regular",),
        purpose="effect-check",
    )
    case(
        "migration-index",
        "indices.create",
        "PUT",
        "/{migration_index}",
        ("template",),
        purpose="fixture-setup",
    )
    case(
        "migrate",
        "indices.migrate_to_data_stream",
        "POST",
        "/_data_stream/_migrate/{migration_stream}",
        ("migration-index",),
    )
    case(
        "migration-readback",
        "indices.get_data_stream",
        "GET",
        "/_data_stream/{migration_stream}",
        ("migrate",),
        purpose="effect-check",
    )
    case(
        "migration-write",
        "create",
        "PUT",
        "/{migration_stream}/_create/one?refresh=true",
        ("migrate",),
        (201,),
    )
    case(
        "migration-count",
        "count",
        "GET",
        "/{migration_stream}/_count",
        ("migration-write",),
        purpose="effect-check",
    )
    for name, api, path in [
        ("main", "indices.delete_data_stream", "/_data_stream/{stream}"),
        ("migration", "indices.delete_data_stream", "/_data_stream/{migration_stream}"),
        ("migration-index", "indices.delete", "/{migration_index}"),
        ("old-backing", "indices.delete", "/{oldbacking}"),
        ("template", "indices.delete_index_template", "/_index_template/{template}"),
    ]:
        deps = (
            ("cleanup-migration",)
            if name == "migration-index"
            else ("cleanup-main",)
            if name == "old-backing"
            else ()
        )
        case("cleanup-" + name, api, "DELETE", path, deps, (200, 404), purpose="cleanup")
    if version in {"8.8.2", "8.9.2", "8.10.4"}:
        for name, api, method, path in [
            ("get", "indices.get_data_lifecycle", "GET", "/_data_stream/{stream}/_lifecycle"),
            ("put", "indices.put_data_lifecycle", "PUT", "/_data_stream/{stream}/_lifecycle"),
            (
                "delete",
                "indices.delete_data_lifecycle",
                "DELETE",
                "/_data_stream/{stream}/_lifecycle",
            ),
            (
                "explain",
                "indices.explain_data_lifecycle",
                "GET",
                "/{oldbacking}/_lifecycle/explain",
            ),
        ]:
            case("dlm-disabled-" + name, api, method, path, ("count",), (400,))
        deps = tuple("dlm-disabled-" + name for name in ["get", "put", "delete", "explain"])
        case(
            "dlm-disabled-metadata",
            "indices.get_data_stream",
            "GET",
            "/_data_stream/{stream}",
            deps,
            purpose="effect-check",
        )
        case("dlm-disabled-count", "count", "GET", "/{stream}/_count", deps, purpose="effect-check")
    if version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
        case(
            "lifecycle-invalid",
            "indices.put_data_lifecycle",
            "PUT",
            "/_data_stream/{stream}/_lifecycle",
            ("stats.named",),
            (400,),
        )
        case(
            "lifecycle-initial",
            "indices.get_data_lifecycle",
            "GET",
            "/_data_stream/{stream}/_lifecycle",
            ("lifecycle-invalid",),
            purpose="effect-check",
        )
        case(
            "lifecycle-explain-removed",
            "indices.explain_data_lifecycle",
            "GET",
            "/{oldbacking}/_lifecycle/explain",
            ("lifecycle-removed",),
            purpose="effect-check",
        )
        case(
            "lifecycle-count-preserved",
            "count",
            "GET",
            "/{stream}/_count",
            ("lifecycle-explain-removed",),
            purpose="effect-check",
        )
        case(
            "lifecycle-document-preserved",
            "get",
            "GET",
            "/{oldbacking}/_doc/one",
            ("lifecycle-count-preserved",),
            purpose="effect-check",
        )
    return graph


def execute(run, catalog, prefix, focused=False):
    seven = catalog.version in {
        "7.17.29",
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
    old_mapping = catalog.version in {
        "7.17.29",
        "8.19.24",
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
    eight = catalog.version == "8.19.24"
    values = {
        "stream": prefix + "-stream-main",
        "template": prefix + "-stream-template",
        "migration_stream": prefix + "-stream-migrated",
        "migration_index": prefix + "-migration-seed",
        "backing": "unavailable",
        "oldbacking": "unavailable",
    }

    def call(name, body=OMITTED, assertions=(), verifies=(), semantic=False):
        case = catalog.cases["stream." + name]
        result = catalog.execute(
            run,
            case.id,
            values=values,
            body=body,
            assertions=assertions,
            depends_on=case.dependency_plan,
            semantic=semantic,
            verifies=["stream." + n for n in verifies],
        )
        print(case.id, result.state, result.status, flush=True)
        return result

    def stream(data):
        return next(row for row in data["data_streams"] if row["name"] == values["stream"])

    def properties(data):
        mapping = stream(data)["mappings"]
        return mapping.get("_doc", mapping).get("properties", {})

    def stream_setting(data):
        key = "number_of_shards" if eight else "refresh_interval"
        return str(stream(data)["settings"]["index"][key])

    def options():
        call("put-options", {"failure_store": {"enabled": True}}, ack)
        call(
            "get-options",
            assertions=[
                (
                    "failure store enabled",
                    lambda d: stream(d)["options"]["failure_store"]["enabled"],
                    True,
                )
            ],
            verifies=["put-options"],
            semantic=True,
        )
        call("delete-options", assertions=ack)
        call(
            "options-removed",
            assertions=[
                ("deleted options member is omitted", lambda d: "options" in stream(d), False)
            ],
            verifies=["delete-options"],
            semantic=True,
        )

    def promote():
        call("promote-regular", assertions=ack)
        call(
            "promoted-state",
            assertions=[
                ("still a regular stream", lambda d: stream(d)["replicated"], False),
                ("stream identity preserved", lambda d: stream(d)["name"], values["stream"]),
            ],
            verifies=["promote-regular"],
            semantic=True,
        )

    ack = [("acknowledged", lambda d: d["acknowledged"], True)]
    call(
        "template",
        {
            "index_patterns": [prefix + "-stream-*"],
            "data_stream": {},
            "priority": 300,
            "template": {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {"@timestamp": {"type": "date"}, "n": {"type": "integer"}}
                },
            },
        },
        ack,
    )
    try:
        call("create", assertions=ack)
        response = call(
            "initial",
            assertions=[("one initial backing index", lambda d: len(stream(d)["indices"]), 1)],
            verifies=["create"],
            semantic=True,
        )
        indices = (response.data or {}).get("data_streams", [{}])[0].get("indices", [])
        values["oldbacking"] = indices[0]["index_name"] if indices else "unavailable"
        call(
            "all",
            assertions=[("fixture stream listed", lambda d: stream(d)["name"], values["stream"])],
        )
        if focused:
            options()
            promote()
            return
        document = {"@timestamp": "2026-11-05T00:00:00Z", "n": 1}
        call(
            "index",
            document,
            [("written to backing index", lambda d: d["_index"], values["oldbacking"])],
        )
        call(
            "count",
            assertions=[("stream sees document", lambda d: d["count"], 1)],
            verifies=["index"],
            semantic=True,
        )
        if catalog.version in {"8.8.2", "8.9.2", "8.10.4"}:
            for name in ["get", "put", "delete", "explain"]:
                call(
                    "dlm-disabled-" + name,
                    {"data_retention": "1d"} if name == "put" else OMITTED,
                    [
                        (
                            "default build has no lifecycle REST handler",
                            lambda d: "no handler found" in str(d["error"]),
                            True,
                        )
                    ],
                )
            call(
                "dlm-disabled-metadata",
                assertions=[
                    (
                        "disabled lifecycle not installed on real stream",
                        lambda d: "lifecycle" not in stream(d),
                        True,
                    ),
                    (
                        "real backing index unchanged",
                        lambda d: stream(d)["indices"][0]["index_name"],
                        values["oldbacking"],
                    ),
                ],
                verifies=["dlm-disabled-put", "dlm-disabled-delete"],
                semantic=True,
            )
            call(
                "dlm-disabled-count",
                assertions=[("one real stream doc preserved", lambda d: d["count"], 1)],
                verifies=["dlm-disabled-put", "dlm-disabled-delete"],
                semantic=True,
            )
        if not old_mapping:
            call(
                "put-mapping",
                {"properties": {"added": {"type": "keyword"}}},
                [
                    (
                        "mapping applied to stream",
                        lambda d: stream(d)["applied_to_data_stream"],
                        True,
                    )
                ],
            )
            call(
                "get-mapping",
                assertions=[
                    (
                        "persisted stream mapping",
                        lambda d: properties(d)["added"]["type"],
                        "keyword",
                    )
                ],
                verifies=["put-mapping"],
                semantic=True,
            )
            call("dry-mapping", {"properties": {"dry_only": {"type": "keyword"}}})
            call(
                "dry-mapping-readback",
                assertions=[
                    ("dry-run field not persisted", lambda d: "dry_only" in properties(d), False)
                ],
                verifies=["dry-mapping"],
                semantic=True,
            )
        if eight:
            call(
                "settings-rejected",
                {"index.refresh_interval": "5s"},
                [
                    (
                        "HTTP 200 contains an application-level refusal",
                        lambda d: stream(d)["applied_to_data_stream"],
                        False,
                    ),
                    (
                        "refusal identifies requested setting",
                        lambda d: "index.refresh_interval" in stream(d)["error"],
                        True,
                    ),
                ],
            )
            call(
                "settings-rejected-readback",
                assertions=[
                    (
                        "rejected setting absent",
                        lambda d: "refresh_interval" in stream(d)["settings"].get("index", {}),
                        False,
                    )
                ],
                verifies=["settings-rejected"],
                semantic=True,
            )
        if not seven:
            call(
                "put-settings",
                {"index.number_of_shards": 2} if eight else {"index.refresh_interval": "5s"},
                [
                    (
                        "settings applied to stream",
                        lambda d: stream(d)["applied_to_data_stream"],
                        True,
                    )
                ],
            )
            call(
                "get-settings",
                assertions=[("stream setting persisted", stream_setting, "2" if eight else "5s")],
                verifies=["put-settings"],
                semantic=True,
            )
            call(
                "dry-settings",
                {"index.number_of_shards": 3} if eight else {"index.refresh_interval": "30s"},
            )
            call(
                "dry-settings-readback",
                assertions=[
                    ("dry-run keeps previous setting", stream_setting, "2" if eight else "5s")
                ],
                verifies=["dry-settings"],
                semantic=True,
            )
        call("rollover", {}, [("stream rolled", lambda d: d["rolled_over"], True)])
        response = call(
            "rolled-stream",
            assertions=[("two backing indices", lambda d: len(stream(d)["indices"]), 2)],
            verifies=["rollover"],
            semantic=True,
        )
        indices = (response.data or {}).get("data_streams", [{}])[0].get("indices", [])
        values["backing"] = indices[-1]["index_name"] if indices else "unavailable"
        backing = values["backing"]
        if not old_mapping:
            call(
                "backing-mapping",
                assertions=[
                    (
                        "new backing inherits stream mapping",
                        lambda d: d[backing]["mappings"]["properties"]["added"]["type"],
                        "keyword",
                    ),
                    (
                        "dry mapping absent from new backing",
                        lambda d: "dry_only" in d[backing]["mappings"]["properties"],
                        False,
                    ),
                ],
                verifies=["put-mapping", "rollover", "dry-mapping"],
                semantic=True,
            )
        if not seven:
            call(
                "backing-settings",
                assertions=[
                    (
                        "new backing inherits stream setting",
                        lambda d: d[backing]["settings"][
                            "index.number_of_shards" if eight else "index.refresh_interval"
                        ],
                        "2" if eight else "5s",
                    )
                ],
                verifies=["put-settings", "rollover", "dry-settings"],
                semantic=True,
            )
        if eight:
            call(
                "old-backing-settings",
                assertions=[
                    (
                        "existing backing retains original shard count",
                        lambda d: d[values["oldbacking"]]["settings"]["index.number_of_shards"],
                        "1",
                    )
                ],
                verifies=["put-settings", "rollover"],
                semantic=True,
            )
        for name in ["all", "named"]:
            call(
                "stats." + name,
                assertions=[
                    (
                        "fixture stats contain two backing indices",
                        lambda d: next(
                            row
                            for row in d["data_streams"]
                            if row["data_stream"] == values["stream"]
                        )["backing_indices"],
                        2,
                    )
                ],
            )
        if not seven or catalog.version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
            if catalog.version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
                call(
                    "lifecycle-invalid",
                    {"data_retention": "garbage"},
                    assertions=[
                        (
                            "invalid retention parsed before mutation",
                            lambda d: (
                                "data_retention" in str(d["error"]) and "garbage" in str(d["error"])
                            ),
                            True,
                        )
                    ],
                )
                call(
                    "lifecycle-initial",
                    assertions=[
                        (
                            "invalid request left lifecycle absent",
                            lambda d: "lifecycle" not in stream(d),
                            True,
                        )
                    ],
                    verifies=["lifecycle-invalid"],
                    semantic=True,
                )
            call("put-lifecycle", {"data_retention": "7d", "enabled": True}, ack)
            call(
                "get-lifecycle",
                assertions=[
                    (
                        "seven-day retention configured",
                        lambda d: stream(d)["lifecycle"]["data_retention"],
                        "7d",
                    )
                ],
                verifies=["put-lifecycle"],
                semantic=True,
            )
            call(
                "explain-lifecycle",
                assertions=[
                    (
                        "backing lifecycle reported",
                        lambda d: values["oldbacking"] in d["indices"],
                        True,
                    ),
                    *(
                        [
                            (
                                "actual backing lifecycle managed",
                                lambda d: d["indices"][values["oldbacking"]][
                                    "managed_by_lifecycle"
                                ],
                                True,
                            )
                        ]
                        if catalog.version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}
                        else []
                    ),
                ],
            )
            if catalog.version not in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
                call(
                    "lifecycle-stats",
                    assertions=[("lifecycle stats object", lambda d: isinstance(d, dict), True)],
                )
            call("delete-lifecycle", assertions=ack)
            call(
                "lifecycle-removed",
                assertions=[
                    (
                        "retention removed",
                        lambda d: "data_retention" in stream(d).get("lifecycle", {}),
                        False,
                    )
                ],
                verifies=["delete-lifecycle"],
                semantic=True,
            )
            if catalog.version in {"8.11.4", "8.12.2", "8.13.4", "8.14.3", "8.15.5"}:
                call(
                    "lifecycle-explain-removed",
                    assertions=[
                        (
                            "backing index no longer lifecycle managed",
                            lambda d: d["indices"][values["oldbacking"]]["managed_by_lifecycle"],
                            False,
                        )
                    ],
                    verifies=["delete-lifecycle"],
                    semantic=True,
                )
                call(
                    "lifecycle-count-preserved",
                    assertions=[
                        (
                            "real document preserved through lifecycle configuration",
                            lambda d: d["count"],
                            1,
                        )
                    ],
                    verifies=["put-lifecycle", "delete-lifecycle"],
                    semantic=True,
                )
                call(
                    "lifecycle-document-preserved",
                    assertions=[
                        (
                            "original backing source unchanged",
                            lambda d: d["_source"],
                            {"@timestamp": "2026-11-05T00:00:00Z", "n": 1},
                        )
                    ],
                    verifies=["put-lifecycle", "delete-lifecycle"],
                    semantic=True,
                )
            if not seven:
                options()
        call(
            "remove-backing",
            {
                "actions": [
                    {
                        "remove_backing_index": {
                            "data_stream": values["stream"],
                            "index": values["oldbacking"],
                        }
                    }
                ]
            },
            ack,
        )
        call(
            "removed-backing-readback",
            assertions=[
                (
                    "old backing detached",
                    lambda d: [i["index_name"] for i in stream(d)["indices"]],
                    [backing],
                )
            ],
            verifies=["remove-backing"],
            semantic=True,
        )
        if catalog.version in {
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
            call(
                "detached-count",
                assertions=[
                    ("detached document absent from stream search", lambda d: d["count"], 0)
                ],
                verifies=["remove-backing"],
                semantic=True,
            )
            call(
                "detached-document",
                assertions=[
                    ("detaching preserves original document", lambda d: d["_source"]["n"], 1),
                    (
                        "document still in detached index",
                        lambda d: d["_index"],
                        values["oldbacking"],
                    ),
                ],
                verifies=["remove-backing"],
                semantic=True,
            )
        call(
            "add-backing",
            {
                "actions": [
                    {
                        "add_backing_index": {
                            "data_stream": values["stream"],
                            "index": values["oldbacking"],
                        }
                    }
                ]
            },
            ack,
        )
        call(
            "added-backing-readback",
            assertions=[
                (
                    "old backing reattached",
                    lambda d: sorted(i["index_name"] for i in stream(d)["indices"]),
                    sorted([backing, values["oldbacking"]]),
                )
            ],
            verifies=["add-backing"],
            semantic=True,
        )
        if catalog.version in {
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
            call(
                "reattached-count",
                assertions=[
                    ("reattached document visible through stream again", lambda d: d["count"], 1)
                ],
                verifies=["add-backing"],
                semantic=True,
            )
        promote()
        call(
            "migration-index",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {"@timestamp": {"type": "date"}, "n": {"type": "integer"}}
                },
                "aliases": {values["migration_stream"]: {"is_write_index": True}},
            },
            ack,
        )
        call("migrate", assertions=ack)
        call(
            "migration-readback",
            assertions=[
                (
                    "alias became stream using existing backing",
                    lambda d: d["data_streams"][0]["indices"][0]["index_name"],
                    values["migration_index"],
                )
            ],
            verifies=["migrate"],
            semantic=True,
        )
        call(
            "migration-write",
            document,
            [("migrated write destination", lambda d: d["_index"], values["migration_index"])],
        )
        call(
            "migration-count",
            assertions=[("migrated stream has document", lambda d: d["count"], 1)],
            verifies=["migration-write"],
            semantic=True,
        )
    finally:
        for name in ["main", "migration", "migration-index", "old-backing", "template"]:
            call("cleanup-" + name)
