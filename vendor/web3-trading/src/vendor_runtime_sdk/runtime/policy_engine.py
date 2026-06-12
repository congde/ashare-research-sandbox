# -*- coding: utf-8 -*-
"""
PolicyEngine — Declarative rule engine for workflow governance.

Key design:
- Policy = "when to trigger what action" (workflow rules)
- Orthogonal to Permission = "who can do what" (access control)
- Rules evaluated by priority (higher number = higher priority)
- Deny actions short-circuit evaluation
- Support: deny, ask, alert, retry, degrade actions

Rule evaluation flow:
  Request → Permission System (access control) → ALLOW/DENY/ASK
                    ↓ ALLOWED
           PolicyEngine (workflow rules) → additional actions (alert/degrade)
                    ↓
                Execute tool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import sys
from enum import Enum
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum): pass

from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ActionType(StrEnum):
    """政策动作类型"""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    ALERT = "alert"
    RETRY = "retry"
    DEGRADE = "degrade"  # 降级到备用工具/模型


@dataclass
class PolicyAction:
    """政策动作"""

    type: ActionType
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class PolicyRule:
    """声明式政策规则"""

    rule_id: str
    priority: int  # 数字越大优先级越高
    description: str
    condition: str  # 表达式字符串 (e.g., "tool == 'bash' && args.contains('rm')")
    action_chain: List[PolicyAction] = field(default_factory=list)
    enabled: bool = True


class PolicyEngine:
    """
    政策引擎 — 声明式规则评估.

    Usage:
        engine = PolicyEngine(rules=[...])
        actions = engine.evaluate({"tool": "bash", "args": {"command": "rm -rf /"}})
        for action in actions:
            if action.type == ActionType.DENY:
                ...
    """

    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self._rules: List[PolicyRule] = sorted(
            rules or [], key=lambda r: -r.priority
        )

    def register_rule(self, rule: PolicyRule) -> None:
        """注册新规则并按优先级排序"""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def remove_rule(self, rule_id: str) -> None:
        """移除规则"""
        self._rules = [r for r in self._rules if r.rule_id != rule_id]

    def evaluate(
        self,
        context: Dict[str, Any],
    ) -> List[PolicyAction]:
        """
        按优先级评估所有规则，返回触发的动作链.

        context 常见字段:
          - tool: 工具名
          - args: 工具参数
          - session_id: 会话 ID
          - lane_id: Lane ID
          - error: 异常对象 (错误场景)
          - now: 当前时间
        """
        import time as _time

        # Add convenience fields
        eval_context = dict(context)
        if "now" not in eval_context:
            eval_context["now"] = _time.localtime()

        triggered: List[PolicyAction] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            try:
                if self._eval_condition(rule.condition, eval_context):
                    triggered.extend(rule.action_chain)
                    # Deny 短路
                    if any(a.type == ActionType.DENY for a in rule.action_chain):
                        break
            except Exception as e:
                logger.warning(
                    "Policy rule %s evaluation failed: %s", rule.rule_id, e
                )

        return triggered

    def _eval_condition(self, expression: str, context: Dict) -> bool:
        """
        安全的表达式求值.

        Supported syntax:
          - Simple comparisons: tool == 'bash', priority > 100
          - String methods: args.command.contains('rm')
          - Logical operators: &&, ||
          - Time checks: now.hour > 22
        """
        # Simple expression evaluator — no arbitrary Python execution
        try:
            # Build a safe evaluation namespace
            safe_ns = _SafeNamespace(context)
            return safe_ns.evaluate(expression)
        except Exception:
            return False

    def get_all_rules(self) -> List[PolicyRule]:
        """获取所有已注册规则"""
        return list(self._rules)

    def enable_rule(self, rule_id: str) -> None:
        for r in self._rules:
            if r.rule_id == rule_id:
                r.enabled = True

    def disable_rule(self, rule_id: str) -> None:
        for r in self._rules:
            if r.rule_id == rule_id:
                r.enabled = False


class _SafeNamespace:
    """安全的条件求值命名空间"""

    def __init__(self, context: Dict):
        self._context = context

    def evaluate(self, expression: str) -> bool:
        """简化的条件表达式求值"""
        # Handle && and || with precedence
        if "||" in expression:
            parts = expression.split("||")
            return any(self.evaluate(p.strip()) for p in parts)
        if "&&" in expression:
            parts = expression.split("&&")
            return all(self.evaluate(p.strip()) for p in parts)

        expr = expression.strip()

        # Handle == comparison
        if " == " in expr:
            left, right = expr.split(" == ", 1)
            left_val = self._resolve_value(left.strip())
            right_val = self._resolve_value(right.strip())
            return left_val == right_val

        # Handle != comparison
        if " != " in expr:
            left, right = expr.split(" != ", 1)
            left_val = self._resolve_value(left.strip())
            right_val = self._resolve_value(right.strip())
            return left_val != right_val

        # Handle > comparison
        if " > " in expr:
            left, right = expr.split(" > ", 1)
            left_val = self._resolve_value(left.strip())
            right_val = self._resolve_value(right.strip())
            try:
                return float(left_val) > float(right_val)
            except (TypeError, ValueError):
                return False

        # Handle .contains() method
        if ".contains(" in expr:
            obj_part, rest = expr.split(".contains(", 1)
            arg = rest.rstrip(")").strip().strip("'\"")
            obj_val = str(self._resolve_value(obj_part.strip()))
            return arg in obj_val

        # Boolean literal
        if expr.lower() == "true":
            return True
        if expr.lower() == "false":
            return False

        return bool(self._resolve_value(expr))

    def _resolve_value(self, token: str) -> Any:
        """解析 token 到值"""
        # String literal
        if (token.startswith("'") and token.endswith("'")) or \
           (token.startswith('"') and token.endswith('"')):
            return token[1:-1]

        # Numeric literal
        try:
            if "." in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        # Context variable (dot notation: tool, args.command, now.hour)
        parts = token.split(".")
        value = self._context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
            if value is None:
                return None
        return value


# ──────────────── Default Rules ────────────────

DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule(
        rule_id="risk_destructive_bash",
        priority=1000,
        description="禁止破坏性 bash 命令",
        condition="tool == 'bash' && args.command.contains('rm -rf')",
        action_chain=[
            PolicyAction(type=ActionType.DENY, reason="destructive operation"),
            PolicyAction(
                type=ActionType.ALERT,
                params={"channel": "lark_urgent"},
                reason="destructive bash command attempted",
            ),
        ],
    ),
    PolicyRule(
        rule_id="llm_rate_limit_degrade",
        priority=800,
        description="LLM 限流时降级到备用模型",
        condition="error.type == 'rate_limit' && error.source == 'llm'",
        action_chain=[
            PolicyAction(
                type=ActionType.DEGRADE,
                params={"target": "backup_model"},
                reason="LLM rate limit detected",
            ),
        ],
    ),
    PolicyRule(
        rule_id="off_hours_write_confirm",
        priority=500,
        description="非工作时段写操作需二次确认",
        condition="now.hour > 22 || now.hour < 6",
        action_chain=[
            PolicyAction(type=ActionType.ASK, reason="off-hours operation requires confirmation"),
        ],
    ),
]
