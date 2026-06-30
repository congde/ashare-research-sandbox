"""Genetic programming search for symbolic alpha factors."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from factor_mining.evaluate import FactorMetrics, evaluate_factor
from factor_mining.expressions import (
    Expr,
    crossover,
    fitness_fn,
    mutate,
    random_expr,
    stringify,
    tournament_select,
    eval_series,
)


@dataclass
class GPConfig:
    population_size: int = 24
    generations: int = 12
    max_depth: int = 4
    elite_count: int = 2
    mutation_rate: float = 0.25
    complexity_penalty: float = 0.01
    seed: int = 42


def run_gp_search(
    features: dict[str, list[float | None]],
    labels: list[float | None],
    terminals: list[str],
    *,
    config: GPConfig | None = None,
) -> dict[str, Any]:
    cfg = config or GPConfig()
    rng = random.Random(cfg.seed)

    population: list[Expr] = [
        random_expr(terminals, rng, max_depth=cfg.max_depth)
        for _ in range(cfg.population_size)
    ]

    history: list[dict[str, Any]] = []
    best_expr = population[0]
    best_fitness = -1.0

    for generation in range(cfg.generations):
        scored: list[tuple[Expr, float]] = [
            (
                expr,
                fitness_fn(
                    expr,
                    features,
                    labels,
                    complexity_penalty=cfg.complexity_penalty,
                ),
            )
            for expr in population
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        leader_expr, leader_fit = scored[0]
        if leader_fit > best_fitness:
            best_fitness = leader_fit
            best_expr = leader_expr.copy()

        leader_metrics = evaluate_factor(eval_series(leader_expr, features), labels, min_samples=15)
        history.append(
            {
                "generation": generation + 1,
                "best_fitness": round(leader_fit, 6),
                "best_ic": leader_metrics.ic_mean if leader_metrics else 0.0,
                "expression": stringify(leader_expr),
            }
        )

        next_gen = [expr.copy() for expr, _ in scored[: cfg.elite_count]]
        while len(next_gen) < cfg.population_size:
            parent_a = tournament_select(scored, rng)
            parent_b = tournament_select(scored, rng)
            child_a, child_b = crossover(parent_a, parent_b, rng)
            if rng.random() < cfg.mutation_rate:
                child_a = mutate(child_a, terminals, rng, max_depth=cfg.max_depth)
            if rng.random() < cfg.mutation_rate:
                child_b = mutate(child_b, terminals, rng, max_depth=cfg.max_depth)
            next_gen.extend([child_a, child_b])
        population = next_gen[: cfg.population_size]

    signal = eval_series(best_expr, features)
    metrics = evaluate_factor(signal, labels)
    return {
        "method": "gp",
        "expression": stringify(best_expr),
        "expr": best_expr,
        "fitness": round(best_fitness, 6),
        "complexity": best_expr.node_count(),
        "metrics": _metrics_dict(metrics),
        "history": history[-5:],
    }


def _metrics_dict(metrics: FactorMetrics | None) -> dict[str, Any]:
    if metrics is None:
        return {"ic_mean": 0.0, "ic_std": 0.0, "ir": 0.0, "hit_rate": 0.0, "sample_count": 0}
    return {
        "ic_mean": metrics.ic_mean,
        "ic_std": metrics.ic_std,
        "ir": metrics.ir,
        "hit_rate": metrics.hit_rate,
        "sample_count": metrics.sample_count,
    }
