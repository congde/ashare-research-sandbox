"""AST validator for user / LLM-generated strategy code.

Per ADR-0007, this is defense layer 2 of 3:
1. Restricted DSL via safelist (safelist.py)
2. AST static validation (this file)
3. Docker sandbox at runtime (sandbox/runner.py)

The validator returns a `ValidationResult` listing every violation
found — not just the first. The LLM Strategy Architect uses this
feedback to self-correct in subsequent turns.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

from strategy_engine.dsl.safelist import (
    ALLOWED_IMPORTS,
    DENIED_ATTRS,
    DENIED_BUILTINS,
    DENIED_IMPORTS,
    MAX_LINES_OF_CODE,
    REQUIRED_FUNCTION_ARGS,
    REQUIRED_FUNCTION_NAME,
)


@dataclass(frozen=True, slots=True)
class ValidationError:
    line: int
    col: int
    rule: str
    message: str
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    errors: tuple[ValidationError, ...]
    ast_hash: str
    line_count: int = 0

    @property
    def first_error(self) -> ValidationError | None:
        return self.errors[0] if self.errors else None

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": [
                {
                    "line": e.line,
                    "col": e.col,
                    "rule": e.rule,
                    "message": e.message,
                    "suggestion": e.suggestion,
                }
                for e in self.errors
            ],
            "ast_hash": self.ast_hash,
            "line_count": self.line_count,
        }


class _StrategyASTValidator(ast.NodeVisitor):
    """Walks the AST and accumulates violations."""

    def __init__(self) -> None:
        self.errors: list[ValidationError] = []
        self.has_on_tick: bool = False
        self.on_tick_signature_ok: bool = False

    # ── Imports ──────────────────────────────────────────────────────────
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self._check_import(module, node)
        self.generic_visit(node)

    def _check_import(self, module: str, node: ast.AST) -> None:
        top = module.split(".")[0]
        if module in DENIED_IMPORTS or top in DENIED_IMPORTS:
            self._err(
                node,
                "denied_import",
                f"禁用 import: {module}",
                "改用 ai_trading.api 暴露的接口",
            )
            return
        if not (module in ALLOWED_IMPORTS or top in ALLOWED_IMPORTS):
            self._err(
                node,
                "unauthorized_import",
                f"未授权 import: {module}",
                f"白名单: {sorted(ALLOWED_IMPORTS)}",
            )

    # ── Names (builtins) ─────────────────────────────────────────────────
    def visit_Name(self, node: ast.Name) -> None:
        if node.id in DENIED_BUILTINS:
            self._err(
                node,
                "denied_builtin",
                f"禁用 builtin: {node.id}",
                None,
            )
        self.generic_visit(node)

    # ── Attribute access ─────────────────────────────────────────────────
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in DENIED_ATTRS:
            self._err(
                node,
                "denied_attribute",
                f"禁用 attribute: {node.attr}（反射逃逸）",
                None,
            )
        self.generic_visit(node)

    # ── Calls (catch eval/exec disguised as Name resolved at call time) ──
    def visit_Call(self, node: ast.Call) -> None:
        # eval / exec / compile / __import__ called via Name
        if isinstance(node.func, ast.Name) and node.func.id in DENIED_BUILTINS:
            self._err(
                node,
                "denied_call",
                f"禁用 call: {node.func.id}()",
                None,
            )
        self.generic_visit(node)

    # ── Function definition: enforce on_tick(ctx, candle) ────────────────
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == REQUIRED_FUNCTION_NAME:
            self.has_on_tick = True
            args = tuple(a.arg for a in node.args.args)
            if args != REQUIRED_FUNCTION_ARGS:
                self._err(
                    node,
                    "wrong_signature",
                    (f"on_tick 签名应为 {REQUIRED_FUNCTION_ARGS}, 实际 {args}"),
                    None,
                )
            else:
                self.on_tick_signature_ok = True
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

    # ── Helpers ──────────────────────────────────────────────────────────
    def _err(
        self,
        node: ast.AST,
        rule: str,
        message: str,
        suggestion: str | None,
    ) -> None:
        self.errors.append(
            ValidationError(
                line=getattr(node, "lineno", 0),
                col=getattr(node, "col_offset", 0),
                rule=rule,
                message=message,
                suggestion=suggestion,
            )
        )


def _normalize_ast_hash(tree: ast.AST) -> str:
    """SHA-256 of the AST dump — stable across whitespace / comments."""
    dumped = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def validate_strategy_code(code: str) -> ValidationResult:
    """Validate a user strategy source string.

    Returns ``ValidationResult`` with ``valid=False`` and a non-empty
    ``errors`` tuple if any rule was violated. ``ast_hash`` is empty
    on syntax error.
    """
    line_count = sum(1 for _ in code.splitlines())
    if line_count > MAX_LINES_OF_CODE:
        return ValidationResult(
            valid=False,
            errors=(
                ValidationError(
                    line=line_count,
                    col=0,
                    rule="too_long",
                    message=f"策略行数 {line_count} 超过 {MAX_LINES_OF_CODE},请拆分",
                ),
            ),
            ast_hash="",
            line_count=line_count,
        )

    try:
        tree = ast.parse(code, mode="exec", type_comments=False)
    except SyntaxError as exc:  # syntax error
        return ValidationResult(
            valid=False,
            errors=(
                ValidationError(
                    line=exc.lineno or 0,
                    col=exc.offset or 0,
                    rule="syntax_error",
                    message=f"SyntaxError: {exc.msg}",
                ),
            ),
            ast_hash="",
            line_count=line_count,
        )

    walker = _StrategyASTValidator()
    walker.visit(tree)

    if not walker.has_on_tick:
        walker.errors.insert(
            0,
            ValidationError(
                line=1,
                col=0,
                rule="missing_on_tick",
                message="必须定义 def on_tick(ctx, candle):",
            ),
        )

    return ValidationResult(
        valid=len(walker.errors) == 0,
        errors=tuple(walker.errors),
        ast_hash=_normalize_ast_hash(tree),
        line_count=line_count,
    )
