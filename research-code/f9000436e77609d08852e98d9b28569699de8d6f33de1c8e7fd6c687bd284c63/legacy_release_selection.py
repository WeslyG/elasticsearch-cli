"""Exact releases prepared for bounded recipes; this is not runtime support."""

PREPARED_LEGACY_RELEASES = frozenset(
    {"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
ROUTE_VARIANT_RELEASES = PREPARED_LEGACY_RELEASES | {"7.17.29", "8.19.24", "9.5.6"}

LEGACY_SPLIT_RELEASES = frozenset(
    {"6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
FLAT_TASK_LIST_RELEASES = frozenset(
    {"7.0.1", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)
LEGACY_INVALID_INPUT_500_RELEASES = frozenset(
    {"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"}
)

SCORE_SCRIPT_CONTEXT_RELEASES = frozenset({"6.4.3", "6.5.4", "6.6.2", "6.7.2", "6.8.23"})


# Preparation is explicit; these narrow first-stage recipes imply no API support.
EARLY_SEVEN_PILOTS = {
    "7.0.1": (
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
    )
}
LAB_RELEASES = ROUTE_VARIANT_RELEASES | set(EARLY_SEVEN_PILOTS)

CANCEL_WITHOUT_WAIT_RELEASES = PREPARED_LEGACY_RELEASES | {"7.0.1"}
