"""
Budget system — 4-tier pressure injection + warning stripping (§5.8, §5.1)

4-tier pressure levels (fraction of max_iterations consumed):
  low      50% — informational nudge
  medium   70% — suggest converging
  high     90% — urgent, finish soon
  critical 95% — must respond immediately

Token quota (P5) — 3-level quota management:
  User daily/monthly → Workspace daily → Session turn/total
"""

from vendor_runtime_sdk.runtime.budget.pressure import (
    BUDGET_MARKER_KEY,
    BudgetPressure,
    inject_into_last_tool_result,
)
from vendor_runtime_sdk.runtime.budget.warning import (
    has_budget_warning,
    strip_budget_warnings,
)

__all__ = [
    "BudgetPressure",
    "BUDGET_MARKER_KEY",
    "inject_into_last_tool_result",
    "strip_budget_warnings",
    "has_budget_warning",
]
