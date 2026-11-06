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
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
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
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
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
            (name in settings_cases and version != "9.1.10")
            or ("options" in name and version != "9.1.10")
            or (
                "lifecycle" in name
                and version
                not in {
                    "8.11.4",
                    "8.12.2",
                    "8.13.4",
                    "8.14.3",
                    "8.15.5",
                    "8.16.6",
                    "8.17.10",
                    "8.18.8",
                    "9.0.8",
                    "9.1.10",
                }
            )
        ):
            return
        if version in {
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
            "9.1.10",
        }:
            if name == "lifecycle-stats" and version not in {
                "8.17.10",
                "8.18.8",
                "9.0.8",
                "9.1.10",
            }:
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
                "8.16.6",
                "8.17.10",
                "8.18.8",
                "9.0.8",
                "9.1.10",
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
    if version in {"8.19.24", "9.1.10"}:
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
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
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
    if version in {
        "8.11.4",
        "8.12.2",
        "8.13.4",
        "8.14.3",
        "8.15.5",
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
    }:
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
    if version in {"8.17.10", "8.18.8", "9.0.8", "9.1.10", "8.16.6"}:
        specs = [
            (
                "before",
                "cluster.get_settings",
                "GET",
                "/_cluster/settings?flat_settings=true",
                ("get-lifecycle",),
                (200,),
            ),
            (
                "invalid",
                "cluster.put_settings",
                "PUT",
                "/_cluster/settings",
                ("lifecycle-global-before",),
                (400,),
            ),
            (
                "unchanged",
                "cluster.get_settings",
                "GET",
                "/_cluster/settings?flat_settings=true",
                ("lifecycle-global-invalid",),
                (200,),
            ),
            (
                "put",
                "cluster.put_settings",
                "PUT",
                "/_cluster/settings",
                ("lifecycle-global-unchanged",),
                (200,),
            ),
            (
                "cap",
                "indices.put_data_lifecycle",
                "PUT",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-put",),
                (200,),
            ),
            (
                "capped",
                "indices.get_data_lifecycle",
                "GET",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-cap",),
                (200,),
            ),
            (
                "default",
                "indices.put_data_lifecycle",
                "PUT",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-capped",),
                (200,),
            ),
            (
                "defaulted",
                "indices.get_data_lifecycle",
                "GET",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-default",),
                (200,),
            ),
            (
                "disable",
                "indices.put_data_lifecycle",
                "PUT",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-defaulted",),
                (200,),
            ),
            (
                "disabled",
                "indices.get_data_lifecycle",
                "GET",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-disable",),
                (200,),
            ),
            (
                "restore-stream",
                "indices.put_data_lifecycle",
                "PUT",
                "/_data_stream/{stream}/_lifecycle",
                (),
                (200,),
            ),
            ("restore-cluster", "cluster.put_settings", "PUT", "/_cluster/settings", (), (200,)),
            (
                "restored",
                "indices.get_data_lifecycle",
                "GET",
                "/_data_stream/{stream}/_lifecycle",
                ("lifecycle-global-restore-stream", "lifecycle-global-restore-cluster"),
                (200,),
            ),
            (
                "settings-restored",
                "cluster.get_settings",
                "GET",
                "/_cluster/settings?flat_settings=true",
                ("lifecycle-global-restore-cluster",),
                (200,),
            ),
            ("count", "count", "GET", "/{stream}/_count", ("lifecycle-global-restored",), (200,)),
        ]
        for name, api, method, path, deps, expected in specs:
            case("lifecycle-global-" + name, api, method, path, deps, expected)
    if version in {"8.17.10", "8.18.8", "9.0.8", "9.1.10"}:
        case(
            "lifecycle-stats-removed",
            "indices.get_data_lifecycle_stats",
            "GET",
            "/_lifecycle/stats",
            ("lifecycle-removed",),
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
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
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
        "8.16.6",
        "8.17.10",
        "8.18.8",
        "9.0.8",
        "9.1.10",
    }
    shard_only_settings = catalog.version in {"8.19.24", "9.1.10"}
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
        key = "number_of_shards" if shard_only_settings else "refresh_interval"
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
        if shard_only_settings:
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
        if not seven or catalog.version == "9.1.10":
            call(
                "put-settings",
                {"index.number_of_shards": 2}
                if shard_only_settings
                else {"index.refresh_interval": "5s"},
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
                assertions=[
                    (
                        "stream setting persisted",
                        stream_setting,
                        "2" if shard_only_settings else "5s",
                    )
                ],
                verifies=["put-settings"],
                semantic=True,
            )
            call(
                "dry-settings",
                {"index.number_of_shards": 3}
                if shard_only_settings
                else {"index.refresh_interval": "30s"},
            )
            call(
                "dry-settings-readback",
                assertions=[
                    (
                        "dry-run keeps previous setting",
                        stream_setting,
                        "2" if shard_only_settings else "5s",
                    )
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
        if not seven or catalog.version == "9.1.10":
            call(
                "backing-settings",
                assertions=[
                    (
                        "new backing inherits stream setting",
                        lambda d: d[backing]["settings"][
                            "index.number_of_shards"
                            if shard_only_settings
                            else "index.refresh_interval"
                        ],
                        "2" if shard_only_settings else "5s",
                    )
                ],
                verifies=["put-settings", "rollover", "dry-settings"],
                semantic=True,
            )
        if shard_only_settings:
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
        if not seven or catalog.version in {
            "8.11.4",
            "8.12.2",
            "8.13.4",
            "8.14.3",
            "8.15.5",
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
            "9.1.10",
        }:
            if catalog.version in {
                "8.11.4",
                "8.12.2",
                "8.13.4",
                "8.14.3",
                "8.15.5",
                "8.16.6",
                "8.17.10",
                "8.18.8",
                "9.0.8",
                "9.1.10",
            }:
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
            if catalog.version in {"8.17.10", "8.18.8", "9.0.8", "9.1.10", "8.16.6"}:
                default_key = "data_streams.lifecycle.retention.default"
                max_key = "data_streams.lifecycle.retention.max"
                keys = [default_key, max_key]
                before = call(
                    "lifecycle-global-before",
                    assertions=[
                        (
                            "owned lab has no pre-existing global retention overrides",
                            lambda d: all(
                                k not in d.get(scope, {})
                                for scope in ["persistent", "transient"]
                                for k in keys
                            ),
                            True,
                        )
                    ],
                )
                original = {key: (before.data or {}).get("transient", {}).get(key) for key in keys}
                try:
                    call(
                        "lifecycle-global-invalid",
                        {"transient": {default_key: "30d", max_key: "10d"}},
                        [
                            (
                                "default above max rejected",
                                lambda d: "cannot be greater than" in str(d["error"]),
                                True,
                            )
                        ],
                    )
                    call(
                        "lifecycle-global-unchanged",
                        assertions=[
                            (
                                "invalid update has no effect",
                                lambda d: {key: d.get("transient", {}).get(key) for key in keys},
                                original,
                            )
                        ],
                        verifies=["lifecycle-global-invalid"],
                        semantic=True,
                    )
                    call(
                        "lifecycle-global-put",
                        {"transient": {default_key: "30d", max_key: "90d"}},
                        ack,
                    )
                    call("lifecycle-global-cap", {"data_retention": "365d", "enabled": True}, ack)
                    call(
                        "lifecycle-global-capped",
                        assertions=[
                            (
                                "configured retention kept",
                                lambda d: stream(d)["lifecycle"]["data_retention"],
                                "365d",
                            ),
                            (
                                "global max actually effective",
                                lambda d: stream(d)["lifecycle"]["effective_retention"],
                                "90d",
                            ),
                            (
                                "max retention source",
                                lambda d: stream(d)["lifecycle"]["retention_determined_by"],
                                "max_global_retention",
                            ),
                            (
                                "actual global configuration",
                                lambda d: d["global_retention"],
                                {"default_retention": "30d", "max_retention": "90d"},
                            ),
                        ],
                        verifies=["lifecycle-global-put", "lifecycle-global-cap"],
                        semantic=True,
                    )
                    call("lifecycle-global-default", {"enabled": True}, ack)
                    call(
                        "lifecycle-global-defaulted",
                        assertions=[
                            (
                                "no explicit retention configured",
                                lambda d: "data_retention" in stream(d)["lifecycle"],
                                False,
                            ),
                            (
                                "global default actually effective",
                                lambda d: stream(d)["lifecycle"]["effective_retention"],
                                "30d",
                            ),
                            (
                                "default retention source",
                                lambda d: stream(d)["lifecycle"]["retention_determined_by"],
                                "default_global_retention",
                            ),
                        ],
                        verifies=["lifecycle-global-default"],
                        semantic=True,
                    )
                    call(
                        "lifecycle-global-disable",
                        {"data_retention": "365d", "enabled": False},
                        ack,
                    )
                    call(
                        "lifecycle-global-disabled",
                        assertions=[
                            (
                                "lifecycle disabled",
                                lambda d: stream(d)["lifecycle"]["enabled"],
                                False,
                            ),
                            (
                                "disabled has no effective retention",
                                lambda d: "effective_retention" in stream(d)["lifecycle"],
                                False,
                            ),
                        ],
                        verifies=["lifecycle-global-disable"],
                        semantic=True,
                    )
                finally:
                    call(
                        "lifecycle-global-restore-stream",
                        {"data_retention": "7d", "enabled": True},
                        ack,
                    )
                    if before.passed:
                        call("lifecycle-global-restore-cluster", {"transient": original}, ack)
                call(
                    "lifecycle-global-restored",
                    assertions=[
                        (
                            "original7d effective again",
                            lambda d: stream(d)["lifecycle"]["effective_retention"],
                            "7d",
                        ),
                        (
                            "original stream retention source",
                            lambda d: stream(d)["lifecycle"]["retention_determined_by"],
                            "data_stream_configuration",
                        ),
                        ("global configuration absent again", lambda d: d["global_retention"], {}),
                    ],
                    verifies=[
                        "lifecycle-global-restore-stream",
                        "lifecycle-global-restore-cluster",
                    ],
                    semantic=True,
                )
                call(
                    "lifecycle-global-settings-restored",
                    assertions=[
                        (
                            "original global setting overrides restored",
                            lambda d: {key: d.get("transient", {}).get(key) for key in keys},
                            original,
                        )
                    ],
                    verifies=["lifecycle-global-restore-cluster"],
                    semantic=True,
                )
                call(
                    "lifecycle-global-count",
                    assertions=[("original stream document survives", lambda d: d["count"], 1)],
                    verifies=[
                        "lifecycle-global-cap",
                        "lifecycle-global-default",
                        "lifecycle-global-disable",
                    ],
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
                        if catalog.version
                        in {
                            "8.11.4",
                            "8.12.2",
                            "8.13.4",
                            "8.14.3",
                            "8.15.5",
                            "8.16.6",
                            "8.17.10",
                            "8.18.8",
                            "9.0.8",
                            "9.1.10",
                        }
                        else []
                    ),
                ],
            )
            if catalog.version in {"8.17.10", "8.18.8", "9.0.8", "9.1.10"}:
                call(
                    "lifecycle-stats",
                    assertions=[
                        (
                            "owned enabled stream present",
                            lambda d: [
                                x for x in d["data_streams"] if x["name"] == values["stream"]
                            ],
                            [
                                {
                                    "name": values["stream"],
                                    "backing_indices_in_total": 2,
                                    "backing_indices_in_error": 0,
                                }
                            ],
                        ),
                        (
                            "count matches actual entries",
                            lambda d: d["data_stream_count"] == len(d["data_streams"]),
                            True,
                        ),
                    ],
                    verifies=["put-lifecycle"],
                    semantic=True,
                )
            elif catalog.version not in {
                "8.11.4",
                "8.12.2",
                "8.13.4",
                "8.14.3",
                "8.15.5",
                "8.16.6",
                "8.17.10",
                "8.18.8",
                "9.0.8",
                "9.1.10",
            }:
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
            if catalog.version in {"8.17.10", "8.18.8", "9.0.8", "9.1.10"}:
                call(
                    "lifecycle-stats-removed",
                    assertions=[
                        (
                            "removed lifecycle excludes owned stream",
                            lambda d: (
                                values["stream"] not in [x["name"] for x in d["data_streams"]]
                            ),
                            True,
                        ),
                        (
                            "removed count matches entries",
                            lambda d: d["data_stream_count"] == len(d["data_streams"]),
                            True,
                        ),
                    ],
                    verifies=["delete-lifecycle"],
                    semantic=True,
                )
            if catalog.version in {
                "8.11.4",
                "8.12.2",
                "8.13.4",
                "8.14.3",
                "8.15.5",
                "8.16.6",
                "8.17.10",
                "8.18.8",
                "9.0.8",
                "9.1.10",
            }:
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
            if not seven or catalog.version == "9.1.10":
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
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
            "9.1.10",
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
            "8.16.6",
            "8.17.10",
            "8.18.8",
            "9.0.8",
            "9.1.10",
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
