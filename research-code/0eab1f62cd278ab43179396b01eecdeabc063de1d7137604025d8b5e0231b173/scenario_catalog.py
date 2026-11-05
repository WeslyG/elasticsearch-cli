"""Explicit scenario metadata. Unplanned API dimensions remain visible obligations."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import parse_qsl, quote

from cat_family import declare as declare_cat
from cluster_family import declare as declare_cluster
from compat8_family import declare as declare_compat8
from document_family import declare as declare_document
from evidence_runner import OMITTED
from feature_family import declare as declare_feature
from handler_route_extensions import load_route_extensions
from legacy_document_family import declare as declare_legacy_document
from legacy_index_family import declare as declare_legacy_index
from legacy_metadata_family import declare as declare_legacy_metadata
from legacy_parameter_family import declare as declare_legacy_parameter
from legacy_query_family import declare as declare_legacy_query
from legacy_release_selection import (
    CANCEL_WITHOUT_WAIT_RELEASES,
    EARLY_SEVEN_PILOTS,
    FLAT_TASK_LIST_RELEASES,
    LEGACY_ROUTE_RELEASES,
    LEGACY_SPLIT_RELEASES,
    PREPARED_LEGACY_RELEASES,
    RETHROTTLE_NEGATIVE_RELEASES,
    ROUTE_VARIANT_RELEASES,
)
from legacy_route_family import declare as declare_legacy_route
from legacy_type_family import declare as declare_legacy_type
from managed_reindex_family import declare as declare_managed_reindex
from metadata_family import declare as declare_metadata
from migration_state_family import declare as declare_migration_state
from module_family import declare as declare_module
from painless_context_family import declare as declare_painless_context
from painless_execute_family import PREPARED_VERSIONS as PAINLESS_RELEASES
from painless_execute_family import declare as declare_painless_execute
from parameter_state_family import declare as declare_parameter_state
from query_family import declare as declare_query
from rank_eval_family import PREPARED_VERSIONS as RANK_EVAL_RELEASES
from rank_eval_family import declare as declare_rank_eval
from repository_family import declare as declare_repository
from resize_family import declare as declare_resize
from rest_definition_routes import definition_routes
from route_variant_family import declare as declare_route_variants
from secure_reload_family import PREPARED_VERSIONS as SECURE_RELOAD_RELEASES
from secure_reload_family import declare as declare_secure_reload
from stream_family import declare as declare_stream
from synonym_family import declare as declare_synonym
from system_wire_family import declare as declare_system_wire
from task_limit_family import declare as declare_task_limit
from template_family import declare as declare_template
from topology_family import declare as declare_topology
from transform_family import declare as declare_transform
from type_transition_family import PREPARED_VERSIONS as TYPE_TRANSITION_RELEASES
from type_transition_family import declare as declare_type_transition
from wire_family import declare as declare_wire

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Case:
    id: str
    api_id: str
    method: str
    path: str
    expected: tuple = (200,)
    dimensions: tuple = ("response.success",)
    purpose: str = "api-contract"
    intentional_unsupported_params: tuple = ()
    dependency_plan: tuple = ()


def cases_for(version):
    legacy = version.startswith("6.")
    legacy_cancel = version in CANCEL_WITHOUT_WAIT_RELEASES
    legacy_snapshot = legacy or version in EARLY_SEVEN_PILOTS
    cases = []

    def add(
        identifier,
        api,
        method,
        path,
        expected=(200,),
        dimensions=("response.success",),
        purpose="api-contract",
        unsupported=(),
    ):
        if dimensions == ("response.success",) and all(code >= 400 for code in expected):
            dimensions = ("response.expected-error",)
        cases.append(
            Case(
                identifier,
                api,
                method,
                path,
                tuple(expected),
                tuple(dimensions),
                purpose,
                tuple(unsupported),
            )
        )

    add("fixture.create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    for method in ["POST", "PUT"]:
        for variant, path in [("global", "/_bulk"), ("index", "/{index}/_bulk")]:
            stem = "bulk." + method.lower() + "." + variant
            add(
                stem,
                "bulk",
                method,
                path + "?refresh=true",
                dimensions=("request.ndjson.final-newline", "query.refresh", "outcome.success"),
            )
            add(
                stem + ".readback",
                "get",
                "GET",
                "/{index}/{doc_type}/{id}",
                dimensions=("effect.bulk-persists-source",),
                purpose="effect-check",
            )
            add(
                stem + ".search-visible",
                "search",
                "GET",
                "/{index}/_search",
                dimensions=("effect.refresh-search-visible", "request.get-json-body"),
                purpose="effect-check",
            )
    add("bulk.partial", "bulk", "POST", "/_bulk", dimensions=("outcome.partial",))
    for suffix, expected in [("valid", (200,)), ("invalid", (404,))]:
        add(
            "bulk.partial." + suffix,
            "get",
            "GET",
            "/{index}/{doc_type}/{id}",
            expected=expected,
            dimensions=("effect.bulk-partial-independent-readback",),
            purpose="effect-check",
        )
    add(
        "bulk.missing-newline",
        "bulk",
        "POST",
        "/_bulk",
        expected=(400,),
        dimensions=("request.ndjson.missing-final-newline", "response.expected-error"),
    )
    add(
        "bulk.cleanup",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    for operation, api, endpoint in [
        ("reindex", "reindex", "_reindex"),
        ("update", "update_by_query", "_update_by_query"),
        ("delete", "delete_by_query", "_delete_by_query"),
    ]:
        prefix = "task." + operation
        if legacy_cancel and operation == "reindex":
            add(
                prefix + ".cancel-parameter-probe",
                "tasks.cancel",
                "POST",
                "/_tasks/_cancel?actions=es-cli-research-no-such-action&wait_for_completion=true",
                expected=(400,),
                unsupported=("wait_for_completion",),
            )
            add(
                prefix + ".list-group-probe",
                "tasks.list",
                "GET",
                "/_tasks?group_by=none",
                expected=(200,) if version in FLAT_TASK_LIST_RELEASES else (400,),
            )
        add(prefix + ".create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
        add(
            prefix + ".seed", "bulk", "POST", "/{index}/_bulk?refresh=true", purpose="fixture-setup"
        )
        add(prefix + ".count", "count", "GET", "/{index}/_count", purpose="fixture-precondition")
        submit_path = "/_reindex" if operation == "reindex" else "/{index}/" + endpoint
        add(
            prefix + ".submit",
            api,
            "POST",
            submit_path
            + "?wait_for_completion=false&requests_per_second=0.2"
            + ("&scroll_size=1" if operation != "reindex" else ""),
            dimensions=("outcome.async", "query.wait_for_completion", "query.requests_per_second"),
        )
        add(
            prefix + ".get-running",
            "tasks.get",
            "GET",
            "/_tasks/{task_id}?wait_for_completion=false",
            dimensions=("outcome.running", "query.wait_for_completion"),
        )
        add(
            prefix + ".list",
            "tasks.list",
            "GET",
            "/_tasks?group_by="
            + ("nodes" if legacy else "none")
            + "&detailed=true"
            + ("&timeout=10s" if legacy else ""),
            dimensions=("query.group_by", "query.detailed", "effect.task-visible"),
        )
        rethrottle = (
            "reindex_rethrottle"
            if legacy and version not in {"6.5.4", "6.6.2", "6.7.2", "6.8.23"}
            else {
                "reindex": "reindex_rethrottle",
                "update": "update_by_query_rethrottle",
                "delete": "delete_by_query_rethrottle",
            }[operation]
        )
        add(
            prefix + ".rethrottle",
            rethrottle,
            "POST",
            "/" + endpoint + "/{task_id}/_rethrottle?requests_per_second=1",
            dimensions=("query.requests_per_second", "outcome.rethrottle"),
        )
        if version in RETHROTTLE_NEGATIVE_RELEASES:
            for name, query in [
                ("missing", ""),
                ("garbage", "?requests_per_second=garbage"),
                ("zero", "?requests_per_second=0"),
                ("negative", "?requests_per_second=-2"),
            ]:
                add(
                    prefix + ".rate-" + name,
                    rethrottle,
                    "POST",
                    "/" + endpoint + "/{task_id}/_rethrottle" + query,
                    expected=(400,),
                    dimensions=("query.requests_per_second.invalid",),
                )
            add(
                prefix + ".rate-unchanged",
                "tasks.get",
                "GET",
                "/_tasks/{task_id}",
                dimensions=("effect.invalid-rethrottle-no-rate-change",),
                purpose="effect-check",
            )
        add(
            prefix + ".rate-readback",
            "tasks.get",
            "GET",
            "/_tasks/{task_id}",
            dimensions=("effect.rethrottle-rate",),
            purpose="effect-check",
        )
        add(
            prefix + ".cancel",
            "tasks.cancel",
            "POST",
            "/_tasks/{task_id}/_cancel"
            + ("?group_by=nodes" if legacy_cancel else "?wait_for_completion=true"),
            dimensions=("effect.task-cancelled",)
            if legacy_cancel
            else ("query.wait_for_completion", "effect.task-cancelled"),
        )
        add(
            prefix + ".completed",
            "tasks.get",
            "GET",
            "/_tasks/{task_id}?wait_for_completion=true&timeout=10s",
            dimensions=("effect.task-finished", "query.timeout"),
            purpose="effect-check",
        )
        if legacy_cancel:
            add(
                prefix + ".refresh-remaining",
                "indices.refresh",
                "POST",
                ("/{target}" if operation == "reindex" else "/{index}") + "/_refresh",
                expected=(200, 404) if operation == "reindex" else (200,),
                purpose="fixture-precondition",
            )
        remaining_path = "/{target}/_count" if operation == "reindex" else "/{index}/_count"
        add(
            prefix + ".remaining",
            "count",
            "GET",
            remaining_path,
            expected=(200, 404) if operation == "reindex" else (200,),
            dimensions=("effect.cancel-prevents-full-operation",),
            purpose="effect-check",
        )
        add(
            prefix + ".cleanup-cancel",
            "tasks.cancel",
            "POST",
            "/_tasks/{task_id}/_cancel"
            + ("?group_by=nodes" if legacy_cancel else "?wait_for_completion=true"),
            expected=(200, 404),
            purpose="cleanup",
        )
        add(
            prefix + ".cleanup-wait",
            "tasks.get",
            "GET",
            "/_tasks/{task_id}?wait_for_completion=true&timeout=10s",
            expected=(200, 404),
            purpose="cleanup",
        )
        add(
            prefix + ".cleanup-source",
            "indices.delete",
            "DELETE",
            "/{index}",
            expected=(200, 404),
            purpose="cleanup",
        )
        if operation == "reindex":
            add(
                prefix + ".cleanup-target",
                "indices.delete",
                "DELETE",
                "/{target}",
                expected=(200, 404),
                purpose="cleanup",
            )
    add("snapshot.create-index", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    add(
        "snapshot.seed",
        "index",
        "PUT",
        "/{index}/{doc_type}/one?refresh=true",
        expected=(201,),
        purpose="fixture-setup",
    )
    add(
        "snapshot.repository",
        "snapshot.create_repository",
        "PUT",
        "/_snapshot/{repository}",
        purpose="fixture-setup",
    )
    add(
        "snapshot.create",
        "snapshot.create",
        "PUT",
        "/_snapshot/{repository}/source?wait_for_completion=true",
        dimensions=("outcome.success",),
    )
    if legacy_snapshot:
        for suffix, api, method, path in [
            ("repo-get", "snapshot.get_repository", "GET", "/_snapshot/{repository}"),
            ("repo-get-all", "snapshot.get_repository", "GET", "/_snapshot"),
            (
                "repo-verify",
                "snapshot.verify_repository",
                "POST",
                "/_snapshot/{repository}/_verify",
            ),
            ("source-get", "snapshot.get", "GET", "/_snapshot/{repository}/source"),
            ("source-status", "snapshot.status", "GET", "/_snapshot/{repository}/source/_status"),
            ("repo-status", "snapshot.status", "GET", "/_snapshot/{repository}/_status"),
            ("global-status", "snapshot.status", "GET", "/_snapshot/_status"),
        ]:
            add("snapshot." + suffix, api, method, path)
    add(
        "snapshot.clone",
        "snapshot.clone",
        "PUT",
        "/_snapshot/{repository}/source/_clone/target",
        dimensions=("effect.snapshot-clone",),
    )
    for attempt in range(20):
        add(
            "snapshot.clone-poll." + str(attempt),
            "snapshot.get",
            "GET",
            "/_snapshot/{repository}/target",
            dimensions=("outcome.async-progress",),
            purpose="bounded-poll",
        )
    add(
        "snapshot.clone-metadata",
        "snapshot.get",
        "GET",
        "/_snapshot/{repository}/target",
        dimensions=("effect.clone-metadata",),
        purpose="effect-check",
    )
    add(
        "snapshot.delete-source-index",
        "indices.delete",
        "DELETE",
        "/{index}",
        purpose="fixture-setup",
    )
    add(
        "snapshot.source-absent",
        "indices.exists",
        "HEAD",
        "/{index}",
        expected=(404,),
        purpose="fixture-precondition",
    )
    add(
        "snapshot.restore",
        "snapshot.restore",
        "POST",
        "/_snapshot/{repository}/target/_restore?wait_for_completion=true",
        dimensions=("effect.restore-data",),
    )
    add(
        "snapshot.restored-document",
        "get",
        "GET",
        "/{index}/{doc_type}/one",
        dimensions=("effect.restore-original-document",)
        if legacy
        else ("effect.clone-restores-original-document",),
        purpose="effect-check",
    )
    add(
        "snapshot.cleanup-index",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    add(
        "snapshot.cleanup-snapshots",
        "snapshot.delete",
        "DELETE",
        "/_snapshot/{repository}/source,target",
        expected=(200, 404),
        purpose="cleanup",
    )
    add(
        "snapshot.cleanup-repository",
        "snapshot.delete_repository",
        "DELETE",
        "/_snapshot/{repository}",
        expected=(200, 404),
        purpose="cleanup",
    )
    add("reopen.create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    add(
        "reopen.seed",
        "index",
        "PUT",
        "/{index}/{doc_type}/one?refresh=true",
        expected=(201,),
        purpose="fixture-setup",
    )
    add("reopen.close", "indices.close", "POST", "/{index}/_close")
    unsupported = version.startswith("6.0.")
    add(
        "reopen.parameter-probe",
        "indices.open",
        "POST",
        "/{index}/_open?wait_for_active_shards=1",
        expected=(400,) if unsupported else (200,),
        dimensions=("query.wait_for_active_shards", "response.version-boundary"),
        unsupported=("wait_for_active_shards",) if unsupported else (),
    )
    add(
        "reopen.open-without-parameter",
        "indices.open",
        "POST",
        "/{index}/_open",
        dimensions=("effect.index-open",),
    )
    add(
        "reopen.readback",
        "get",
        "GET",
        "/{index}/{doc_type}/one",
        dimensions=("effect.reopen-preserves-document",),
        purpose="effect-check",
    )
    add(
        "reopen.analyze",
        "indices.analyze",
        "POST",
        "/{index}/_analyze",
        dimensions=("effect.analyzer-usable-after-reopen",),
    )
    add("reopen.refresh", "indices.refresh", "POST", "/{index}/_refresh")
    add(
        "reopen.reindex",
        "reindex",
        "POST",
        "/_reindex?refresh=true",
        dimensions=("effect.reindex-after-reopen",),
    )
    add(
        "reopen.reindex-count",
        "count",
        "GET",
        "/{target}/_count",
        dimensions=("effect.reindex-target-count",),
        purpose="effect-check",
    )
    add("reopen.update-query", "update_by_query", "POST", "/{index}/_update_by_query?refresh=true")
    add(
        "reopen.updated-document",
        "get",
        "GET",
        "/{index}/{doc_type}/one",
        dimensions=("effect.update-by-query-after-reopen",),
        purpose="effect-check",
    )
    add("reopen.delete-query", "delete_by_query", "POST", "/{index}/_delete_by_query?refresh=true")
    add(
        "reopen.empty-count",
        "count",
        "GET",
        "/{index}/_count",
        dimensions=("effect.delete-by-query-after-reopen",),
        purpose="effect-check",
    )
    add(
        "reopen.cleanup-source",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    add(
        "reopen.cleanup-target",
        "indices.delete",
        "DELETE",
        "/{target}",
        expected=(200, 404),
        purpose="cleanup",
    )

    add("maintenance.create", "indices.create", "PUT", "/{index}", purpose="fixture-setup")
    for batch in range(3):
        add(
            "maintenance.seed." + str(batch),
            "bulk",
            "POST",
            "/{index}/_bulk?refresh=true",
            purpose="fixture-setup",
        )
        add(
            "maintenance.flush." + str(batch),
            "indices.flush",
            "POST",
            "/{index}/_flush",
            purpose="fixture-setup",
        )
    for name in ["warm1", "warm2", "rewarm"]:
        add(
            "maintenance." + name,
            "search",
            "POST",
            "/{index}/_search?request_cache=true",
            dimensions=("query.request_cache",),
            purpose="fixture-setup",
        )
    for name in ["cache-before", "cache-after", "global-cache-before", "global-cache-after"]:
        add(
            "maintenance." + name,
            "indices.stats",
            "GET",
            "/{index}/_stats/request_cache",
            dimensions=("effect.request-cache-state",),
            purpose="fixture-precondition" if name == "cache-before" else "effect-check",
        )
    add(
        "maintenance.clear-cache",
        "indices.clear_cache",
        "POST",
        "/{index}/_cache/clear?request=true",
        dimensions=("query.request", "effect.clear-request-cache"),
    )
    add(
        "maintenance.clear-cache-global",
        "indices.clear_cache",
        "POST",
        "/_cache/clear?request=true",
        dimensions=("query.request", "effect.global-clear-request-cache"),
    )
    for name in ["segments-before", "segments-after"]:
        add(
            "maintenance." + name,
            "indices.segments",
            "GET",
            "/{index}/_segments",
            dimensions=("effect.segment-count",),
            purpose="fixture-precondition" if name.endswith("before") else "effect-check",
        )
    add(
        "maintenance.block-writes",
        "indices.put_settings",
        "PUT",
        "/{index}/_settings",
        purpose="fixture-setup",
    )
    add(
        "maintenance.block-readback",
        "indices.get_settings",
        "GET",
        "/{index}/_settings",
        purpose="fixture-precondition",
    )
    if version == "7.17.29" or version in EARLY_SEVEN_PILOTS:
        add(
            "maintenance.merge-parameter-probe",
            "indices.forcemerge",
            "POST",
            "/{index}/_forcemerge?max_num_segments=1&wait_for_completion=true",
            expected=(400,),
            unsupported=("wait_for_completion",),
            dimensions=("query.wait_for_completion", "response.version-boundary"),
        )
    add(
        "maintenance.forcemerge",
        "indices.forcemerge",
        "POST",
        "/{index}/_forcemerge?max_num_segments=1&flush=true"
        + (
            ""
            if legacy or version == "7.17.29" or version in EARLY_SEVEN_PILOTS
            else "&wait_for_completion=true"
        ),
        dimensions=("query.max_num_segments", "query.flush")
        if legacy or version == "7.17.29" or version in EARLY_SEVEN_PILOTS
        else ("query.max_num_segments", "query.flush", "query.wait_for_completion"),
    )
    add(
        "maintenance.refresh",
        "indices.refresh",
        "POST",
        "/{index}/_refresh",
        purpose="fixture-setup",
    )
    add(
        "maintenance.preserved-count",
        "count",
        "GET",
        "/{index}/_count",
        dimensions=("effect.forcemerge-preserves-documents",),
        purpose="effect-check",
    )
    add(
        "maintenance.recovery",
        "indices.recovery",
        "GET",
        "/{index}/_recovery?detailed=true&active_only=false",
        dimensions=("query.detailed", "query.active_only"),
    )
    add(
        "maintenance.active-recovery",
        "indices.recovery",
        "GET",
        "/{index}/_recovery?active_only=true",
        dimensions=("effect.no-active-recovery",),
        purpose="effect-check",
    )
    add(
        "maintenance.shard-stores",
        "indices.shard_stores",
        "GET",
        "/{index}/_shard_stores?status=all",
        dimensions=("query.status", "effect.primary-store-present"),
    )
    add(
        "maintenance.disk-usage",
        "indices.disk_usage",
        "POST",
        "/{index}/_disk_usage?run_expensive_tasks=true",
        dimensions=("query.run_expensive_tasks", "effect.field-disk-measurement"),
    )
    add(
        "maintenance.cleanup",
        "indices.delete",
        "DELETE",
        "/{index}",
        expected=(200, 404),
        purpose="cleanup",
    )
    add("maintenance.seed-count", "count", "GET", "/{index}/_count", purpose="fixture-precondition")
    maintenance_graph = {}
    for batch in range(3):
        maintenance_graph["seed." + str(batch)] = ("create",)
        maintenance_graph["flush." + str(batch)] = ("seed." + str(batch),)
    maintenance_graph.update(
        {
            "seed-count": ("seed.0", "seed.1", "seed.2", "flush.0", "flush.1", "flush.2"),
            "warm1": ("seed-count",),
            "warm2": ("warm1",),
            "cache-before": ("warm2",),
            "clear-cache": ("cache-before",),
            "cache-after": ("clear-cache",),
            "rewarm": ("cache-after",),
            "global-cache-before": ("rewarm",),
            "clear-cache-global": ("global-cache-before",),
            "global-cache-after": ("clear-cache-global",),
            "segments-before": ("seed-count",),
            "block-writes": ("seed-count",),
            "block-readback": ("block-writes",),
            "forcemerge": ("segments-before", "block-readback"),
            "refresh": ("forcemerge",),
            "segments-after": ("refresh",),
            "preserved-count": ("forcemerge",),
            "recovery": ("create",),
            "active-recovery": ("recovery",),
            "shard-stores": ("create",),
            "disk-usage": ("forcemerge",),
        }
    )

    graph = {}
    for case in cases:
        name = case.id
        if name.startswith("bulk.") and name != "bulk.cleanup":
            graph[name] = (
                (name.rsplit(".", 1)[0],)
                if name.endswith((".readback", ".search-visible"))
                else ("fixture.create",)
            )
    for operation in ["reindex", "update", "delete"]:
        prefix = "task." + operation
        links = {
            "seed": ("create",),
            "count": ("seed",),
            "submit": ("count",),
            "get-running": ("submit",),
            "list": ("get-running",),
            "rethrottle": ("get-running",),
            "rate-readback": ("rethrottle",),
            "cancel": ("submit",),
            "completed": ("cancel",),
            "refresh-remaining": ("completed",),
            "remaining": ("refresh-remaining",) if legacy_cancel else ("completed",),
            "cleanup-cancel": ("submit",),
            "cleanup-wait": ("submit",),
            "cleanup-source": ("cleanup-wait",),
            "cleanup-target": ("cleanup-wait",),
        }
        if version in RETHROTTLE_NEGATIVE_RELEASES:
            for suffix in ["missing", "garbage", "zero", "negative"]:
                links["rate-" + suffix] = ("get-running",)
            links["rate-unchanged"] = tuple(
                "rate-" + suffix for suffix in ["missing", "garbage", "zero", "negative"]
            )
        graph.update(
            {
                prefix + "." + name: tuple(prefix + "." + dependency for dependency in deps)
                for name, deps in links.items()
            }
        )
    if legacy_cancel:
        graph["task.reindex.cancel-parameter-probe"] = ("task.reindex.create",)
        graph["task.reindex.list-group-probe"] = ("task.reindex.get-running",)
    graph.update(
        {
            "snapshot.seed": ("snapshot.create-index",),
            "snapshot.create": ("snapshot.seed", "snapshot.repository"),
            "snapshot.clone": ("snapshot.create",),
            "snapshot.clone-metadata": ("snapshot.clone-poll.*",),
            "snapshot.delete-source-index": ("snapshot.clone-metadata",),
            "snapshot.source-absent": ("snapshot.delete-source-index",),
            "snapshot.restore": ("snapshot.source-absent",),
            "snapshot.restored-document": ("snapshot.restore",),
        }
    )
    for attempt in range(20):
        graph["snapshot.clone-poll." + str(attempt)] = ("snapshot.clone",)
    links = {
        "seed": ("create",),
        "close": ("seed",),
        "parameter-probe": ("close",),
        "open-without-parameter": ("close",),
        "readback": ("open-without-parameter",),
        "analyze": ("open-without-parameter",),
        "refresh": ("open-without-parameter",),
        "reindex": ("open-without-parameter",),
        "reindex-count": ("reindex",),
        "update-query": ("open-without-parameter",),
        "updated-document": ("update-query",),
        "delete-query": ("updated-document",),
        "empty-count": ("delete-query",),
    }
    graph.update(
        {
            "reopen." + name: tuple("reopen." + dependency for dependency in deps)
            for name, deps in links.items()
        }
    )
    graph.update(
        {
            "maintenance." + name: tuple("maintenance." + dependency for dependency in deps)
            for name, deps in maintenance_graph.items()
        }
    )
    if version == "7.17.29" or version in EARLY_SEVEN_PILOTS:
        graph["maintenance.merge-parameter-probe"] = (
            "maintenance.segments-before",
            "maintenance.block-readback",
        )
    graph["bulk.partial.valid"] = ("bulk.partial",)
    graph["bulk.partial.invalid"] = ("bulk.partial",)
    if version == "8.19.24":
        graph.update(declare_compat8(add))
    graph.update(declare_metadata(add, version))
    graph.update(declare_query(add, version))
    graph.update(declare_template(add, version))
    graph.update(declare_transform(add, version))
    graph.update(declare_document(add, version))
    graph.update(declare_cluster(add, version))
    graph.update(declare_synonym(add, version))
    graph.update(declare_resize(add, version))
    graph.update(declare_cat(add, version))
    graph.update(declare_stream(add, version))
    graph.update(declare_module(add, version))
    graph.update(declare_repository(add))
    graph.update(declare_feature(add, version))
    graph.update(declare_type_transition(add, version))
    graph.update(declare_secure_reload(add, version))
    graph.update(declare_painless_execute(add, version))
    graph.update(declare_painless_context(add, version))
    graph.update(declare_task_limit(add, version))
    graph.update(declare_rank_eval(add, version))
    graph.update(declare_legacy_parameter(add, version))
    graph.update(declare_legacy_route(add, version))
    graph.update(declare_parameter_state(add, version))
    graph.update(declare_legacy_type(add, version))
    graph.update(declare_route_variants(add, version))
    graph.update(declare_system_wire(add, version))
    graph.update(declare_migration_state(add, version))
    graph.update(declare_managed_reindex(add))
    graph.update(declare_topology(add, version))
    graph.update(declare_wire(add))
    if version == "7.17.29" or version in EARLY_SEVEN_PILOTS:
        graph.update(declare_legacy_index(add, version))
    if legacy:
        graph.update(declare_legacy_index(add, version))
        graph.update(declare_legacy_document(add))
        graph.update(declare_legacy_metadata(add))
        graph.update(declare_legacy_query(add, version))
    if legacy_snapshot:
        graph["snapshot.delete-source-index"] = ("snapshot.create",)
        for suffix in ["repo-get", "repo-get-all", "repo-verify"]:
            graph["snapshot." + suffix] = ("snapshot.repository",)
        for suffix in ["source-get", "source-status", "repo-status", "global-status"]:
            graph["snapshot." + suffix] = ("snapshot.create",)
    cases = [replace(case, dependency_plan=graph.get(case.id, ())) for case in cases]
    if legacy:
        # This prepared legacy pilot restores the original snapshot; clone applicability remains open.
        cases = [
            replace(
                case,
                path=case.path.replace("/target/_restore", "/source/_restore").replace(
                    "/source,target", "/source"
                ),
            )
            for case in cases
            if case.id.startswith(
                (
                    "reopen.",
                    "bulk.",
                    "fixture.",
                    "task.",
                    "snapshot.",
                    "maintenance.",
                    "legacy-index.",
                    "migration-state.",
                    "route-variant.",
                    "type-transition.",
                    "secure-reload.",
                    "painless-execute.",
                    "painless-context.",
                    "task-limit.",
                    "rank-eval.",
                    "legacy-parameter.",
                    "legacy-route.",
                    "legacy-type.",
                    "parameter-state.",
                    "system-wire.",
                    "legacy-doc.",
                    "legacy-meta.",
                    "legacy-query.",
                    "cluster.",
                    "template.",
                    "transform.",
                    "resize.",
                    "cat.",
                )
            )
            and not case.id.startswith("snapshot.clone")
            and case.id != "maintenance.disk-usage"
        ]
    if prepared_pilot_families(version):
        # Unprepared families stay explicit backlog, never inferred unsupported.
        cases = [
            case
            for case in cases
            if case.id.startswith(
                (
                    "bulk.",
                    "fixture.",
                    "task.",
                    "snapshot.",
                    "reopen.",
                    "maintenance.",
                    "metadata.",
                    "query.",
                    "template.",
                    "transform.",
                    "document.",
                    "resize.",
                    "repository.",
                    "wire.",
                    "cluster.",
                    "cat.",
                    "module.",
                    "stream.",
                    "legacy-index.",
                    "migration-state.",
                    "route-variant.",
                    "type-transition.",
                    "secure-reload.",
                    "painless-execute.",
                    "painless-context.",
                    "task-limit.",
                    "rank-eval.",
                    "legacy-parameter.",
                    "legacy-route.",
                    "legacy-type.",
                    "parameter-state.",
                    "system-wire.",
                    "topology.",
                    "synonym.",
                    "feature.",
                    "compat8.",
                )
            )
            and not (version == "7.17.29" and case.id.startswith("synonym."))
        ]
    if version == "7.17.29":
        # Pinned handler classification places data-stream operations under X-Pack.
        # Historical research observations are preserved, not product support.
        cases = [case for case in cases if not case.id.startswith("stream.")]
    if version in EARLY_SEVEN_PILOTS:
        prefixes = ("fixture.",) + tuple(
            {"tasks": "task.", "route-variants": "route-variant."}.get(family, family + ".")
            for family in EARLY_SEVEN_PILOTS[version]
        )
        cases = [
            replace(
                case,
                path=case.path.replace("/target/_restore", "/source/_restore").replace(
                    "/source,target", "/source"
                ),
                dimensions=tuple(d.replace("clone-restores", "restores") for d in case.dimensions),
            )
            for case in cases
            if case.id.startswith(prefixes)
            and not case.id.startswith("snapshot.clone")
            and case.id != "maintenance.disk-usage"
        ]
    return cases


def prepared_pilot_families(version):
    """Only these exact cross-major anchors have prepared pilot recipes."""
    if version in EARLY_SEVEN_PILOTS:
        return EARLY_SEVEN_PILOTS[version]
    if version in {"7.17.29", "8.19.24"}:
        return (
            "bulk",
            "tasks",
            "snapshot",
            "reopen",
            "maintenance",
            "metadata",
            "query",
            "template",
            "transform",
            "document",
            "resize",
            "repository",
            "wire",
            "cluster",
            "cat",
            "module",
            "topology",
            "topology-dangling",
        ) + (
            ("legacy-index", "feature")
            if version == "7.17.29"
            else ("stream", "synonym", "feature", "compat8")
        )
    return None


def validate_family_selection(version, families):
    """Reject unprepared exact-release fixture families before any HTTP."""
    selected = set(families or ())
    special = {
        "migration-state": {"6.0.1", "7.17.29"},
        "system-wire": {"7.17.29"},
        "rank-eval": RANK_EVAL_RELEASES,
        "painless-execute": PAINLESS_RELEASES,
        "painless-context": {"7.2.1", "7.3.2", "7.4.2"},
        "task-limit": {"7.3.2", "7.4.2"},
        "secure-reload": SECURE_RELOAD_RELEASES,
        "type-transition": TYPE_TRANSITION_RELEASES,
        "resize-split": LEGACY_SPLIT_RELEASES | {"7.17.29", "8.19.24", "9.5.6"},
        "route-variants": ROUTE_VARIANT_RELEASES,
        "legacy-parameter": PREPARED_LEGACY_RELEASES,
        "legacy-route": LEGACY_ROUTE_RELEASES,
        "legacy-type": {"7.0.1", "7.1.1", "7.2.1", "7.3.2", "7.4.2", "7.17.29"},
        "parameter-state": {
            "7.0.1",
            "7.1.1",
            "7.2.1",
            "7.3.2",
            "7.4.2",
            "7.17.29",
            "8.19.24",
            "9.5.6",
        },
    }
    for name in selected & special.keys():
        if version not in special[name]:
            raise ValueError(name + " fixture is not prepared for exact " + version)
    if "migration-state" in selected and selected != {"migration-state"}:
        raise ValueError("Sequential migration fixture must run alone")
    pilot = prepared_pilot_families(version)
    standalone = {name for name, versions in special.items() if version in versions}
    if pilot and selected - set(pilot) - standalone:
        raise ValueError("Unprepared cross-major pilot families; no HTTP executed")


def route_matches(template, path):
    template = "/" + template.lstrip("/")
    pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(template.rstrip("/") or "/"))
    return re.fullmatch(pattern, path.rstrip("/") or "/") is not None


class Catalog:
    def __init__(self, version, inventory):
        self.version = version
        self.cases = {case.id: case for case in cases_for(version)}
        if len(self.cases) != len(cases_for(version)):
            raise ValueError("Duplicate scenario ID")
        self.inventory = inventory
        facts_path = Path(__file__).with_name("query_parameter_facts.json")
        facts = (
            json.loads(facts_path.read_text())["releases"].get(version, {})
            if facts_path.exists()
            else {}
        )
        if facts and facts["source_commit"] != inventory["source_commit"]:
            raise ValueError("Query parameter source facts differ from pinned release")
        self.query_parameter_facts = facts.get("query_params", {})
        self.handler_route_extensions = load_route_extensions(version, inventory["source_commit"])

    def validate(self):
        definitions = {
            row["api"]: row
            for row in self.inventory["records"]
            if isinstance(row["definition"], dict)
            and isinstance(row["definition"].get("url"), dict)
        }
        common = {}
        for row in self.inventory["records"]:
            if row["source_path"].endswith("/_common.json") and isinstance(row["definition"], dict):
                if row["api"] == "params":
                    common.update(row["definition"])
                elif row["api"] == "url":
                    common.update(row["definition"].get("params", {}))
        errors = []
        for case in self.cases.values():
            for prerequisite in case.dependency_plan:
                present = (
                    any(name.startswith(prerequisite[:-1]) for name in self.cases)
                    if prerequisite.endswith(".*")
                    else prerequisite in self.cases
                )
                if not present:
                    errors.append(case.id + ": declared prerequisite absent: " + prerequisite)
            definition = definitions.get(case.api_id)
            if not definition:
                errors.append(
                    case.id + ": API absent from pinned catalogue; applicability unresolved"
                )
                continue
            body = definition["definition"]
            params = body.get("params", body["url"].get("params", {}))
            unknown = (
                {name for name, _ in parse_qsl(case.path.partition("?")[2], keep_blank_values=True)}
                - set(params)
                - set(common)
                - set(self.query_parameter_facts.get(case.api_id, {}))
            )
            if unknown - set(case.intentional_unsupported_params):
                errors.append(case.id + ": undeclared query params " + str(sorted(unknown)))
            if case.intentional_unsupported_params and any(code < 400 for code in case.expected):
                errors.append(case.id + ": unsupported-param case must expect a negative status")
            if case.purpose == "unsupported-method-probe" and case.expected != (405,):
                errors.append(case.id + ": unsupported-method probe must expect only405")
                continue
            logical = case.path.split("?", 1)[0]
            # Compare route shapes, preserving actual wire values for runtime recording.
            rendered = logical.replace(
                "{doc_type}", "fixture" if self.version.startswith("6.") else "_doc"
            )
            rendered = re.sub(r"\{[^}]+\}", "fixture", rendered)
            routes = definition_routes(body)
            matched = False
            for route in routes:
                path = route["path"]
                methods = route["methods"]
                if case.method in methods and route_matches(path, rendered):
                    matched = True
            if matched and case.purpose == "unsupported-method-probe":
                errors.append(
                    case.id + ": method is source-declared; not an unsupported-method probe"
                )
                continue
            if not matched and case.purpose == "unsupported-method-probe":
                matched = case.expected == (405,) and any(
                    route["methods"] and route_matches(route["path"], rendered) for route in routes
                )
            if not matched:
                matched = any(
                    route["method"] == case.method and route_matches(route["path"], rendered)
                    for route in self.handler_route_extensions.get(case.api_id, [])
                )
            if not matched:
                errors.append(case.id + ": method/path not declared by pinned source")
        return errors

    def execute(
        self,
        session,
        identifier,
        *,
        values,
        body=OMITTED,
        assertions=(),
        depends_on=(),
        semantic=False,
        verifies=(),
        content_type="application/json",
        headers=None,
        deadline=20,
        socket_timeout=None,
    ):
        case = self.cases[identifier]
        declared = case.dependency_plan
        actual = tuple(depends_on)
        if len(actual) != len(declared) or not all(
            any(
                re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), dependency)
                for pattern in declared
            )
            for dependency in actual
        ):
            raise ValueError("Runtime dependencies differ from frozen scenario plan: " + identifier)
        encoded = {key: quote(str(value), safe=",:*") for key, value in values.items()}
        path = case.path.format_map(encoded)
        return session.call(
            case.api_id,
            case.id,
            case.method,
            path,
            case.expected,
            body=body,
            content_type=content_type,
            headers=headers,
            assertions=assertions,
            dimensions=case.dimensions,
            depends_on=depends_on,
            semantic=semantic,
            verifies=verifies,
            purpose=case.purpose,
            deadline=deadline,
            socket_timeout=socket_timeout,
        )

    def manifest(self):
        records = []
        for case in self.cases.values():
            records.append({**asdict(case), "execution_state": "not-run"})
        return {
            "schema_version": 2,
            "release": self.version,
            "kind": "development-anchor-scenario-plan-not-api-evidence",
            "inventory_source_commit": self.inventory["source_commit"],
            "query_parameter_source_facts": self.query_parameter_facts,
            "handler_route_extensions": self.handler_route_extensions,
            "applicability_note": "Legacy pilot prepares typed bulk, reopen, tasks, cache/merge/recovery and original-snapshot restore; other operations and snapshot clone remain gaps, not unsupported claims."
            if self.version.startswith("6.")
            else "Prepared modern anchor recipes; all unplanned dimensions remain gaps.",
            "definition_errors": self.validate(),
            "scenarios": records,
            "ready_for_full_matrix": False,
            "remaining": [
                "all public-core operation recipes",
                "complete parameter/error matrix",
                "native TLS/auth/fault and multi-node fixtures",
                "scope unknowns",
            ],
            "scenario_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }


def main():
    for version in ["9.5.6", "6.0.0"]:
        folder = ROOT / "docs/research/versions" / version
        inventory = json.loads((folder / "inventory.json").read_text())
        catalog = Catalog(version, inventory)
        manifest = catalog.manifest()
        (folder / "deep-scenario-plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(
            version,
            len(catalog.cases),
            "planned cases; source validation errors:",
            manifest["definition_errors"],
        )


if __name__ == "__main__":
    main()
