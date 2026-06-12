# -*- coding: utf-8 -*-
"""
PolicyEngine — §6.8

Evaluates ordered PolicyRules using a safe expression sandbox.

Safe-eval constraints (per spec):
  • Allowed operators: ==, !=, <, >, <=, >=, in, not in, and, or, not
  • Allowed builtins: len(), str(), int(), lower(), upper(),
                      startswith(), endswith()
  • Predefined helpers: is_destructive(), is_write_tool(), matches_pattern()
  • No access to __builtins__, os, sys, or any attribute with "__"
  • Max expression length  : 500 chars
  • Max AST nodes          : 50
  • Max nesting depth      : 3
  • Eval timeout           : 10 ms

Three default rules (loaded at construction):
  risk_destructive_bash   priority 1000 — deny+alert on destructive terminal
  off_hours_write_confirm priority  500 — ask on write ops outside 06-22
  llm_rate_limit_degrade  priority  800 — degrade on 429 after 3 retries

Three-stage canary mode:
  monitor        — evaluate rules but only log, never enforce
  enforce_low    — enforce rules whose action_chain contains only low-risk actions
  enforce_all    — fully enforce all rules (default)
"""

from __future__ import annotations

import ast
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ── Canary stages ───────────────────────────────────────────────────────────────

CanaryStage = Literal["monitor", "enforce_low", "enforce_all"]

# ── Data models ─────────────────────────────────────────────────────────────────


@dataclass
class Action:
    """Single action in a rule's action chain."""

    type: Literal["allow", "deny", "ask", "degrade", "alert"]
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyRule:
    """
    A single policy rule.

    condition  — simpleeval-sandbox expression; context vars described in §6.8
    action_chain — ordered actions executed when condition matches
    """

    id: str
    priority: int  # higher value = evaluated first
    condition: str
    action_chain: List[Action]
    enabled: bool = True

    # Auto-disable when false-positive rate exceeds this threshold
    max_false_positive_rate: float = 0.05

    # Internal counters (not persisted)
    _total_fires: int = field(default=0, repr=False, compare=False)
    _false_positives: int = field(default=0, repr=False, compare=False)


@dataclass
class PolicyDecision:
    """Result of PolicyEngine.evaluate()."""

    allowed: bool
    action_type: str = "allow"  # the primary action type that decided this
    reason: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    rule_id: Optional[str] = None  # which rule fired, if any


# ── Validation helpers ──────────────────────────────────────────────────────────

_MAX_EXPR_LEN = 500
_MAX_AST_NODES = 50
_MAX_DEPTH = 5  # measured excluding ctx nodes (Load/Store/Del); covers helper call patterns


def _count_depth(node: ast.AST, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        return depth
    # Skip AST context nodes (Load/Store/Del) — they are implementation details
    # of the AST, not logical nesting levels, so they should not count toward depth.
    children = [
        child
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, (ast.Load, ast.Store, ast.Del))
    ]
    child_depths = [_count_depth(child, depth + 1) for child in children]
    return max(child_depths, default=depth)


def _count_nodes(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


_ALLOWED_OP_TYPES = (
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.And, ast.Or, ast.Not,
    ast.BoolOp, ast.Compare, ast.UnaryOp,
    ast.BinOp,  # needed for string methods chained via attribute
)

_ALLOWED_FUNC_NAMES = frozenset(
    {
        "len", "str", "int", "bool",
        # string/dict methods used in rule expressions
        "lower", "upper", "startswith", "endswith", "get",
        # helper functions
        "is_destructive", "is_destructive_sql", "is_write_tool",
        "is_non_whitelist_git", "matches_pattern", "token_estimate",
    }
)

_FORBIDDEN_ATTR_PREFIXES = ("__",)


def validate_rule(rule: PolicyRule) -> List[str]:
    """
    Validate a PolicyRule before insertion.

    Returns a list of error messages; empty list means valid.
    """
    errors: List[str] = []

    if len(rule.condition) > _MAX_EXPR_LEN:
        errors.append(
            f"condition too long: {len(rule.condition)} chars > {_MAX_EXPR_LEN}"
        )
        return errors  # can't parse an oversized expression

    try:
        tree = ast.parse(rule.condition, mode="eval")
    except SyntaxError as exc:
        errors.append(f"syntax error in condition: {exc}")
        return errors

    node_count = _count_nodes(tree)
    if node_count > _MAX_AST_NODES:
        errors.append(f"too many AST nodes: {node_count} > {_MAX_AST_NODES}")

    depth = _count_depth(tree)
    if depth > _MAX_DEPTH:
        errors.append(f"expression too deeply nested: depth {depth} > {_MAX_DEPTH}")

    # Walk AST for forbidden constructs
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if any(attr.startswith(p) for p in _FORBIDDEN_ATTR_PREFIXES):
                errors.append(f"forbidden attribute access: '{attr}'")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in _ALLOWED_FUNC_NAMES:
                    errors.append(f"function not in whitelist: '{func.id}'")
            elif isinstance(func, ast.Attribute):
                # e.g. args["cmd"].startswith("rm")
                if func.attr not in _ALLOWED_FUNC_NAMES:
                    errors.append(f"method not in whitelist: '{func.attr}'")
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            errors.append("import statements not allowed in policy conditions")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            errors.append("function definitions not allowed in policy conditions")
        elif isinstance(node, ast.Assign):
            errors.append("assignment not allowed in policy conditions")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) > 200:
                errors.append(
                    f"string literal too long: {len(node.value)} chars > 200"
                )

    return errors


