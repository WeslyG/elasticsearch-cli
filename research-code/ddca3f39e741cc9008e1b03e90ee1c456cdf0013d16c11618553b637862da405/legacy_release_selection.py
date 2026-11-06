"""Exact source-prepared recipes; membership never implies runtime/API support."""

PREPARED_LEGACY_RELEASES = frozenset(
    {"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
EARLY_SEVEN_FAMILIES = (
    "bulk",
    "tasks",
    "reopen",
    "document",
    "resize",
    "metadata",
    "query",
    "template",
    "secure-reload",
    "painless-execute",
    "rank-eval",
    "cluster",
    "cat",
    "snapshot",
    "maintenance",
    "transform",
    "route-variants",
    "type-transition",
    "legacy-type",
    "legacy-route",
    "legacy-index",
    "parameter-state",
)
EARLY_SEVEN_PILOTS = {
    "7.0.1": EARLY_SEVEN_FAMILIES,
    "7.1.1": EARLY_SEVEN_FAMILIES,
    "7.2.1": (*EARLY_SEVEN_FAMILIES, "painless-context"),
    "7.3.2": (*EARLY_SEVEN_FAMILIES, "painless-context", "task-limit"),
    "7.4.2": (*EARLY_SEVEN_FAMILIES, "painless-context", "task-limit", "repository"),
    "7.5.2": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
    ),
    "7.6.2": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
    ),
    "7.7.1": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
        "feature-gates",
    ),
    "7.8.1": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
        "feature-gates",
        "composable-template",
        "voting-state",
    ),
    "7.9.3": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
        "voting-state",
        "core79",
    ),
    "7.10.2": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
        "voting-state",
        "core79",
        "alias-guard",
    ),
    "7.11.2": (
        *EARLY_SEVEN_FAMILIES,
        "painless-context",
        "task-limit",
        "repository",
        "ingest-state",
        "script-info",
        "voting-state",
        "core79",
        "alias-guard",
    ),
}
EARLY_SEVEN_RELEASES = frozenset(EARLY_SEVEN_PILOTS)
ROUTE_VARIANT_RELEASES = (
    PREPARED_LEGACY_RELEASES | EARLY_SEVEN_RELEASES | {"7.17.29", "8.19.24", "9.5.6"}
)
LAB_RELEASES = ROUTE_VARIANT_RELEASES
LEGACY_SPLIT_RELEASES = frozenset(
    {"6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
FLAT_TASK_LIST_RELEASES = frozenset(
    {
        "6.2.4",
        "6.3.2",
        "6.4.3",
        "6.5.4",
        "6.6.2",
        "6.7.2",
        "6.8.23",
        "7.0.1",
        "7.1.1",
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
    }
)
LEGACY_INVALID_INPUT_500_RELEASES = frozenset(
    {"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
SCORE_SCRIPT_CONTEXT_RELEASES = frozenset(
    {
        "6.4.3",
        "6.5.4",
        "6.6.2",
        "6.7.2",
        "6.8.23",
        "7.0.1",
        "7.1.1",
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
    }
)
CANCEL_WITHOUT_WAIT_RELEASES = PREPARED_LEGACY_RELEASES | {
    "7.0.1",
    "7.1.1",
    "7.2.1",
    "7.3.2",
    "7.4.2",
    "7.5.2",
    "7.6.2",
    "7.7.1",
}
# TaskInfo7.8 still omits cancelled although cancel now accepts wait_for_completion.
CANCEL_RESPONSE_WITHOUT_CANCELLED_RELEASES = CANCEL_WITHOUT_WAIT_RELEASES | {
    "7.8.1",
    "7.9.3",
    "7.10.2",
    "7.11.2",
}
LEGACY_ROUTE_RELEASES = PREPARED_LEGACY_RELEASES | EARLY_SEVEN_RELEASES
RETHROTTLE_NEGATIVE_RELEASES = {
    "6.5.4",
    "6.6.2",
    "6.7.2",
    "6.8.23",
    "7.1.1",
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
}
TASK_RESULT_DOCUMENT_TYPES = {
    **{version: "task" for version in PREPARED_LEGACY_RELEASES | EARLY_SEVEN_RELEASES},
    "7.17.29": "_doc",
    "8.19.24": "_doc",
    "9.5.6": "_doc",
}

# Negative short-key behavior is observed only on these exact releases.
ROLLOVER_SHORT_SETTINGS_REFUSAL_RELEASES = {"7.6.2", "7.7.1"}
ROLLOVER_PREFIXED_RECIPE_RELEASES = {"7.6.2", "7.7.1", "7.8.1", "7.9.3", "7.10.2", "7.11.2"}

SNAPSHOT_CLONE_RELEASES = {"7.10.2", "7.17.29", "8.19.24", "9.5.6", "7.11.2"}

REJECT_UNUSED_METADATA_BODY_RELEASES = {"7.11.2"}

ALIAS_REMOVE_MUST_EXIST_RELEASES = {"7.11.2"}
