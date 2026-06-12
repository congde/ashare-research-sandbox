# -*- coding: utf-8 -*-
"""报告生成器 — 将 BacktestReport 转为可读的 Markdown 文本。"""

from factors.backtest.models import BacktestReport


class Reporter:
    """生成 Markdown 格式的回测报告。"""

    def generate(self, report: BacktestReport) -> str:
        lines: list[str] = []
        lines.append("# 因子回测报告")
        lines.append("")
        lines.append(f"**报告 ID**: `{report.id}`")
        lines.append(f"**生成时间**: {report.created_at_ms}")
        lines.append("")

        if not report.per_factor:
            lines.append("暂无因子数据。")
            return "\n".join(lines)

        self._render_factor_table(lines, report)

        if report.per_category:
            lines.append("")
            self._render_category_table(lines, report)

        if report.top_factors_by_ir:
            lines.append("")
            lines.append("## Top 因子")
            lines.append("")
            lines.append(f"**IR 排名**: {', '.join(report.top_factors_by_ir[:5])}")
            lines.append(f"**IC 排名**: {', '.join(report.top_factors_by_ic[:5])}")

        return "\n".join(lines)

    def _render_factor_table(self, lines: list[str], report: BacktestReport) -> None:
        lines.append("## 因子绩效排名（按 IR 降序）")
        lines.append("")
        lines.append("| 排名 | 因子 | 类别 | 周期 | IC Mean | IC Std | IR | Hit Rate | 样本数 |")
        lines.append("|------|------|------|------|---------|--------|----|----------|--------|")
        sorted_metrics = sorted(report.per_factor, key=lambda m: m.ir, reverse=True)
        for i, m in enumerate(sorted_metrics, 1):
            lines.append(
                f"| {i} | {m.factor_name} | {m.category} | {m.horizon} "
                f"| {m.ic_mean:.4f} | {m.ic_std:.4f} | {m.ir:.4f} "
                f"| {m.hit_rate:.2%} | {m.sample_count} |"
            )

    def _render_category_table(self, lines: list[str], report: BacktestReport) -> None:
        lines.append("## 分类别汇总")
        lines.append("")
        lines.append("| 类别 | 因子数 | 平均 IC | 平均 IR | 平均 Hit Rate |")
        lines.append("|------|--------|---------|---------|---------------|")
        for cat in report.per_category:
            lines.append(
                f"| {cat.get('category', '')} | {cat.get('factor_count', 0)} "
                f"| {cat.get('avg_ic_mean', 0):.4f} | {cat.get('avg_ir', 0):.4f} "
                f"| {cat.get('avg_hit_rate', 0):.2%} |"
            )
