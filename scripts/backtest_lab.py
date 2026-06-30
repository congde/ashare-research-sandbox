#!/usr/bin/env python3
"""Teaching CLI for backtest chapters 18 and 21."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest.trace import run_ma_crossover_trace, run_teaching_scenario  # noqa: E402
from backtest.metrics_explain import explain_metrics  # noqa: E402
from backtest.pollution import run_pollution_checks  # noqa: E402
from backtest.research_path import run_research_path  # noqa: E402
from backtest.rolling.service import (
    compare_strategies,
    compare_windows,
    get_trial_audit,
    run_cpcv_service,
    run_robustness_audit,
    run_walk_forward,
)
from backtest.rolling.portfolio import compare_portfolio  # noqa: E402
from factor_mining.service import run_factor_mining  # noqa: E402


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_trace(_: argparse.Namespace) -> None:
    _print_json(run_ma_crossover_trace())


def cmd_scenario(_: argparse.Namespace) -> None:
    _print_json(run_teaching_scenario())


def cmd_compare(args: argparse.Namespace) -> None:
    _print_json(
        compare_strategies(
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
        )
    )


def cmd_windows(args: argparse.Namespace) -> None:
    _print_json(
        compare_windows(
            strategy_name=args.strategy,
            num_windows=args.windows,
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
        )
    )


def cmd_walk_forward(args: argparse.Namespace) -> None:
    _print_json(
        run_walk_forward(
            strategy_name=args.strategy,
            num_windows=args.windows,
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
            cost_preset=args.cost_preset,
        )
    )


def cmd_robustness(args: argparse.Namespace) -> None:
    _print_json(
        run_robustness_audit(
            strategy_name=args.strategy,
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
            cost_preset=args.cost_preset,
        )
    )


def cmd_cpcv(args: argparse.Namespace) -> None:
    _print_json(
        run_cpcv_service(
            strategy_name=args.strategy,
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
            cost_preset=args.cost_preset,
        )
    )


def cmd_audit(args: argparse.Namespace) -> None:
    _print_json(get_trial_audit(strategy_key=args.strategy or None))


def cmd_portfolio(args: argparse.Namespace) -> None:
    _print_json(
        compare_portfolio(
            strategy_name=args.strategy,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
        )
    )


def cmd_metrics(args: argparse.Namespace) -> None:
    _print_json(
        explain_metrics(
            symbol=args.symbol,
            limit=args.limit,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
        )
    )


def cmd_pollution(_: argparse.Namespace) -> None:
    _print_json(run_pollution_checks())


def cmd_path(args: argparse.Namespace) -> None:
    _print_json(
        run_research_path(
            short=args.short,
            long=args.long,
            strategy=args.strategy,
            include_factor_mine=args.factor_mine,
        )
    )


def cmd_mine(args: argparse.Namespace) -> None:
    _print_json(
        run_factor_mining(
            mode=args.mode,  # type: ignore[arg-type]
            target=args.target,  # type: ignore[arg-type]
            risk_kind=args.risk_kind,  # type: ignore[arg-type]
            symbol=args.symbol,
            limit=args.limit,
            horizon=args.horizon,
            gp_generations=args.gp_generations,
            gp_population=args.gp_population,
            seed=args.seed,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest teaching lab")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("trace", help="Chapter 18: MA crossover event trail").set_defaults(func=cmd_trace)
    sub.add_parser("scenario", help="Chapter 18: fill / pending / risk block demo").set_defaults(
        func=cmd_scenario
    )

    compare = sub.add_parser("compare", help="Chapter 21: multi-strategy comparison")
    compare.add_argument("--symbol", default="WEB3-DEMO/USDT")
    compare.add_argument("--limit", type=int, default=120)
    compare.add_argument("--stop-loss", type=float, default=3.0)
    compare.add_argument("--take-profit", type=float, default=5.0)
    compare.set_defaults(func=cmd_compare)

    windows = sub.add_parser("windows", help="Chapter 21: split-sample window check")
    windows.add_argument("--strategy", default="ma_crossover")
    windows.add_argument("--windows", type=int, default=3)
    windows.add_argument("--symbol", default="WEB3-DEMO/USDT")
    windows.add_argument("--limit", type=int, default=120)
    windows.add_argument("--stop-loss", type=float, default=3.0)
    windows.add_argument("--take-profit", type=float, default=5.0)
    windows.set_defaults(func=cmd_windows)

    wfo = sub.add_parser("walk-forward", help="Chapter 21: train/validate param search")
    wfo.add_argument("--strategy", default="ma_crossover")
    wfo.add_argument("--windows", type=int, default=3)
    wfo.add_argument("--symbol", default="WEB3-DEMO/USDT")
    wfo.add_argument("--limit", type=int, default=120)
    wfo.add_argument("--stop-loss", type=float, default=3.0)
    wfo.add_argument("--take-profit", type=float, default=5.0)
    wfo.add_argument("--cost-preset", default="teaching", choices=("teaching", "realistic", "perp"))
    wfo.set_defaults(func=cmd_walk_forward)

    robustness = sub.add_parser("robustness", help="Parameter sensitivity + PBO audit")
    robustness.add_argument("--strategy", default="ma_crossover")
    robustness.add_argument("--symbol", default="WEB3-DEMO/USDT")
    robustness.add_argument("--limit", type=int, default=120)
    robustness.add_argument("--stop-loss", type=float, default=3.0)
    robustness.add_argument("--take-profit", type=float, default=5.0)
    robustness.add_argument("--cost-preset", default="teaching", choices=("teaching", "realistic", "perp"))
    robustness.set_defaults(func=cmd_robustness)

    cpcv = sub.add_parser("cpcv", help="Teaching-scale CPCV path distribution")
    cpcv.add_argument("--strategy", default="ma_crossover")
    cpcv.add_argument("--symbol", default="WEB3-DEMO/USDT")
    cpcv.add_argument("--limit", type=int, default=120)
    cpcv.add_argument("--stop-loss", type=float, default=3.0)
    cpcv.add_argument("--take-profit", type=float, default=5.0)
    cpcv.add_argument("--cost-preset", default="teaching", choices=("teaching", "realistic", "perp"))
    cpcv.set_defaults(func=cmd_cpcv)

    audit = sub.add_parser("audit", help="Trial ledger summary")
    audit.add_argument("--strategy", default="")
    audit.set_defaults(func=cmd_audit)

    portfolio = sub.add_parser("portfolio", help="Chapter 22: equal-weight multi-leg compare")
    portfolio.add_argument("--strategy", default="ma_crossover")
    portfolio.add_argument("--limit", type=int, default=120)
    portfolio.add_argument("--stop-loss", type=float, default=3.0)
    portfolio.add_argument("--take-profit", type=float, default=5.0)
    portfolio.set_defaults(func=cmd_portfolio)

    metrics = sub.add_parser("metrics", help="Chapter 19: return vs drawdown interpretation")
    metrics.add_argument("--symbol", default="WEB3-DEMO/USDT")
    metrics.add_argument("--limit", type=int, default=120)
    metrics.add_argument("--stop-loss", type=float, default=3.0)
    metrics.add_argument("--take-profit", type=float, default=5.0)
    metrics.set_defaults(func=cmd_metrics)

    sub.add_parser("pollution", help="Chapter 20: DSL vs lookahead checks").set_defaults(
        func=cmd_pollution
    )

    path = sub.add_parser("path", help="Chapter 34: end-to-end research path")
    path.add_argument("--short", type=int, default=3)
    path.add_argument("--long", type=int, default=7)
    path.add_argument("--strategy", default="ma_crossover")
    path.add_argument("--factor-mine", action="store_true", help="Append ML factor mine + backtest steps")
    path.set_defaults(func=cmd_path)

    mine = sub.add_parser("mine", help="GP / ML automatic factor discovery")
    mine.add_argument("--mode", choices=("gp", "ml", "both"), default="both")
    mine.add_argument("--target", choices=("return", "risk"), default="return", help="return=收益因子, risk=风险因子")
    mine.add_argument("--risk-kind", choices=("abs_ret", "realized_vol"), default="abs_ret", dest="risk_kind")
    mine.add_argument("--symbol", default="WEB3-DEMO/USDT")
    mine.add_argument("--limit", type=int, default=120)
    mine.add_argument("--horizon", type=int, default=1)
    mine.add_argument("--gp-generations", type=int, default=8)
    mine.add_argument("--gp-population", type=int, default=16)
    mine.add_argument("--seed", type=int, default=42)
    mine.set_defaults(func=cmd_mine)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
