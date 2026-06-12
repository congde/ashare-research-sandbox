# -*- coding: utf-8 -*-
"""共线性检测 — Union-Find 分组 + 去重建议。"""

from __future__ import annotations

import uuid

from factors.analysis.models import (
    CollinearityGroup,
    CollinearitySeverity,
    CorrelationMatrix,
    DedupAction,
    DedupPlan,
)


class CollinearityDetector:
    """基于 Spearman 相关矩阵检测共线性组并生成去重计划。"""

    def __init__(self, correlation_matrix: CorrelationMatrix) -> None:
        self._matrix = correlation_matrix

    def detect_groups(self, threshold: float = 0.7) -> list[CollinearityGroup]:
        """Union-Find 在 |spearman_rho| > threshold 图上连通分组。"""
        names = list(self._matrix.factor_names)
        n = len(names)
        spearman = self._matrix.spearman_matrix
        if n == 0 or not spearman:
            return []

        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for i in range(n):
            for j in range(i + 1, n):
                if abs(spearman[i][j]) >= threshold:
                    union(i, j)

        # 收集各组
        groups_map: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            groups_map.setdefault(root, []).append(i)

        result: list[CollinearityGroup] = []
        for root, indices in groups_map.items():
            if len(indices) < 2:
                continue
            group_names = [names[i] for i in indices]
            avg_corr = self._compute_avg_correlation(indices, spearman)
            severity = self._classify_severity(avg_corr)
            result.append(CollinearityGroup(
                group_id=uuid.uuid4().hex[:8],
                factor_names=group_names,
                avg_correlation=round(avg_corr, 4),
                severity=severity,
                primary_factor=group_names[0],
                vif_scores={},
                recommendation="",
            ))

        result.sort(key=lambda g: g.avg_correlation, reverse=True)
        return result

    def recommend_dedup(
        self,
        groups: list[CollinearityGroup] | None = None,
        ic_scores: dict[str, float] | None = None,
        current_weights: dict[str, float] | None = None,
        vif_scores: dict[str, float] | None = None,
    ) -> DedupPlan:
        """为每组生成去重建议：保留 IC 最高因子，其余降权。"""
        if groups is None:
            groups = self.detect_groups()

        actions: list[dict] = []
        adjusted = dict(current_weights or {})
        updated_groups: list[CollinearityGroup] = []

        for group in groups:
            # 按 IC 确定主因子
            ic = ic_scores or {}
            ordered = sorted(group.factor_names, key=lambda f: ic.get(f, 0.0), reverse=True)
            primary = ordered[0]
            secondary = ordered[1:]

            # VIF 信息
            group_vif = {}
            if vif_scores:
                group_vif = {f: vif_scores.get(f, 1.0) for f in group.factor_names}

            # 推荐文字
            vif_high = [
                f for f in group.factor_names
                if vif_scores and vif_scores.get(f, 0) > 10.0
            ]
            if vif_high:
                recommendation = (
                    f"保留 {primary}（IC 最高），{', '.join(secondary)} 降权至 0.3 倍。"
                    f" VIF > 10: {', '.join(vif_high)}，建议考虑移除。"
                )
            elif secondary:
                recommendation = (
                    f"保留 {primary}（IC 最高），{', '.join(secondary)} 降权至 0.3 倍。"
                )
            else:
                recommendation = ""

            updated_groups.append(group.model_copy(update={
                "primary_factor": primary,
                "vif_scores": group_vif,
                "recommendation": recommendation,
            }))

            # 主因子操作
            actions.append({
                "factor": primary,
                "action": DedupAction.KEEP_PRIMARY.value,
                "group_id": group.group_id,
            })

            # 次要因子降权
            for f in secondary:
                old_w = adjusted.get(f, 1.0)
                new_w = round(old_w * 0.3, 4)
                adjusted[f] = new_w
                actions.append({
                    "factor": f,
                    "action": DedupAction.DOWNWEIGHT.value,
                    "old_weight": old_w,
                    "new_weight": new_w,
                    "group_id": group.group_id,
                })

        return DedupPlan(
            collinearity_cutoff=0.7,
            groups=updated_groups,
            actions=actions,
            adjusted_weights=adjusted,
        )

    # ── 内部辅助 ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_avg_correlation(indices: list[int], spearman: list[list[float]]) -> float:
        total = 0.0
        count = 0
        for i in indices:
            for j in indices:
                if i < j:
                    total += abs(spearman[i][j])
                    count += 1
        return total / count if count > 0 else 0.0

    @staticmethod
    def _classify_severity(avg_abs_rho: float) -> CollinearitySeverity:
        if avg_abs_rho >= 0.8:
            return CollinearitySeverity.HIGH
        if avg_abs_rho >= 0.6:
            return CollinearitySeverity.MODERATE
        return CollinearitySeverity.LOW