# ── Safe evaluator ──────────────────────────────────────────────────────────────

# Helpers injected into the expression context
def _is_destructive(cmd: str) -> bool:
    """True if *cmd* looks like a destructive shell command.

    Matches the command **anywhere** in the string (not just prefix) so that
    pipes / env prefixes (``sudo rm -rf``, ``PGOPTIONS=... psql -c "DROP
    TABLE foo"``) still trip the guard.  Keep the keyword set small; the
    S6 HITL layer additionally handles SQL-embedded destructive statements
    via :func:`_is_destructive_sql`.
    """
    if not isinstance(cmd, str):
        return False
    cl = cmd.strip().lower()
    # Prefix match (legacy behaviour preserved).
    legacy_prefixes = ("rm ", "rm -", "drop ", "truncate ", "delete ", "format ", "mkfs")
    if any(cl.startswith(p) for p in legacy_prefixes):
        return True
    # §S6 HITL — detect sudo/env-prefixed forms and shell pipelines.
    destructive_patterns = (
        r"(^|[\s;&|`])rm\s+(-[rRfFvV]+\s+)*/($|\s)",  # rm -rf /
        r"(^|[\s;&|`])rm\s+-[rRfF]+",                  # sudo rm -rf ...
        r"(^|[\s;&|`])mkfs(\.|\s)",                    # mkfs.ext4 /dev/...
        r"(^|[\s;&|`])dd\s+.*\bof=/dev/",              # dd of=/dev/sda
        r":\(\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:",      # fork bomb :(){:|:&};:
    )
    return any(re.search(p, cl) for p in destructive_patterns)


_SQL_DESTRUCTIVE_RE = re.compile(
    r"(^|[\s;(`\"'])(drop\s+(table|database|schema|index|view)"
    r"|truncate\s+table"
    r"|delete\s+from(?!\s+\S+\s+where)"  # DELETE FROM without WHERE
    r"|update\s+\S+\s+set\b(?!.*\bwhere\b)"  # UPDATE ... SET without WHERE
    r")",
    re.IGNORECASE,
)


def _is_destructive_sql(cmd: str) -> bool:
    """True if *cmd* contains a destructive SQL statement.

    Flags ``DROP TABLE``, ``TRUNCATE``, ``DELETE FROM`` (no WHERE), and
    ``UPDATE ... SET`` (no WHERE).  Case-insensitive.  Matches even when
    the statement is embedded as a ``-c``/``-e`` argument to a CLI
    (``psql -c "DROP TABLE users"``) — we only need a substring match.
    """
    if not isinstance(cmd, str):
        return False
    return bool(_SQL_DESTRUCTIVE_RE.search(cmd))


_WRITE_TOOL_NAMES = frozenset(
    {
        "write_file", "edit_file", "terminal", "bash", "exec",
        "database_write", "insert", "update", "delete",
    }
)


def _is_write_tool(name: str) -> bool:
    if not isinstance(name, str):
        return False
    return name.lower() in _WRITE_TOOL_NAMES


def _matches_pattern(s: str, pattern: str) -> bool:
    try:
        return bool(re.search(pattern, str(s)))
    except Exception:
        return False


# ── §S6 Mid-run HITL helpers ────────────────────────────────────────────

_GIT_WHITELIST_READ = frozenset(
    {"clone", "status", "diff", "log", "fetch", "ls-remote", "show"}
)
_GIT_WHITELIST_WRITE = frozenset(
    {"add", "commit", "push", "checkout", "branch", "pull"}
)
_GIT_WHITELIST = _GIT_WHITELIST_READ | _GIT_WHITELIST_WRITE


