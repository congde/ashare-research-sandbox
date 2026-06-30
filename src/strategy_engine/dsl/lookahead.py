"""Lookahead-bias linter for strategy code.

Sprint-S4 scope item: "Lookahead bias 检查". Different concern from the
DSL safelist validator (``dsl/validator.py``):

  * **Safelist validator** asks: "is this code safe to execute?"
    (blocks dangerous imports, dunder access, eval, etc.)
  * **Lookahead linter** asks: "even if this code is safe, does it
    secretly peek at future data?"

LLMs love writing ``ctx.future_close`` or calling ``df.shift(-5)``
when they're being lazy. The engine's runtime can't catch all of
this — by the time a strategy reads from a misleading global the
backtest is already corrupted. Static detection at submit time is
the only honest defence.

The linter is intentionally conservative:

  * False positives are tolerable — a flagged finding is a prompt for
    the author to add a comment explaining why their pattern is safe.
  * False negatives are NOT tolerable — a strategy that quietly cheats
    invalidates the entire backtest pipeline.

What this is NOT:

  * Not a proof of correctness. ``ctx.history`` indexing is checked
    only for obvious-bad patterns; an attacker who wants to peek
    can still embed the bias inside a helper function.
  * Not a replacement for the runtime engine guard. The engine only
    passes the current-and-prior candles; the linter helps catch the
    code-review-able cases earlier.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# ── Findings ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LookaheadFinding:
    """One detected pattern.

    ``severity`` separates "definitely-cheats" (error) from
    "looks suspicious, please justify" (warning). The runtime
    sandbox doesn't enforce on warning-level findings — they're a
    code-review hint, not a hard block.
    """

    line: int
    col: int
    rule: str
    severity: str  # "warning" | "error"
    message: str
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class LookaheadReport:
    """Aggregate over one strategy module's findings."""

    clean: bool  # True iff no error-severity findings
    findings: tuple[LookaheadFinding, ...]

    @property
    def errors(self) -> tuple[LookaheadFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[LookaheadFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")


# ── Rule catalogue ───────────────────────────────────────────────

# L001 — attribute access names that signal future-peeking.
# Treated as ERROR: legitimate strategies never need ``ctx.future_*``
# because the engine's contract is "history ends at current bar".
_BANNED_ATTRIBUTE_PREFIXES: frozenset[str] = frozenset(
    {
        "future_",
        "tomorrow_",
        "next_bar",
        "next_candle",
        "lookahead",
        "peek_",
        # The strategy might legitimately need to KNOW the next
        # candle's *desired* state (e.g. "next entry price") in
        # planning code, but our convention is to name those
        # ``_planned_*`` to avoid collision with the linter rule.
    }
)

# L002 — pandas-style backward-shift idioms. ``df.shift(-N)`` brings
# a future row's value into the current row — a textbook bias.
# Treated as ERROR when N is a literal negative int.
_SHIFT_METHODS: frozenset[str] = frozenset({"shift"})

# L003 — numpy-style backward-roll. ``np.roll(arr, -N)`` does the
# same as ``shift(-N)`` for arrays.
_ROLL_METHODS: frozenset[str] = frozenset({"roll"})

# L004 — slicing history with a positive integer start is suspicious
# because the convention is negative-from-end. A WARNING: there are
# legitimate uses (e.g. truncating an initial warm-up region) so we
# don't outright ban.
_HISTORY_NAMES: frozenset[str] = frozenset({"history"})


# ── Walker ───────────────────────────────────────────────────────


class _LookaheadVisitor(ast.NodeVisitor):
    """AST walker that records findings without raising."""

    def __init__(self) -> None:
        self.findings: list[LookaheadFinding] = []

    # ── L001: banned attribute prefixes ──────────────────────────

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        for prefix in _BANNED_ATTRIBUTE_PREFIXES:
            if attr == prefix.rstrip("_") or attr.startswith(prefix):
                self.findings.append(
                    LookaheadFinding(
                        line=node.lineno,
                        col=node.col_offset,
                        rule="L001",
                        severity="error",
                        message=(
                            f"Attribute '{attr}' suggests reading future "
                            "data. Strategies must only see history up to "
                            "the current candle."
                        ),
                        suggestion=(
                            "If the value is computed from past data, "
                            "rename to a non-future-suggesting identifier "
                            "(e.g. 'planned_entry_price' instead of "
                            "'tomorrow_entry_price')."
                        ),
                    )
                )
                break
        self.generic_visit(node)

    # ── L002 / L003: shift(-N) / roll(-N) ────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        method_name = self._called_method_name(node)
        if method_name in _SHIFT_METHODS or method_name in _ROLL_METHODS:
            # Argument carrying the shift amount lives at different
            # positions: pandas .shift(-N) → args[0]; numpy .roll(arr,
            # -N) → args[1]. Also support the ``periods=`` / ``shift=``
            # kwargs since real strategy code mixes both styles.
            shift_arg = self._extract_shift_amount(node, method_name)
            if shift_arg is not None and _is_negative_int_literal(shift_arg):
                rule = "L002" if method_name in _SHIFT_METHODS else "L003"
                op = "shift" if rule == "L002" else "roll"
                self.findings.append(
                    LookaheadFinding(
                        line=node.lineno,
                        col=node.col_offset,
                        rule=rule,
                        severity="error",
                        message=(
                            f"{op}(<negative>) pulls a future row's value "
                            "into the current row. This is lookahead bias."
                        ),
                        suggestion=(
                            f"Use {op}(positive_N) instead to lag past "
                            "values into the present, OR rebuild your "
                            "feature column from history that ENDS at "
                            "the current bar."
                        ),
                    )
                )
        self.generic_visit(node)

    @staticmethod
    def _extract_shift_amount(node: ast.Call, method_name: str | None) -> ast.AST | None:
        """Locate the shift-amount argument across pandas / numpy
        calling conventions.

        pandas: ``Series.shift(periods=-N)`` / ``Series.shift(-N)``
                → args[0] or kw 'periods'
        numpy:  ``np.roll(arr, -N)`` / ``np.roll(arr, shift=-N)``
                → args[1] or kw 'shift'
        """
        # kwarg path covers both conventions.
        for kw in node.keywords:
            if kw.arg in {"periods", "shift"}:
                return kw.value
        # Positional fallback. shift → arg 0; roll → arg 1.
        if method_name in _SHIFT_METHODS and node.args:
            return node.args[0]
        if method_name in _ROLL_METHODS and len(node.args) >= 2:
            return node.args[1]
        return None

    # ── L004: history[pos_int_literal] ───────────────────────────

    def visit_Subscript(self, node: ast.Subscript) -> None:
        target = self._subscript_target_name(node)
        if target in _HISTORY_NAMES:
            slice_node = node.slice
            if _is_positive_int_literal(slice_node):
                self.findings.append(
                    LookaheadFinding(
                        line=node.lineno,
                        col=node.col_offset,
                        rule="L004",
                        severity="warning",
                        message=(
                            f"Positive integer indexing on '{target}' "
                            "(e.g. history[5]) reads the oldest bars, "
                            "not the most recent. This is usually a bug, "
                            "but can be intentional for warm-up logic."
                        ),
                        suggestion=(
                            "Prefer negative indices (history[-1] is the "
                            "current bar, history[-2] is the prior). "
                            "If you genuinely want bar N from the start, "
                            "add a comment explaining why."
                        ),
                    )
                )
        self.generic_visit(node)

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _called_method_name(node: ast.Call) -> str | None:
        """Return the bare method name for ``obj.method(...)``, else
        None for plain function calls (where the linter doesn't have
        enough context to judge)."""
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @staticmethod
    def _subscript_target_name(node: ast.Subscript) -> str | None:
        """Return the rightmost name being subscripted, so we can match
        both ``history[...]`` and ``ctx.history[...]``."""
        target = node.value
        if isinstance(target, ast.Attribute):
            return target.attr
        if isinstance(target, ast.Name):
            return target.id
        return None


def _is_negative_int_literal(node: ast.AST) -> bool:
    """``-N`` parses as ``UnaryOp(USub, Constant(N))`` where N > 0.

    Astaire-style ``Constant(-N)`` doesn't happen in modern Python
    parsing, but we cover both defensively.
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = node.operand
        return isinstance(operand, ast.Constant) and isinstance(operand.value, int)
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int) and node.value < 0
    return False


def _is_positive_int_literal(node: ast.AST) -> bool:
    """Match ``5`` but not ``-5`` or ``0``. Zero is excluded because
    ``history[0]`` is well-defined as the oldest bar and isn't
    suspicious."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and node.value > 0
    )


# ── Public entry point ───────────────────────────────────────────


def check_lookahead_bias(code: str) -> LookaheadReport:
    """Parse ``code`` and return a :class:`LookaheadReport` listing
    every suspicious pattern.

    Raises ``SyntaxError`` on un-parseable input — the DSL safelist
    validator runs FIRST and catches that, so a downstream caller
    only sees valid Python.
    """
    tree = ast.parse(code)
    visitor = _LookaheadVisitor()
    visitor.visit(tree)
    findings = tuple(visitor.findings)
    clean = not any(f.severity == "error" for f in findings)
    return LookaheadReport(clean=clean, findings=findings)
