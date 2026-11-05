"""Exact releases prepared for bounded recipes; this is not runtime support."""

PREPARED_LEGACY_RELEASES = frozenset({"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3"})
ROUTE_VARIANT_RELEASES = PREPARED_LEGACY_RELEASES | {"7.17.29", "8.19.24", "9.5.6"}

LEGACY_SPLIT_RELEASES = frozenset({"6.1.4", "6.2.4", "6.3.2", "6.4.3"})
FLAT_TASK_LIST_RELEASES = frozenset({"6.2.4", "6.3.2", "6.4.3"})
LEGACY_INVALID_INPUT_500_RELEASES = frozenset(
    {"6.0.0", "6.0.1", "6.1.4", "6.2.4", "6.3.2", "6.4.3"}
)
