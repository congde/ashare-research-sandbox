"""JSON serialization for GP expression trees."""

from __future__ import annotations

from typing import Any

from factor_mining.expressions import Expr


def expr_to_dict(expr: Expr) -> dict[str, Any]:
    payload: dict[str, Any] = {"op": expr.op}
    if expr.terminal is not None:
        payload["terminal"] = expr.terminal
    if expr.lag is not None:
        payload["lag"] = expr.lag
    if expr.left is not None:
        payload["left"] = expr_to_dict(expr.left)
    if expr.right is not None:
        payload["right"] = expr_to_dict(expr.right)
    return payload


def expr_from_dict(payload: dict[str, Any]) -> Expr:
    return Expr(
        op=str(payload["op"]),
        terminal=payload.get("terminal"),
        lag=payload.get("lag"),
        left=expr_from_dict(payload["left"]) if payload.get("left") else None,
        right=expr_from_dict(payload["right"]) if payload.get("right") else None,
    )