def _is_non_whitelist_git(cmd: str) -> bool:
    """True if *cmd* is a git invocation whose subcommand is NOT in the
    §Gap 2 whitelist (read ∪ write).

    Returns ``False`` for non-git commands.  HITL rules can rely on this
    to prompt for approval on ``merge`` / ``cherry-pick`` / ``revert`` /
    ``reset --hard`` / ``rebase`` and any subcommand that slips through
    the static classification (new git features, aliases, etc.).

    Destructive forbidden subcommands (``push --force``, ``tag -f``,
    ``submodule``) are left to :class:`GitRepoAclHook` to deny outright —
    this helper only flags the "ask human" bucket.
    """
    if not isinstance(cmd, str):
        return False
    try:
        parts = cmd.strip().split()
    except Exception:
        return False
    if len(parts) < 2 or parts[0] != "git":
        return False
    sub = parts[1]
    # Force-push variants — leave to Git ACL hook for deny; still non-whitelist.
    if sub == "push" and any(
        flag in parts[2:] for flag in ("--force", "-f", "--force-with-lease", "--delete")
    ):
        return True
    # reset --hard is HITL
    if sub == "reset" and "--hard" in parts[2:]:
        return True
    if sub == "rebase":
        return True
    # merge / cherry-pick / revert / unknown subcommand
    return sub not in _GIT_WHITELIST


def _token_estimate(value: Any) -> int:
    """Best-effort numeric cast for ``token_estimate`` / ``max_tokens`` args.

    Returns ``0`` on any non-numeric input — rules stay false on malformed
    context so the engine never misfires.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


_SAFE_BUILTINS: Dict[str, Any] = {
    "len": len,
    "str": str,
    "int": int,
    "bool": bool,
    "is_destructive": _is_destructive,
    "is_destructive_sql": _is_destructive_sql,
    "is_write_tool": _is_write_tool,
    "is_non_whitelist_git": _is_non_whitelist_git,
    "matches_pattern": _matches_pattern,
    "token_estimate": _token_estimate,
    # Explicitly block dangerous names
    "__builtins__": {},
}

_EVAL_TIMEOUT_S = 0.010  # 10 ms


def _safe_eval(condition: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate *condition* against *context* with the safe-eval sandbox.

    Returns False on any error (timeout, exception, type error).
    """
    eval_ns = dict(_SAFE_BUILTINS)
    eval_ns.update(context)

    result_holder: List[Any] = [False, None]  # [result, exception]

    def _run():
        try:
            result_holder[0] = bool(eval(condition, {"__builtins__": {}}, eval_ns))  # noqa: S307  # nosec B307 — intentional sandboxed eval: __builtins__ empty, AST-validated whitelist, 10ms thread timeout
        except Exception as exc:
            result_holder[1] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=_EVAL_TIMEOUT_S)

    if t.is_alive():
        logger.warning("PolicyEngine: condition timed out (>10ms): %s", condition[:80])
        return False

    if result_holder[1] is not None:
        logger.debug("PolicyEngine: eval error for condition %r: %s", condition[:80], result_holder[1])
        return False

    return bool(result_holder[0])


# ── PolicyEngine ────────────────────────────────────────────────────────────────


