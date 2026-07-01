"""Tests for GP / ML factor mining teaching module."""

from __future__ import annotations

import pytest
from factor_mining.evaluate import evaluate_factor, spearman
from factor_mining.expressions import eval_series, random_expr, stringify
from factor_mining.features import build_feature_matrix
from factor_mining.gp import GPConfig, run_gp_search
from factor_mining.ml import run_ml_search
from factor_mining.service import run_factor_mining, run_mined_factor_backtest
from factor_mining.serialize import expr_from_dict, expr_to_dict


def _sample_candles(count: int = 80) -> list[dict]:
    candles: list[dict] = []
    price = 100.0
    for i in range(count):
        drift = 0.002 if i % 7 < 4 else -0.001
        price *= 1.0 + drift
        candles.append(
            {
                "tsSec": 1_700_000_000 + i * 86_400,
                "date": f"2024-01-{i + 1:02d}",
                "open": price * 0.999,
                "close": price,
                "high": price * 1.004,
                "low": price * 0.996,
                "volume": 1000 + (i % 5) * 120,
            }
        )
    return candles


def test_spearman_is_bounded() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert spearman(xs, ys) == pytest.approx(1.0)


def test_build_feature_matrix_aligns_labels() -> None:
    features, labels, names = build_feature_matrix(_sample_candles(), horizon=1)
    assert len(names) >= 10
    assert len(labels) == len(_sample_candles())
    metrics = evaluate_factor(features["ret_1"], labels, min_samples=20)
    assert metrics is not None
    assert metrics.sample_count > 0
    assert -1.0 <= metrics.rank_autocorr <= 1.0
    assert 0.0 <= metrics.p_value <= 1.0
    assert len(metrics.quantile_returns) == 5


def test_gp_search_returns_expression() -> None:
    features, labels, names = build_feature_matrix(_sample_candles(), horizon=1)
    result = run_gp_search(
        features,
        labels,
        names,
        config=GPConfig(population_size=8, generations=4, seed=7),
    )
    assert result["method"] == "gp"
    assert result["expression"]
    assert result["expr"].node_count() >= 1


def test_ml_search_selects_features() -> None:
    features, labels, names = build_feature_matrix(_sample_candles(), horizon=1)
    result = run_ml_search(features, labels, names, max_features=3)
    assert result["method"] == "ml"
    assert isinstance(result["selected_features"], list)
    assert result["formula"]


def test_run_factor_mining_both_modes() -> None:
    payload = run_factor_mining(
        mode="both",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        horizon=1,
        gp_generations=4,
        gp_population=8,
        seed=11,
    )
    assert payload["ok"] is True
    leader = payload.get("leader")
    assert leader is not None
    assert "validation" in leader
    assert "quintile_spread" in leader["validation"]
    assert "turnover_rate" in leader["validation"]
    assert "p_value" in payload["gp"]["test"]
    assert "rank_autocorr" in payload["gp"]["test"]
    assert len(payload["gp"]["test"]["quantile_returns"]) == 5
    assert payload["ok"] is True
    assert payload["gp"]["expression"]
    assert payload["gp"]["backtest_spec"]["factor_source"] == "gp"
    assert payload["ml"]["selected_features"] is not None
    assert payload["ml"]["backtest_spec"]["factor_source"] == "ml"
    assert payload["leader"] is not None
    assert payload["leader"]["backtest_spec"]
    assert payload["baseline_univariate"]
    assert payload["warnings"]


def test_mined_factor_backtest_runs() -> None:
    mined = run_factor_mining(
        mode="ml",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        gp_generations=3,
        gp_population=6,
        seed=3,
    )
    spec = mined["leader"]["backtest_spec"]
    payload = run_mined_factor_backtest(backtest_spec=spec, symbol="WEB3-DEMO/USDT", limit=120)
    assert payload["ok"] is True
    assert payload["strategy_key"] == "mined_factor"
    assert payload["factor_label"]


def test_risk_factor_mining_returns_risk_spec() -> None:
    payload = run_factor_mining(
        mode="both",
        target="risk",
        risk_kind="abs_ret",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        gp_generations=4,
        gp_population=8,
        seed=42,
    )
    assert payload["ok"] is True
    assert payload["mining_target"] == "risk"
    assert payload["metric_name"] == "RIC"
    assert payload["leader"] is not None
    assert payload["leader"]["risk_spec"]
    assert payload["leader"].get("backtest_spec") is None
    assert payload["risk_application"]
    assert payload["gp"]["risk_spec"]["application"] == "position_scale"


def test_risk_backtest_spec_rejected() -> None:
    mined = run_factor_mining(
        mode="ml",
        target="risk",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        gp_generations=3,
        gp_population=6,
        seed=5,
    )
    spec = mined["leader"]["risk_spec"]
    with pytest.raises(ValueError, match="风险因子"):
        run_mined_factor_backtest(backtest_spec=spec, symbol="WEB3-DEMO/USDT", limit=120)


def test_build_risk_labels() -> None:
    from factor_mining.features import build_feature_matrix

    candles = _sample_candles(80)
    _, abs_labels, _ = build_feature_matrix(candles, horizon=2, target="risk", risk_kind="abs_ret")
    _, vol_labels, _ = build_feature_matrix(candles, horizon=3, target="risk", risk_kind="realized_vol")
    assert any(v is not None and v >= 0 for v in abs_labels)
    assert any(v is not None and v >= 0 for v in vol_labels)


def test_expr_roundtrip() -> None:
    import random

    rng = random.Random(1)
    expr = random_expr(["ret_1", "rsi", "vol_ratio"], rng, max_depth=3)
    restored = expr_from_dict(expr_to_dict(expr))
    features, _, _ = build_feature_matrix(_sample_candles(), horizon=1)
    assert eval_series(expr, features) == eval_series(restored, features)


def test_random_expr_stringifies() -> None:
    import random

    rng = random.Random(0)
    expr = random_expr(["ret_1", "rsi"], rng, max_depth=3)
    text = stringify(expr)
    features, _, _ = build_feature_matrix(_sample_candles(), horizon=1)
    series = eval_series(expr, features)
    assert len(series) == len(_sample_candles())
    assert text
