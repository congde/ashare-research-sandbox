# -*- coding: utf-8 -*-
"""信号评估器 — 计算 IC/IR/Hit Rate 等评估指标。"""

from collections import defaultdict

import numpy as np
from scipy.stats import spearmanr

from factors.backtest.config import BacktestConfig
from factors.backtest.models import BacktestReport, BacktestTimePoint, EvalMetrics


class Evaluator:
    """评估因子信号与未来收益的关系。"""

    def __init__(self, kucoin=None) -> None:
        self._kucoin = kucoin

    async def evaluate(
        self,
        timepoints: list[BacktestTimePoint],
        config: BacktestConfig,
    ) -> BacktestReport:
        """对时间点序列进行完整评估。"""
        if not timepoints:
            return BacktestReport(config_snapshot=config.model_dump())

        factor_names = list(timepoints[0].factor_scores.keys())
        all_metrics: list[EvalMetrics] = []

        for factor_name in factor_names:
            horizons = self._get_horizons(factor_name, config)
            for horizon in horizons:
                pairs = await self._build_signal_return_pairs(timepoints, factor_name, horizon)
                if len(pairs) < config.min_snapshots:
                    continue

                signals = [p[0] for p in pairs]
                returns = [p[1] for p in pairs]

                ic_mean, ic_std = self._compute_ic(signals, returns)
                hit_rate = self._compute_hit_rate(signals, returns)
                ir = ic_mean / ic_std if ic_std > 0 else 0.0

                all_metrics.append(EvalMetrics(
                    factor_name=factor_name,
                    horizon=horizon,
                    ic_mean=round(ic_mean, 6),
                    ic_std=round(ic_std, 6),
                    ir=round(ir, 6),
                    hit_rate=round(hit_rate, 6),
                    sample_count=len(pairs),
                    signal_distribution=self._signal_dist(signals),
                ))

        return self._build_report(all_metrics, config)

    async def _build_signal_return_pairs(
        self,
        timepoints: list[BacktestTimePoint],
        factor_name: str,
        horizon: str,
    ) -> list[tuple[float, float]]:
        """构建 (signal, forward_return) 对列表。"""
        horizon_ms = self._horizon_to_ms(horizon)
        pairs: list[tuple[float, float]] = []

        for tp in timepoints:
            signal = tp.factor_scores.get(factor_name, 0.0)
            future_price = await self._get_price_at(tp.symbol, tp.timestamp_ms + horizon_ms)
            entry_price = await self._get_price_at(tp.symbol, tp.timestamp_ms)
            if future_price is not None and entry_price is not None and entry_price > 0:
                forward_return = (future_price - entry_price) / entry_price
                pairs.append((signal, forward_return))

        return pairs

    async def _get_price_at(self, symbol: str, target_ms: int) -> float | None:
        """从 KuCoin 获取指定时间点的收盘价。"""
        if self._kucoin is None:
            return None

        from libs.kucoin_openapi.enums import KlineGranularity

        symbol_pair = f"{symbol}-USDT"
        for tf, granularity in [("1h", KlineGranularity.H1), ("4h", KlineGranularity.H4), ("1d", KlineGranularity.D1)]:
            try:
                start_at = (target_ms // 1000) - 7200
                end_at = (target_ms // 1000) + 3600
                klines = await self._kucoin.get_kline(
                    symbol=symbol_pair,
                    granularity=granularity,
                    start_at=start_at,
                    end_at=end_at,
                )
                if klines:
                    closest = min(klines, key=lambda k: abs(k.time * 1000 - target_ms))
                    return closest.close
            except Exception:
                continue
        return None

    def _get_horizons(self, factor_name: str, config: BacktestConfig) -> list[str]:
        return sorted(set(config.granularity_horizon_map.values()))

    def _horizon_to_ms(self, horizon: str) -> int:
        mapping = {"1h": 3600000, "4h": 14400000, "1d": 86400000, "3d": 259200000}
        return mapping.get(horizon, 86400000)

    def _compute_ic(self, signals: list[float], returns: list[float]) -> tuple[float, float]:
        """计算 Spearman rank correlation（IC）及其滚动窗口标准差。"""
        if len(signals) < 3:
            return 0.0, 0.0
        arr_s = np.array(signals, dtype=np.float64)
        arr_r = np.array(returns, dtype=np.float64)
        result = spearmanr(arr_s, arr_r)
        ic = result.correlation if hasattr(result, 'correlation') else result[0]
        if np.isnan(ic):
            return 0.0, 0.0

        window = min(10, max(3, len(signals) // 2))
        ics: list[float] = []
        for i in range(len(signals) - window + 1):
            w_s = arr_s[i:i + window]
            w_r = arr_r[i:i + window]
            r = spearmanr(w_s, w_r)
            w_ic = r.correlation if hasattr(r, 'correlation') else r[0]
            if not np.isnan(w_ic):
                ics.append(w_ic)

        ic_std = float(np.std(ics)) if ics else 0.0
        return float(ic), ic_std

    def _compute_hit_rate(self, signals: list[float], returns: list[float]) -> float:
        """计算方向正确率 P(sign(signal) == sign(return))。"""
        if not signals:
            return 0.0
        correct = 0
        for s, r in zip(signals, returns):
            s_sign = 1 if s >= 0 else -1
            r_sign = 1 if r >= 0 else -1
            if s_sign == r_sign:
                correct += 1
        return correct / len(signals)

    def _signal_dist(self, signals: list[float]) -> dict[str, int]:
        bullish = sum(1 for s in signals if s >= 0)
        return {"bullish": bullish, "bearish": len(signals) - bullish}

    def _build_report(self, metrics: list[EvalMetrics], config: BacktestConfig) -> BacktestReport:
        by_category: dict[str, list[EvalMetrics]] = defaultdict(list)
        for m in metrics:
            by_category[m.category or "unknown"].append(m)

        per_category = []
        for cat, items in by_category.items():
            valid = [x for x in items if x.ic_mean != 0.0 or x.hit_rate != 0.0]
            if valid:
                per_category.append({
                    "category": cat,
                    "factor_count": len(items),
                    "avg_ic_mean": round(float(np.mean([x.ic_mean for x in valid])), 6),
                    "avg_ir": round(float(np.mean([x.ir for x in valid])), 6),
                    "avg_hit_rate": round(float(np.mean([x.hit_rate for x in valid])), 6),
                })

        sorted_by_ic = sorted(metrics, key=lambda m: m.ic_mean, reverse=True)
        sorted_by_ir = sorted(metrics, key=lambda m: m.ir, reverse=True)

        return BacktestReport(
            config_snapshot=config.model_dump(),
            per_factor=metrics,
            per_category=per_category,
            aggregate_summary={
                "total_factors": len({m.factor_name for m in metrics}),
                "total_metrics": len(metrics),
                "avg_hit_rate": round(float(np.mean([m.hit_rate for m in metrics])), 6) if metrics else 0,
            },
            top_factors_by_ic=[m.factor_name for m in sorted_by_ic[:10]],
            top_factors_by_ir=[m.factor_name for m in sorted_by_ir[:10]],
        )