class PolicyEngine:
    """
    Evaluates policy rules against a context dict.

    Rules are evaluated in descending priority order.  The first matching
    rule's action_chain is executed.  If no rule matches, returns allow.
    """

    def __init__(
        self,
        rules: Optional[List[PolicyRule]] = None,
        canary_stage: CanaryStage = "enforce_all",
    ) -> None:
        self._rules: List[PolicyRule] = []
        self._canary_stage: CanaryStage = canary_stage

        # PR-Q follow-up: when ``KC_CODER_AUTO_APPROVE_TOOLS`` is set the
        # operator has explicitly opted into unattended ops — skip the
        # built-in ``off_hours_write_confirm`` rule (HITL friction with
        # no upside in that mode). Other defaults (risk_destructive_bash,
        # llm_rate_limit_degrade) stay because they guard against
        # catastrophic / cost-runaway actions, not routine HITL.
        skip_offhours = bool(os.environ.get("KC_CODER_AUTO_APPROVE_TOOLS", "").strip())

        # Load built-in defaults
        for rule in _DEFAULT_RULES:
            if skip_offhours and rule.id == "off_hours_write_confirm":
                continue
            self._rules.append(rule)

        # Then caller-provided rules
        for rule in (rules or []):
            self.add_rule(rule)

    # ── Rule management ────────────────────────────────────────────────────────

    def add_rule(self, rule: PolicyRule) -> None:
        """Add (or replace) a rule.  Raises ValueError if validation fails."""
        errors = validate_rule(rule)
        if errors:
            raise ValueError(f"PolicyRule '{rule.id}' invalid: {errors}")
        # Remove existing rule with same id
        self._rules = [r for r in self._rules if r.id != rule.id]
        self._rules.append(rule)
        logger.info("PolicyEngine: added rule '%s' priority=%d", rule.id, rule.priority)

    def remove_rule(self, rule_id: str) -> None:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        if len(self._rules) < before:
            logger.info("PolicyEngine: removed rule '%s'", rule_id)

    def get_rule(self, rule_id: str) -> Optional[PolicyRule]:
        for r in self._rules:
            if r.id == rule_id:
                return r
        return None

    def list_rules(self) -> List[PolicyRule]:
        return sorted(self._rules, key=lambda r: -r.priority)

    # ── Evaluation ─────────────────────────────────────────────────────────────

    def evaluate(self, context: Dict[str, Any]) -> PolicyDecision:
        """
        Evaluate all rules against *context* and return the first match.

        Returns PolicyDecision(allowed=True) if no rule matches.
        """
        for rule in sorted(self._rules, key=lambda r: -r.priority):
            if not rule.enabled:
                continue
            try:
                matched = _safe_eval(rule.condition, context)
            except Exception as exc:
                logger.warning(
                    "PolicyEngine: rule '%s' eval failed: %s — treated as no-match",
                    rule.id, exc,
                )
                continue

            if not matched:
                continue

            # Rule matched — execute action chain
            decision = self._execute_chain(rule.action_chain, rule.id)

            if self._canary_stage == "monitor":
                logger.info(
                    "PolicyEngine[monitor]: rule '%s' would have fired → %s (not enforced)",
                    rule.id,
                    decision.action_type,
                )
                continue  # don't enforce in monitor mode

            if self._canary_stage == "enforce_low":
                if not self._is_low_risk_chain(rule.action_chain):
                    logger.info(
                        "PolicyEngine[enforce_low]: skipping high-risk rule '%s'",
                        rule.id,
                    )
                    continue

            return decision

        return PolicyDecision(allowed=True, action_type="allow")

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _execute_chain(action_chain: List[Action], rule_id: str) -> PolicyDecision:
        """Return a PolicyDecision from the first decisive action in the chain."""
        for action in action_chain:
            if action.type == "deny":
                return PolicyDecision(
                    allowed=False,
                    action_type="deny",
                    reason=action.params.get("reason", "Policy rule denied the action"),
                    params=action.params,
                    rule_id=rule_id,
                )
            elif action.type == "allow":
                return PolicyDecision(
                    allowed=True,
                    action_type="allow",
                    reason="Policy rule explicitly allowed",
                    params=action.params,
                    rule_id=rule_id,
                )
            elif action.type == "ask":
                return PolicyDecision(
                    allowed=False,  # not allowed until human confirms
                    action_type="ask",
                    reason=action.params.get("message", "Policy rule requires confirmation"),
                    params=action.params,
                    rule_id=rule_id,
                )
            elif action.type == "degrade":
                # Degrade = allowed but with a different model / lower capability
                return PolicyDecision(
                    allowed=True,
                    action_type="degrade",
                    reason="Policy rule degraded the action",
                    params=action.params,
                    rule_id=rule_id,
                )
            elif action.type == "alert":
                # Alert is side-effect only; continue to next action
                channel = action.params.get("channel", "log")
                logger.warning(
                    "PolicyEngine[alert/%s]: rule '%s' fired — %s",
                    channel,
                    rule_id,
                    action.params,
                )
                # Don't return — keep processing the chain
        # Chain exhausted without a decisive action → allow
        return PolicyDecision(allowed=True, action_type="allow", rule_id=rule_id)

    @staticmethod
    def _is_low_risk_chain(chain: List[Action]) -> bool:
        """True if all decisive actions in the chain are low-risk (alert only)."""
        return all(a.type in ("alert", "allow") for a in chain)

    # ── Canary management ──────────────────────────────────────────────────────

    def set_canary_stage(self, stage: CanaryStage) -> None:
        self._canary_stage = stage
        logger.info("PolicyEngine: canary stage → %s", stage)

    @property
    def canary_stage(self) -> CanaryStage:
        return self._canary_stage


# ── 3 default rules (§6.8) ──────────────────────────────────────────────────────

_DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule(
        id="risk_destructive_bash",
        priority=1000,
        condition='tool_name == "terminal" and is_destructive(args.get("command", ""))',
        action_chain=[
            Action(type="deny", params={"reason": "Destructive terminal command blocked"}),
            Action(type="alert", params={"channel": "log"}),
        ],
    ),
    PolicyRule(
        id="llm_rate_limit_degrade",
        priority=800,
        condition="error_code == 429 and retry_count >= 3",
        action_chain=[
            Action(type="degrade", params={"backup_model": True}),
        ],
    ),
    PolicyRule(
        id="off_hours_write_confirm",
        priority=500,
        condition="is_write_tool(tool_name) and (hour >= 23 or hour < 6)",
        action_chain=[
            Action(
                type="ask",
                params={"message": "This write operation is happening outside working hours. Confirm?"},
            ),
        ],
    ),
]
