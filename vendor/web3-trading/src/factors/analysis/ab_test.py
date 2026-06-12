# -*- coding: utf-8 -*-
"""A/B 测试框架 — 比较两个 RankingProfile 的回测表现。"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict

import numpy as np
from scipy.stats import ttest_ind

from factors.analysis.models import (
    ABComparisonRow,
    ABTestReport,
    ABTestWinner,
    OptimizerType,
)
from factors.backtest.config import BacktestConfig
from factors.backtest.engine import BacktestEngine
from factors.ranking.profile import RankingProfile

logger = logging.getLogger(__name__)


class ABTestRunner:
    """比较两个 RankingProfile 的回测表现。"""

    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    async def compare(
        self,
        profile_a: RankingProfile,
        profile_b: RankingProfile,
        config: BacktestConfig,
        *,
        optimizer_types: list[OptimizerType] | None = None,
    ) -> ABTestReport:
        """依次执行两个 profile 的回测，生成对比报告。"""
        report_a, sharpe_a, scores_a = await self._compute_profile_sharpe(profile_a, config)
        report_b, sharpe_b, scores_b = await self._compute_profile_sharpe(profile_b, config)

        p_value = self._welch_ttest(scores_a, scores_b)

        if p_value < 0.05:
            winner = ABTestWinner.PROFILE_B if sharpe_b > sharpe_a else ABTestWinner.PROFILE_A
        else:
            winner = ABTestWinner.NO_SIGNIFICANT_DIFFERENCE

        per_factor = self._build_comparison(report_a, report_b, profile_a, profile_b)

        recommendations: list[str] = []
        if winner == ABTestWinner.PROFILE_A:
            recommendations.append(f"建议保持 {profile_a.profile_id}")
        elif winner == ABTestWinner.PROFILE_B:
            recommendations.append(f"建议切换到 {profile_b.profile_id}")
        else:
            improvements = [
                row for row in per_factor
                if row.ir_b > row.ir_a + 0.05
            ]
            if improvements:
                recommendations.append(
                    f"虽然整体差异不显著，但 {len(improvements)} 个因子在 B 方案下 IR 有所提升"
                )

        return ABTestReport(
            id=uuid.uuid4().hex,
            profile_a_id=profile_a.profile_id,
            profile_b_id=profile_b.profile_id,
            optimizer_types=optimizer_types or [],
            winner=winner,
            sharpe_a=round(sharpe_a, 6),
            sharpe_b=round(sharpe_b, 6),
            p_value=round(p_value, 6),
            per_factor_comparison=per_factor,
            recommendation="; ".join(recommendations),
        )

    async def _compute_profile_sharpe(
        self,
        profile: RankingProfile,
        config: BacktestConfig,
    ) -> tuple:
        """按给定 profile 回测并计算夏普和逐时间点分数。"""
        from factors.config import PipelineConfig

        pipeline_config = PipelineConfig.for_spot()
        pipeline_config = pipeline_config.model_copy(update={"ranking_profile": profile})
        config_copy = config.model_copy(update={})

        # 获取原始 engine 的 simulator 读取快照
        timepoints = await self._engine._simulator.replay(config_copy)
        report = await self._engine._evaluator.evaluate(timepoints, config_copy)

        # 用 timepoint aggregate_score 算滚动夏普
        if timepoints:
            scores = [tp.aggregate_score for tp in timepoints]
            sharpe = self._sharpe_from_scores(scores)
        else:
            scores = []
            sharpe = 0.0

        return report, sharpe, scores

    def _build_comparison(
        self,
        report_a,
        report_b,
        profile_a: RankingProfile,
        profile_b: RankingProfile,
    ) -> list[ABComparisonRow]:
        """构建逐因子对比表。"""
        metrics_a: dict[str, dict] = {}
        for m in report_a.per_factor:
            if m.factor_name not in metrics_a or m.sample_count > metrics_a[m.factor_name].get("n", 0):
                metrics_a[m.factor_name] = {"ic": m.ic_mean, "ir": m.ir, "n": m.sample_count}

        metrics_b: dict[str, dict] = {}
        for m in report_b.per_factor:
            if m.factor_name not in metrics_b or m.sample_count > metrics_b[m.factor_name].get("n", 0):
                metrics_b[m.factor_name] = {"ic": m.ic_mean, "ir": m.ir, "n": m.sample_count}

        all_names = sorted(set(metrics_a.keys()) | set(metrics_b.keys()))
        rows: list[ABComparisonRow] = []
        for name in all_names:
            rows.append(ABComparisonRow(
                factor_name=name,
                weight_a=round(profile_a.get_weight(name), 4),
                weight_b=round(profile_b.get_weight(name), 4),
                ic_mean_a=round(metrics_a.get(name, {}).get("ic", 0.0), 6),
                ic_mean_b=round(metrics_b.get(name, {}).get("ic", 0.0), 6),
                ir_a=round(metrics_a.get(name, {}).get("ir", 0.0), 6),
                ir_b=round(metrics_b.get(name, {}).get("ir", 0.0), 6),
            ))
        return rows

    @staticmethod
    def _welch_ttest(scores_a: list[float], scores_b: list[float]) -> float:
        """Welch t-test 检验两个分布均值差异显著性。"""
        if len(scores_a) < 2 or len(scores_b) < 2:
            return 1.0
        try:
            result = ttest_ind(scores_a, scores_b, equal_var=False)
            p = result.pvalue if hasattr(result, "pvalue") else result[1]
            return float(p) if p is not None else 1.0
        except Exception:
            return 1.0

    @staticmethod
    def _sharpe_from_scores(scores: list[float], annualize: int = 365) -> float:
        """用信号分数序列近似估计夏普。"""
        if len(scores) < 2:
            return 0.0
        returns = np.diff(np.array(scores, dtype=np.float64))
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))
        if sigma < 1e-8:
            return 0.0 if mu == 0 else (1.0 if mu > 0 else -1.0)
        return mu / sigma * np.sqrt(annualize)
