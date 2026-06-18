"""Symbolic expression trees for genetic programming factor search."""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from typing import Any


UNARY_OPS = ("neg", "abs", "rank")
BINARY_OPS = ("add", "sub", "mul", "div")
DELAY_LAGS = (1, 3, 5)
RANK_LOOKBACK = 20


@dataclass
class Expr:
    op: str
    terminal: str | None = None
    lag: int | None = None
    left: Expr | None = None
    right: Expr | None = None

    def copy(self) -> Expr:
        return copy.deepcopy(self)

    def node_count(self) -> int:
        if self.op == "terminal":
            return 1
        if self.op == "delay":
            return 1 + (self.left.node_count() if self.left else 0)
        if self.op in UNARY_OPS:
            return 1 + (self.left.node_count() if self.left else 0)
        return 1 + (self.left.node_count() if self.left else 0) + (self.right.node_count() if self.right else 0)


def random_terminal(terminals: list[str], rng: random.Random) -> Expr:
    return Expr(op="terminal", terminal=rng.choice(terminals))


def random_expr(
    terminals: list[str],
    rng: random.Random,
    *,
    max_depth: int = 4,
    depth: int = 0,
) -> Expr:
    if depth >= max_depth or (depth > 0 and rng.random() < 0.25):
        return random_terminal(terminals, rng)

    choice = rng.random()
    if choice < 0.15:
        return Expr(
            op="delay",
            lag=rng.choice(DELAY_LAGS),
            left=random_expr(terminals, rng, max_depth=max_depth, depth=depth + 1),
        )
    if choice < 0.35:
        op = rng.choice(UNARY_OPS)
        return Expr(op=op, left=random_expr(terminals, rng, max_depth=max_depth, depth=depth + 1))
    op = rng.choice(BINARY_OPS)
    return Expr(
        op=op,
        left=random_expr(terminals, rng, max_depth=max_depth, depth=depth + 1),
        right=random_expr(terminals, rng, max_depth=max_depth, depth=depth + 1),
    )


def _safe_div(a: float, b: float) -> float | None:
    if abs(b) < 1e-9 or not math.isfinite(a) or not math.isfinite(b):
        return None
    return a / b


def _rolling_rank(series: list[float | None], idx: int, lookback: int) -> float | None:
    start = max(0, idx - lookback + 1)
    window = [series[i] for i in range(start, idx + 1) if series[i] is not None]
    if len(window) < 3:
        return None
    value = series[idx]
    if value is None:
        return None
    less = sum(1 for v in window if v < value)
    equal = sum(1 for v in window if v == value)
    return (less + (equal - 1) / 2.0) / (len(window) - 1) * 2.0 - 1.0


def eval_at(expr: Expr, features: dict[str, list[float | None]], idx: int) -> float | None:
    if expr.op == "terminal":
        name = expr.terminal
        if not name or name not in features:
            return None
        row = features[name]
        if idx < 0 or idx >= len(row):
            return None
        value = row[idx]
        return None if value is None else float(value)

    if expr.op == "delay":
        lag = expr.lag or 1
        if expr.left is None:
            return None
        return eval_at(expr.left, features, idx - lag)

    if expr.op in UNARY_OPS:
        if expr.left is None:
            return None
        child = eval_at(expr.left, features, idx)
        if child is None:
            return None
        if expr.op == "neg":
            return -child
        if expr.op == "abs":
            return abs(child)
        if expr.op == "rank":
            if expr.left is None:
                return None
            series = eval_series(expr.left, features)
            return _rolling_rank(series, idx, RANK_LOOKBACK)
        return None

    if expr.left is None or expr.right is None:
        return None
    left = eval_at(expr.left, features, idx)
    right = eval_at(expr.right, features, idx)
    if left is None or right is None:
        return None
    if expr.op == "add":
        return left + right
    if expr.op == "sub":
        return left - right
    if expr.op == "mul":
        return left * right
    if expr.op == "div":
        return _safe_div(left, right)
    return None


def eval_series(expr: Expr, features: dict[str, list[float | None]]) -> list[float | None]:
    n = max(len(v) for v in features.values()) if features else 0
    return [eval_at(expr, features, i) for i in range(n)]


def stringify(expr: Expr) -> str:
    if expr.op == "terminal":
        return expr.terminal or "?"
    if expr.op == "delay":
        return f"delay({expr.lag},{stringify(expr.left) if expr.left else '?'})"
    if expr.op in UNARY_OPS:
        return f"{expr.op}({stringify(expr.left) if expr.left else '?'})"
    return f"{expr.op}({stringify(expr.left) if expr.left else '?'}, {stringify(expr.right) if expr.right else '?'})"


def _collect_nodes(expr: Expr, acc: list[Expr]) -> None:
    acc.append(expr)
    if expr.left is not None:
        _collect_nodes(expr.left, acc)
    if expr.right is not None:
        _collect_nodes(expr.right, acc)


def _replace_subtree(root: Expr, target: Expr, replacement: Expr) -> Expr:
    if root is target:
        return replacement.copy()
    cloned = root.copy()
    if cloned.left is not None:
        cloned.left = _replace_subtree(cloned.left, target, replacement)
    if cloned.right is not None:
        cloned.right = _replace_subtree(cloned.right, target, replacement)
    return cloned


def mutate(expr: Expr, terminals: list[str], rng: random.Random, *, max_depth: int = 4) -> Expr:
    nodes: list[Expr] = []
    _collect_nodes(expr, nodes)
    target = rng.choice(nodes)
    if rng.random() < 0.5:
        replacement = random_expr(terminals, rng, max_depth=max_depth)
    else:
        replacement = random_terminal(terminals, rng)
    return _replace_subtree(expr, target, replacement)


def crossover(a: Expr, b: Expr, rng: random.Random) -> tuple[Expr, Expr]:
    nodes_a: list[Expr] = []
    nodes_b: list[Expr] = []
    _collect_nodes(a, nodes_a)
    _collect_nodes(b, nodes_b)
    if len(nodes_a) < 2 or len(nodes_b) < 2:
        return a.copy(), b.copy()
    sub_a = rng.choice(nodes_a[1:] or nodes_a)
    sub_b = rng.choice(nodes_b[1:] or nodes_b)
    child_a = _replace_subtree(a, sub_a, sub_b)
    child_b = _replace_subtree(b, sub_b, sub_a)
    return child_a, child_b


def fitness_fn(
    expr: Expr,
    features: dict[str, list[float | None]],
    labels: list[float | None],
    *,
    complexity_penalty: float = 0.01,
) -> float:
    from factor_mining.evaluate import evaluate_factor

    signal = eval_series(expr, features)
    metrics = evaluate_factor(signal, labels, min_samples=15)
    if metrics is None:
        return -1.0
    return abs(metrics.ic_mean) - complexity_penalty * expr.node_count()


def tournament_select(
    population: list[tuple[Expr, float]],
    rng: random.Random,
    k: int = 3,
) -> Expr:
    contenders = rng.sample(population, min(k, len(population)))
    return max(contenders, key=lambda item: item[1])[0].copy()
