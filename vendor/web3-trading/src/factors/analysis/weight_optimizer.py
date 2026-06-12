# -*- coding: utf-8 -*-
"""因子权重优化器 — 从回测报告中生成数据驱动的因子权重。"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

import numpy as np

from factors.analysis.models import (
    OptimizedWeight,
    OptimizerResult,
    OptimizerType,
)
from factors.backtest.models import BacktestReport, EvalMetrics
from factors.enums import MarketType

logger = logging.getLogger(__name__)


class WeightOptimizer:
    """统一入口：从回测报告生成优化权重。

    输入 BacktestReport.per_factor（EvalMetrics 列表），
    对每个因子取 best horizon（sample_count 最大），
    然后应用优化方法生成权重向量。
    """

    def __init__(self, report: BacktestReport, market_type: MarketType = MarketType.SPOT) -> None:
        self._market_type = market_type
        self._factor_names, self._best_metrics = self._pick_best_horizons(report.per_factor)
        self._n = len(self._factor_names)

    # ── 公共入口 ────────────────────────────────────────────────────────────

    def optimize(self, method: OptimizerType) -> OptimizerResult:
        weights = self._dispatch(method)
        sharpe = self._estimate_sharpe(weights)
        ew_sharpe = self._estimate_sharpe(self._equal_weight())
        improvement = (sharpe - ew_sharpe) / abs(ew_sharpe) if ew_sharpe > 0 else 0.0

        return OptimizerResult(
            optimizer_type=method,
            profile_id=f"{method.value}_v{int(time.time())}",
            market_type=self._market_type,
            weights=weights,
            sharpe_estimate=round(sharpe, 6),
            equal_weight_sharpe=round(ew_sharpe, 6),
            sharpe_improvement=round(improvement, 6),
        )

    # ── 内部调度 ────────────────────────────────────────────────────────────

    def _dispatch(self, method: OptimizerType) -> list[OptimizedWeight]:
        if method == OptimizerType.IC_WEIGHTED:
            return self._ic_weighted()
        if method == OptimizerType.RISK_PARITY:
            return self._risk_parity()
        if method == OptimizerType.MEAN_VARIANCE:
            return self._mean_variance()
        return self._equal_weight()

    # ── IC 加权 ─────────────────────────────────────────────────────────────

    def _ic_weighted(self) -> list[OptimizedWeight]:
        raw: list[float] = []
        for i, name in enumerate(self._factor_names):
            m = self._best_metrics[i]
            ic_std = m.ic_std if m.ic_std > 1e-8 else 1e-8
            ic = max(0.0, m.ic_mean)
            raw.append(ic / ic_std)
        return self._normalize(raw, "ic_ir")

    # ── 风险平价 ────────────────────────────────────────────────────────────

    def _risk_parity(self) -> list[OptimizedWeight]:
        raw: list[float] = []
        for i, name in enumerate(self._factor_names):
            m = self._best_metrics[i]
            dist = m.signal_distribution or {}
            total_signals = dist.get("bullish", 0) + dist.get("bearish", 0)
            if total_signals <= 1:
                raw.append(0.0)
                continue
            bullish_ratio = max(dist.get("bullish", 0), 1) / total_signals
            sigma_est = 1.0 / (bullish_ratio * (1.0 - bullish_ratio) + 0.1)
            raw.append(1.0 / max(sigma_est, 1e-8))
        return self._normalize(raw, "inv_sigma")

    # ── 均值-方差 ───────────────────────────────────────────────────────────

    def _mean_variance(self) -> list[OptimizedWeight]:
        n = self._n
        if n <= 1:
            return self._equal_weight()
        ic_vec = np.array([m.ic_mean for m in self._best_metrics], dtype=np.float64)
        cov = self._estimate_ic_covariance()
        try:
            precision = np.linalg.pinv(cov)
            raw = precision @ ic_vec
            raw = np.maximum(raw, 0.0)
        except np.linalg.LinAlgError:
            raw = np.maximum(ic_vec, 0.0)
        return self._normalize(raw.tolist(), "mv_score")

    # ── 等权基线 ────────────────────────────────────────────────────────────

    def _equal_weight(self) -> list[OptimizedWeight]:
        n = self._n
        if n == 0:
            return []
        w = 1.0 / n
        return [
            OptimizedWeight(
                factor_name=name,
                raw_weight=w,
                normalized_weight=w,
                optimizer_metric=1.0 / n,
            )
            for name in self._factor_names
        ]

    # ── 辅助 ────────────────────────────────────────────────────────────────

    def _normalize(self, raw: list[float], metric_key: str) -> list[OptimizedWeight]:
        total = sum(raw)
        result: list[OptimizedWeight] = []
        for i, name in enumerate(self._factor_names):
            nw = raw[i] / total if total > 0 else 0.0
            result.append(OptimizedWeight(
                factor_name=name,
                raw_weight=raw[i],
                normalized_weight=round(nw, 6),
                optimizer_metric=raw[i] if metric_key != "ic_ir" else round(
                    self._best_metrics[i].ic_mean / max(self._best_metrics[i].ic_std, 1e-8), 6,
                ),
            ))
        return result

    def _estimate_sharpe(self, weights: list[OptimizedWeight]) -> float:
        """基于因子 IC/IR 近似组合夏普。

        使用公式: IR_portfolio = sum(w_i * IR_i) / sqrt(w^T * Corr_IC * w)
        Sharpe ≈ sqrt(N) * IR_portfolio / sqrt(IR_portfolio^2 + 1)
        """
        if not weights:
            return 0.0
        w = np.array([x.normalized_weight for x in weights], dtype=np.float64)
        ir_vec = np.array([m.ir for m in self._best_metrics], dtype=np.float64)
        cov = self._estimate_ic_covariance()
        port_ir = float(np.dot(w, ir_vec) / max(np.sqrt(w @ cov @ w), 1e-8))
        n = len(weights)
        sharpe = np.sqrt(n) * port_ir / np.sqrt(port_ir ** 2 + 1.0)
        return round(float(sharpe), 6)

    def _estimate_ic_covariance(self) -> np.ndarray:
        """用 IC_mean 向量近似 IC 协方差矩阵。"""
        n = self._n
        if n <= 1:
            return np.eye(n, dtype=np.float64) * 0.01
        corr = np.eye(n, dtype=np.float64)
        std_vec = np.array([max(m.ic_std, 1e-4) for m in self._best_metrics], dtype=np.float64)
        cov = np.outer(std_vec, std_vec) * corr
        cov += np.eye(n, dtype=np.float64) * 1e-6
        return cov

    @staticmethod
    def _pick_best_horizons(
        metrics: list[EvalMetrics],
    ) -> tuple[list[str], list[EvalMetrics]]:
        """对每个 factor_name 选 sample_count 最大的 horizon。"""
        groups: dict[str, list[EvalMetrics]] = defaultdict(list)
        for m in metrics:
            groups[m.factor_name].append(m)

        factor_names = sorted(groups.keys())
        best: list[EvalMetrics] = []
        for name in factor_names:
            candidates = groups[name]
            pick = max(candidates, key=lambda x: x.sample_count)
            best.append(pick)
        return factor_names, best


# ── 本地持久化 ────────────────────────────────────────────────────────────────


class WeightOptimizerResultWriter:
    """将优化结果写入本地 data/factors/weight_optimizations/。"""

    @staticmethod
    async def save(result: OptimizerResult) -> str:
        doc = result.model_dump()
        doc["_id"] = result.profile_id
        try:
            from factors.local_store import save_weight_optimization

            await save_weight_optimization(doc)
        except Exception:
            logger.exception("保存权重优化结果失败: %s", result.profile_id)
            raise
        return result.profile_id

    @staticmethod
    async def load(profile_id: str) -> OptimizerResult | None:
        try:
            from factors.local_store import load_weight_optimization

            doc = await load_weight_optimization(profile_id)
            if doc:
                return OptimizerResult(**doc)
        except Exception:
            logger.exception("加载权重优化结果失败: %s", profile_id)
        return None
