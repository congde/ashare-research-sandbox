"""
Tool call reliability — self-repair + deduplication (§5.1)

- Dedup: Removes duplicate tool calls within the same iteration
- Repair: Fuzzy-matches misspelled tool names via difflib
"""

from vendor_runtime_sdk.runtime.tools.dedup import (
    deduplicate_tool_calls,
    has_duplicates,
)
from vendor_runtime_sdk.runtime.tools.repair import (
    DEFAULT_THRESHOLD,
    find_closest,
    repair_tool_calls,
    repair_tool_name,
)

__all__ = [
    # Dedup
    "deduplicate_tool_calls",
    "has_duplicates",
    # Repair
    "repair_tool_name",
    "repair_tool_calls",
    "find_closest",
    "DEFAULT_THRESHOLD",
]
