# -*- coding: utf-8 -*-
"""信号相关性分析 — Spearman/Pearson 矩阵、VIF、高相关对检测。"""

from __future__ import annotations

import numpy as np
from scipy.stats import pearsonr, spearmanr

from factors.analysis.models import (
    CorrelationMatrix,
    FactorCorrelationPair,
)
from factors.backtest.models import BacktestTimePoint


class SignalCorrelationAnalyzer:
    """从回放时间点构建因子信号相关矩阵。

    内部构建 N_factors × T_timepoints 的信号矩阵，
    缺失值用 0 填充（对应因子在某个时间点未计算）。
    """

    def __init__(self, timepoints: list[BacktestTimePoint]) -> None:
        if not timepoints:
            self._factor_names: list[str] = []
            self._signal_matrix = np.empty((0, 0))
            return

        self._factor_names = sorted(timepoints[0].factor_scores.keys())
        t = len(timepoints)
        n = len(self._factor_names)
        matrix = np.zeros((n, t), dtype=np.float64)
        name_to_idx = {name: i for i, name in enumerate(self._factor_names)}

        for col, tp in enumerate(timepoints):
            for fname, score in tp.factor_scores.items():
                idx = name_to_idx.get(fname)
                if idx is not None:
                    matrix[idx, col] = score

        self._signal_matrix = matrix

    @property
    def factor_names(self) -> list[str]:
        return list(self._factor_names)

    def compute_pearson(self) -> list[list[float]]:
        n = len(self._factor_names)
        if n == 0:
            return []
        pearson = np.eye(n, dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                r, _ = pearsonr(self._signal_matrix[i], self._signal_matrix[j])
                if np.isnan(r):
                    r = 0.0
                pearson[i, j] = float(r)
                pearson[j, i] = float(r)
        return pearson.tolist()

    def compute_spearman(self) -> list[list[float]]:
        n = len(self._factor_names)
        if n == 0:
            return []
        spearman = np.eye(n, dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                result = spearmanr(self._signal_matrix[i], self._signal_matrix[j])
                rho = result.correlation if hasattr(result, "correlation") else result[0]
                if np.isnan(rho):
                    rho = 0.0
                spearman[i, j] = float(rho)
                spearman[j, i] = float(rho)
        return spearman.tolist()

    def compute_vif(self) -> dict[str, float]:
        """对每个因子计算 Variance Inflation Factor。

        VIF_j = 1 / (1 - R_j²)，其中 R_j² 是用其他所有因子预测因子 j 的 R²。
        使用最小二乘法：beta = (X_(-j)^T X_(-j))^{-1} X_(-j)^T y_j。
        """
        n = len(self._factor_names)
        if n <= 1:
            return {name: 1.0 for name in self._factor_names}

        X = self._signal_matrix.T  # T x N
        vif: dict[str, float] = {}
        for j in range(n):
            y = X[:, j]
            X_other = np.delete(X, j, axis=1)
            try:
                beta, _, _, _ = np.linalg.lstsq(X_other, y, rcond=None)
                y_pred = X_other @ beta
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = np.sum((y - np.mean(y)) ** 2)
                r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                vif_j = 1.0 / (1.0 - r_squared) if r_squared < 1.0 else float("inf")
            except np.linalg.LinAlgError:
                vif_j = float("inf")
            vif[self._factor_names[j]] = round(float(vif_j), 4)

        return vif

    def find_high_correlation_pairs(
        self, threshold: float = 0.7,
    ) -> list[FactorCorrelationPair]:
        """找出 |Spearman rho| > threshold 的所有因子对。"""
        n = len(self._factor_names)
        if n == 0:
            return []

        pearson = self.compute_pearson()
        spearman = self.compute_spearman()
        pairs: list[FactorCorrelationPair] = []

        for i in range(n):
            for j in range(i + 1, n):
                rho = spearman[i][j]
                if abs(rho) >= threshold:
                    p_val = self._spearman_p_value(self._signal_matrix[i], self._signal_matrix[j])
                    pairs.append(FactorCorrelationPair(
                        factor_a=self._factor_names[i],
                        factor_b=self._factor_names[j],
                        pearson_r=round(pearson[i][j], 6),
                        spearman_rho=round(rho, 6),
                        p_value=round(p_val, 6),
                    ))

        pairs.sort(key=lambda p: abs(p.spearman_rho), reverse=True)
        return pairs

    def build_matrix(self, threshold: float = 0.7) -> CorrelationMatrix:
        return CorrelationMatrix(
            factor_names=self._factor_names,
            pearson_matrix=self.compute_pearson(),
            spearman_matrix=self.compute_spearman(),
            high_correlation_pairs=self.find_high_correlation_pairs(threshold),
        )

    @staticmethod
    def _spearman_p_value(x: np.ndarray, y: np.ndarray) -> float:
        result = spearmanr(x, y)
        p = result.pvalue if hasattr(result, "pvalue") else result[1]
        return float(p) if p is not None else 1.0
