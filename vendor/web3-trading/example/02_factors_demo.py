# -*- coding: utf-8 -*-
"""因子调试工具 — 支持全量/单因子两种模式，可导出 JSON。

环境变量:
    VS_OPEN_API_KEY       API Key (ak_...)
    VS_OPEN_SECRET_KEY    Secret Key (sk_...)
    VS_OPEN_API_BASE_URL  Base URL (默认: https://api.valuescan.io/api/open/v1)

用法:
    # 全部因子（表格输出）
    python example/02_factors_demo.py --market spot --symbol BTC

    # 单因子深度调试（展示完整 DecisionTrace）
    python example/02_factors_demo.py --factor spot_trade_inflow --symbol BTC

    # 合约模式
    python example/02_factors_demo.py --market contract --symbol ETH

    # 导出 JSON
    python example/02_factors_demo.py --market spot --symbol BTC --json result.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import ClassVar, Dict, Optional

import click
from rich.box import SIMPLE_HEAVY
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
if _ENV_PATH.exists():
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ═══════════════════════════════════════════════════════════════════════════
# FactorFormatter — 因子结果可视化
# ═══════════════════════════════════════════════════════════════════════════

class FactorFormatter:
    """将 FactorResult / FactorBundle 渲染为 Rich 终端输出。"""

    DIR_ICON: ClassVar[Dict[str, str]] = {
        "strong_bullish": "🟢🟢",
        "bullish": "🟢  ",
        "neutral_bullish": "🟡↑ ",
        "neutral": "⚪  ",
        "neutral_bearish": "🟡↓ ",
        "bearish": "🔴  ",
        "strong_bearish": "🔴🔴",
        "inconclusive": "❓  ",
    }

    DIR_CN: ClassVar[Dict[str, str]] = {
        "strong_bullish": "强多",
        "bullish": "看多",
        "neutral_bullish": "偏多",
        "neutral": "中性",
        "neutral_bearish": "偏空",
        "bearish": "看空",
        "strong_bearish": "强空",
        "inconclusive": "无结论",
    }

    STATE_CN: ClassVar[Dict[str, str]] = {
        "trending_up": "上升趋势",
        "trending_down": "下降趋势",
        "ranging": "横盘震荡",
        "high_vol": "高波动",
        "low_vol": "低波动",
    }

    STATE_ICON: ClassVar[Dict[str, str]] = {
        "trending_up": "🟢",
        "trending_down": "🔴",
        "ranging": "⚪",
        "high_vol": "🟡",
        "low_vol": "🔵",
    }

    TIER_LABELS: ClassVar[list] = [
        ("T1 核心资金流向", "tier_1"),
        ("T2 链上筹码结构", "tier_2"),
        ("T3 市场心理", "tier_3"),
        ("T4 辅助因子", "tier_4"),
        ("T5 实验因子", "tier_5"),
    ]

    TIER_KEY_MAP: ClassVar[Dict[str, str]] = {
        "tier_1": "tier1_results",
        "tier_2": "tier2_results",
        "tier_3": "tier3_results",
        "tier_4": "tier4_results",
        "tier_5": "tier5_results",
    }

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def print_single(self, result) -> None:
        """输出单个 FactorResult 及完整 DecisionTrace。"""
        trace = result.trace

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("因子", f"{result.display_name} ({result.factor_name})")
        header.add_row("层级", f"{result.factor_tier.value}    分类: {result.category.value}")
        header.add_row("方向", self._dir_label(result.signal_direction.value))
        header.add_row(
            "得分",
            f"[{self._score_style(result.normalized_score)}]{result.normalized_score:+.4f}[/]"
            f"    置信度: {result.confidence:.0%}",
        )
        header.add_row("原始值", f"{result.raw_value}    完整度: {result.data_completeness:.0%}")
        self._console.print(Panel(header, title=result.factor_name, border_style="bold"))

        if trace.conclusion:
            self._console.print(Panel(trace.conclusion, title="结论", border_style="cyan"))
        if trace.suggested_action:
            self._console.print(Panel(trace.suggested_action, title="建议操作", border_style="green"))
        if trace.counter_argument:
            self._console.print(Panel(trace.counter_argument, title="反向论点", border_style="yellow"))
        if trace.evidence_chain:
            self._print_evidence_chain(trace)
        if trace.limitations:
            limits = "\n".join(f"• {lim}" for lim in trace.limitations)
            self._console.print(Panel(limits, title="局限性", border_style="dim"))

    def print_bundle(self, bundle, factor_info: dict | None = None) -> None:
        """输出 FactorBundle 中所有因子的分层表格。"""
        self._print_bundle_header(bundle)

        for label, tier_key in self.TIER_LABELS:
            attr = self.TIER_KEY_MAP[tier_key]
            results = getattr(bundle, attr)
            if not results:
                continue
            sorted_results = sorted(results, key=lambda r: abs(r.normalized_score), reverse=True)
            self._print_tier_table(label, sorted_results, factor_info)

        if bundle.cross_factors:
            self._print_cross_table(bundle.cross_factors)

        if bundle.errors:
            self._console.print()
            for err in bundle.errors:
                self._console.print(f"  [red]✗[/] {err}")

    def print_data_status(self, ctx) -> None:
        """输出原始数据可用性一览。"""
        table = Table(title="原始数据可用性", box=SIMPLE_HEAVY)
        table.add_column("数据源", width=22)
        table.add_column("状态", width=8)
        table.add_column("详情")

        ok = fail = 0
        for key in sorted(ctx.data.keys()):
            val = ctx.data[key]
            if val is None:
                table.add_row(key, "[red]✗ 缺失[/]", "—")
                fail += 1
            elif isinstance(val, list):
                table.add_row(key, "[green]✓ 可用[/]", f"{len(val)} 条记录")
                ok += 1
            else:
                table.add_row(key, "[green]✓ 可用[/]", type(val).__name__)
                ok += 1

        self._console.print(table)
        self._console.print(
            f"  [dim]可用 {ok}/{ok+fail}  │  "
            f"has_spot={ctx.has_spot}  has_contract={ctx.has_contract}  "
            f"price={ctx.current_price}[/]"
        )

    def print_market_state(self, state_result) -> None:
        """输出市场状态检测结果。"""
        icon = self.STATE_ICON.get(state_result.state.value, "❓")
        cn = self.STATE_CN.get(state_result.state.value, state_result.state.value)
        table = Table(title="P2 市场状态检测", box=SIMPLE_HEAVY)
        table.add_column("指标", style="bold", width=14)
        table.add_column("数值", width=14)
        table.add_column("说明", width=40)
        table.add_row("市场状态", f"{icon} {cn}", f"置信度 {state_result.confidence:.0%}")
        indicators = state_result.indicators
        table.add_row("ADX", f"{indicators.get('adx', 0):.1f}", ">25=趋势市场, ≤25=震荡")
        table.add_row("ATR分位", f"{indicators.get('atr_pct', 0):.0%}", ">80%=高波动, <20%=低波动")
        table.add_row("EMA偏离", f"{indicators.get('ema_ratio', 1):.3f}", ">1价格高于EMA20, <1价格低于EMA20")
        if state_result.adjacent_states:
            adj = ", ".join(
                f"{self.STATE_ICON.get(s.value,'')} {self.STATE_CN.get(s.value, s.value)}({w:.0%})"
                for s, w in zip(state_result.adjacent_states, state_result.adjacent_weights)
            )
            table.add_row("相邻状态", adj, "用于平滑过渡的相邻市场状态")
        self._console.print(table)

    def print_adaptive_weights(self, base_profile, adaptive_profile, max_items: int = 10) -> None:
        """输出自适应权重变化对比。"""
        table = Table(title="P2 自适应权重变化（Top 变化）", box=SIMPLE_HEAVY)
        table.add_column("因子", width=26)
        table.add_column("默认", justify="right", width=8)
        table.add_column("自适应", justify="right", width=8)
        table.add_column("变化", justify="right", width=8)

        changes = []
        for e in adaptive_profile.factors:
            old_w = base_profile.get_weight(e.factor_name)
            new_w = e.weight
            delta = new_w - old_w
            if abs(delta) > 0.01:
                changes.append((e.factor_name, old_w, new_w, delta))

        changes.sort(key=lambda x: abs(x[3]), reverse=True)
        for name, old, new, delta in changes[:max_items]:
            direction = "[green]+" if delta >= 0 else "[red]"
            table.add_row(name, f"{old:.2f}", f"{new:.2f}", f"{direction}{delta:+.2f}[/]")

        if len(changes) > max_items:
            self._console.print(f"  [dim]… 共 {len(changes)} 个因子权重被调整[/]")
        self._console.print(table)

    def print_collinearity_groups(self, groups, vif_scores: dict) -> None:
        """输出共线性组检测结果。"""
        table = Table(title=f"共线性组（{len(groups)} 组）", box=SIMPLE_HEAVY)
        table.add_column("组", width=6)
        table.add_column("因子", width=56)
        table.add_column("|ρ|均值", justify="right", width=8)
        table.add_column("严重度", width=8)

        severity_style = {"high": "red", "moderate": "yellow", "low": "dim"}
        for g in groups:
            names = ", ".join(g.factor_names)
            sev = g.severity.value
            vif_info = ""
            if vif_scores:
                high_vif = [f for f in g.factor_names if vif_scores.get(f, 0) > 10.0]
                if high_vif:
                    vif_info = f"  [red]VIF>10: {', '.join(high_vif)}[/]"
            table.add_row(
                f"G{g.group_id[:4]}",
                f"{names}{vif_info}",
                f"{g.avg_correlation:.2f}",
                f"[{severity_style.get(sev, 'dim')}]{sev}[/]",
            )
        self._console.print(table)

    def print_correlation_pairs(self, pairs: list) -> None:
        """输出高相关因子对。"""
        table = Table(title=f"高相关因子对（|ρ| > 0.6, {len(pairs)} 对）", box=SIMPLE_HEAVY)
        table.add_column("因子 A", width=24)
        table.add_column("因子 B", width=24)
        table.add_column("Spearman ρ", justify="right", width=12)

        for p in pairs:
            table.add_row(p.factor_a, p.factor_b, f"{p.spearman_rho:+.4f}")
        self._console.print(table)

    def print_vif_warning(self, high_vif: list) -> None:
        """输出 VIF 告警。"""
        table = Table(title="VIF 告警（VIF > 5）", box=SIMPLE_HEAVY)
        table.add_column("因子", width=30)
        table.add_column("VIF", justify="right", width=10)
        table.add_column("风险", width=30)
        for name, vif_val in high_vif:
            level = "[red]严重共线性" if vif_val > 10 else "[yellow]中等共线性"
            table.add_row(name, f"{vif_val:.1f}", level)
        self._console.print(table)

    # ------------------------------------------------------------------
    # 静态工具方法
    # ------------------------------------------------------------------

    @classmethod
    def _dir_label(cls, direction: str) -> str:
        icon = cls.DIR_ICON.get(direction, "❓  ")
        cn = cls.DIR_CN.get(direction, direction)
        return f"{icon} {cn}"

    @staticmethod
    def _fmt_raw(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        if isinstance(value, int):
            return str(value)
        return str(value)[:14]

    @staticmethod
    def _score_style(score: float) -> str:
        if score > 0.15:
            return "green"
        if score > 0.03:
            return "bright_green"
        if score < -0.15:
            return "red"
        if score < -0.03:
            return "bright_red"
        return "dim"

    @staticmethod
    def build_factor_info(registry) -> dict:
        """从 FactorRegistry 构建 factor_name → {file} 的映射。"""
        info: dict = {}
        for computer in registry.get_computers():
            module = computer.__class__.__module__
            # factors.computers.spot.inflow → spot/inflow.py
            parts = module.split(".")
            file_path = "/".join(parts[-2:]) + ".py" if len(parts) >= 2 else module
            info[computer.factor_name] = {"file": file_path}
        return info

    # ------------------------------------------------------------------
    # 内部渲染方法
    # ------------------------------------------------------------------

    def _print_bundle_header(self, bundle) -> None:
        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("代币", f"{bundle.symbol} (vs_token_id={bundle.vs_token_id})")
        summary.add_row(
            "综合评分",
            f"[{self._score_style(bundle.aggregate_score)}]{bundle.aggregate_score:+.4f}[/]"
            f"    完整度: {bundle.overall_completeness:.1%}",
        )
        summary.add_row("统计", f"成功 {len(bundle.all_results)} 个    错误 {len(bundle.errors)} 个")
        self._console.print(Panel(summary, title="因子调试", border_style="bold"))

    def _print_tier_table(self, label: str, results: list, factor_info: dict | None = None) -> None:
        table = Table(title=f"{label} ({len(results)} 个)", box=SIMPLE_HEAVY)
        table.add_column("因子名称", style="bright_white", width=24)
        table.add_column("源文件", style="dim", width=16)
        table.add_column("权重", justify="right", width=6)
        table.add_column("方向", width=10)
        table.add_column("得分", justify="right", width=10)
        table.add_column("置信度", justify="right", width=8)
        table.add_column("原始值", style="dim", width=14)

        for r in results:
            score = r.normalized_score
            raw = self._fmt_raw(r.raw_value)
            meta = (factor_info or {}).get(r.factor_name, {})
            file_path = meta.get("file", "—")
            table.add_row(
                f"{r.display_name} ({r.factor_name})",
                file_path,
                f"{r.weight:.1f}",
                self._dir_label(r.signal_direction.value),
                f"[{self._score_style(score)}]{score:+.4f}[/]",
                f"{r.confidence:.0%}",
                raw,
            )
        self._console.print(table)

    def _print_cross_table(self, cross_factors: list) -> None:
        table = Table(title=f"交叉因子 ({len(cross_factors)})", box=SIMPLE_HEAVY)
        table.add_column("名称", style="bright_white", width=28)
        table.add_column("方向", width=10)
        table.add_column("得分", justify="right", width=10)
        table.add_column("公式", style="dim", width=18)

        for cf in cross_factors:
            score = cf.normalized_score
            table.add_row(
                cf.cross_name,
                self._dir_label(cf.signal_direction.value),
                f"[{self._score_style(score)}]{score:+.4f}[/]",
                cf.formula,
            )
        self._console.print(table)

    def _print_evidence_chain(self, trace) -> None:
        evidence_table = Table(
            title=f"推理链 ({len(trace.evidence_chain)} 步)",
            box=SIMPLE_HEAVY,
            show_lines=True,
        )
        evidence_table.add_column("#", style="dim", width=4)
        evidence_table.add_column("数据", style="bright_white", width=30)
        evidence_table.add_column("解读", width=36)
        evidence_table.add_column("推论", width=36)
        evidence_table.add_column("置信", justify="right", width=6)

        for i, link in enumerate(trace.evidence_chain, 1):
            evidence_table.add_row(
                str(i),
                link.data_point,
                link.interpretation,
                link.implication,
                f"{link.confidence:.0%}",
            )
        self._console.print(evidence_table)


# ═══════════════════════════════════════════════════════════════════════════
# FactorExporter — JSON 导出
# ═══════════════════════════════════════════════════════════════════════════

class FactorExporter:
    """将 FactorBundle 导出为 JSON 文件。"""

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    def export(self, bundle, path: str) -> None:
        data = {
            "vs_token_id": bundle.vs_token_id,
            "symbol": bundle.symbol,
            "aggregate_score": bundle.aggregate_score,
            "overall_completeness": bundle.overall_completeness,
            "errors": bundle.errors,
            "factors": self._serialize_factors(bundle),
            "cross_factors": self._serialize_cross(bundle),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._console.print(f"\n  [green]已导出:[/] {path}")

    @staticmethod
    def _serialize_factors(bundle) -> list:
        items: list = []
        for r in bundle.all_results:
            items.append({
                "name": r.factor_name,
                "display_name": r.display_name,
                "tier": r.factor_tier.value,
                "category": r.category.value,
                "signal": r.signal_direction.value,
                "score": r.normalized_score,
                "confidence": r.confidence,
                "raw_value": r.raw_value,
                "weight": r.weight,
                "trace": {
                    "conclusion": r.trace.conclusion,
                    "suggested_action": r.trace.suggested_action,
                    "counter_argument": r.trace.counter_argument,
                    "evidence": [
                        {
                            "data": e.data_point,
                            "interpretation": e.interpretation,
                            "implication": e.implication,
                            "confidence": e.confidence,
                        }
                        for e in r.trace.evidence_chain
                    ],
                    "limitations": r.trace.limitations,
                },
            })
        return items

    @staticmethod
    def _serialize_cross(bundle) -> list:
        items: list = []
        for cf in bundle.cross_factors:
            items.append({
                "name": cf.cross_name,
                "parents": cf.parent_factors,
                "formula": cf.formula,
                "signal": cf.signal_direction.value,
                "score": cf.normalized_score,
                "confidence": cf.confidence,
            })
        return items


# ═══════════════════════════════════════════════════════════════════════════
# FactorDemo — 编排器
# ═══════════════════════════════════════════════════════════════════════════

class FactorDemo:
    """因子调试编排器 — 连接管线、格式化器和导出器。"""

    def __init__(
        self,
        market: str,
        symbol: str,
        factor_name: str = "",
        json_path: str = "",
        verbose: bool = False,
        adaptive: bool = False,
        collinearity: bool = False,
        console: Optional[Console] = None,
    ) -> None:
        self._market = market
        self._symbol = symbol
        self._factor_name = factor_name
        self._json_path = json_path
        self._verbose = verbose
        self._adaptive = adaptive
        self._collinearity = collinearity
        self._console = console or Console()
        self._formatter = FactorFormatter(self._console)
        self._exporter = FactorExporter(self._console)
        self._logger = logging.getLogger("factors.demo")

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.getLogger("factors").setLevel(logging.DEBUG)
        else:
            logging.getLogger("factors").setLevel(logging.INFO)

    async def run(self) -> None:
        self._validate_env()

        # 初始化配置和组件服务（加载 YAML → env 覆盖 → Apollo → init_component）
        from web.config import init_config

        init_config(str(_PROJECT_ROOT / "conf" / "default.yaml"))

        from factors import FactorPipeline, MarketType, PipelineConfig
        from libs.kucoin_openapi import KuCoinClient
        from libs.valuescan import ValueScanClient

        market_type = MarketType(self._market)
        market_cn = "现货" if market_type == MarketType.SPOT else "合约"
        config = (
            PipelineConfig.for_spot()
            if market_type == MarketType.SPOT
            else PipelineConfig.for_contract()
        )
        if self._adaptive:
            config = config.model_copy(update={"adaptive_weighting_enabled": True})

        self._logger.info("启动因子调试 — %s模式 — %s", market_cn, self._symbol)
        if self._adaptive:
            self._logger.info("市场状态自适应权重已启用")
        self._console.print()
        self._console.rule(f"[bold]因子调试 — {market_cn}模式 — {self._symbol}[/]")

        self._logger.info("初始化 ValueScan / KuCoin 客户端及因子管线 (profile=%s)", config.ranking_profile.profile_id)
        client = ValueScanClient.from_env()
        kucoin = KuCoinClient()
        pipeline = FactorPipeline(client, config, kucoin=kucoin)

        # 解析 vs_token_id（DataRecorder 录制需要）
        vs_token_id, _coin_key = await client.resolve_symbol(self._symbol)
        if vs_token_id is None:
            self._console.print(f"[red]无法解析代币: {self._symbol}[/]")
            sys.exit(1)

        from factors.backtest import DataRecorder

        recorder = DataRecorder(pipeline, kucoin)

        if self._factor_name:
            await self._run_single(pipeline, recorder, vs_token_id)
        else:
            await self._run_all(pipeline, recorder, vs_token_id)

        # P2 共线性检测（需要历史快照数据，在因子计算完成后执行）
        if self._collinearity:
            await self._p2_collinearity(pipeline)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _validate_env(self) -> None:
        missing = [k for k in ("VS_OPEN_API_KEY", "VS_OPEN_SECRET_KEY") if not os.environ.get(k)]
        if missing:
            self._console.print(f"[red]错误: 缺少环境变量 {', '.join(missing)}[/]")
            self._console.print("  export VS_OPEN_API_KEY='ak_...'")
            self._console.print("  export VS_OPEN_SECRET_KEY='sk_...'")
            self._console.print("  export VS_OPEN_API_BASE_URL='https://api.valuescan.io/api/open/v1'")
            sys.exit(1)

    async def _p2_collinearity(self, pipeline) -> None:
        """P2 因子间共线性检测 — 从本地历史快照构建相关矩阵。"""
        self._console.print()
        self._console.rule("[bold]P2 因子间共线性检测[/]")

        try:
            from factors.analysis.collinearity import CollinearityDetector
            from factors.analysis.correlation import SignalCorrelationAnalyzer
            from factors.backtest import Simulator
            from factors.backtest.config import BacktestConfig

            sim = Simulator()
            btc_config = BacktestConfig(symbols=[self._symbol], lookback_days=30)
            timepoints = await sim.replay(btc_config)

            if len(timepoints) < 5:
                self._console.print("  [yellow]历史快照不足（需≥5条），请先积累数据[/]")
                return

            self._console.print(f"  [dim]已加载 {len(timepoints)} 条历史快照[/]")

            analyzer = SignalCorrelationAnalyzer(timepoints)
            corr_matrix = analyzer.build_matrix(threshold=0.6)
            vif_scores = analyzer.compute_vif()

            # 共线性组
            detector = CollinearityDetector(corr_matrix)
            groups = detector.detect_groups(threshold=0.6)
            if groups:
                self._formatter.print_collinearity_groups(groups, vif_scores)
            else:
                self._console.print("  [green]未检测到显著共线性组（|ρ| > 0.6）[/]")

            # 高相关对
            pairs = corr_matrix.high_correlation_pairs
            if pairs:
                self._formatter.print_correlation_pairs(pairs[:15])

            # VIF 最高
            high_vif = sorted(
                [(k, v) for k, v in vif_scores.items() if v > 5.0],
                key=lambda x: x[1], reverse=True,
            )[:5]
            if high_vif:
                self._formatter.print_vif_warning(high_vif)

        except Exception:
            self._logger.warning("P2 共线性检测失败", exc_info=True)

    async def _p2_analysis(self, pipeline, profile) -> None:
        """P2 市场状态检测 + 自适应权重展示。"""
        try:
            ctx = await pipeline._fetch_context(self._symbol)
            kline = ctx.data.get("kline") if ctx else None
            if not kline or kline.is_empty:
                self._console.print("  [dim]P2: K线数据不可用[/]")
                return
            from factors.analysis.market_state import MarketStateDetector
            from factors.analysis.adaptive_selector import AdaptiveProfileSelector, ProfileComposer
            state_result = MarketStateDetector.detect(kline)
            self._formatter.print_market_state(state_result)

            selector = AdaptiveProfileSelector(profile)
            state_profiles = selector.get_all_relevant_profiles(state_result)
            adaptive_profile = ProfileComposer.compose(profile, state_result, state_profiles)
            self._formatter.print_adaptive_weights(profile, adaptive_profile)
            self._console.print()
        except Exception:
            self._logger.warning("P2 市场状态检测失败，继续计算因子", exc_info=True)

    async def _run_single(self, pipeline, recorder, vs_token_id: str) -> None:
        self._logger.info("计算单因子: %s（录制完整快照）", self._factor_name)
        self._console.print(f"\n  正在录制快照并计算: [bold]{self._factor_name}[/] ...")

        if self._adaptive:
            await self._p2_analysis(pipeline, pipeline.config.ranking_profile)

        snap = await recorder.record_snapshot(self._symbol, vs_token_id)

        # 从快照中提取目标因子
        result = None
        for r_dict in snap.factor_results:
            if r_dict.get("factor_name") == self._factor_name:
                from factors.models import FactorResult
                result = FactorResult(**r_dict)
                break

        if result is None:
            self._logger.warning("因子 %s 不在计算结果中", self._factor_name)
            self._console.print(f"\n  [red]因子 {self._factor_name} 不在计算结果中[/]")
            sys.exit(1)
        self._logger.info("因子 %s 计算完成 (score=%+.3f, direction=%s)",
                          result.factor_name, result.normalized_score, result.signal_direction.value)

        self._formatter.print_single(result)
        self._console.print(f"  [dim]快照已入库: factor_snapshots.id={snap.id}  "
                           f"quality_report_id={snap.quality_report_id}  "
                           f"source_data_id={snap.source_data_id}[/]")

    async def _run_all(self, pipeline, recorder, vs_token_id: str) -> None:
        self._logger.info("开始全量因子计算 (profile=%s)", pipeline.config.ranking_profile.profile_id)
        self._console.print("\n  正在录制快照并计算所有因子 ...")

        if self._adaptive:
            await self._p2_analysis(pipeline, pipeline.config.ranking_profile)

        snap = await recorder.record_snapshot(self._symbol, vs_token_id)

        # 从快照反序列化 FactorResult 列表（用于显示）
        from factors.models import FactorResult
        results = [FactorResult(**r) for r in snap.factor_results]

        active_count = len(results)
        error_count = len(snap.errors)
        self._logger.info(
            "因子计算完成: 成功=%d 失败=%d 完整度=%.1f%% 综合评分=%+.4f",
            active_count, error_count, snap.overall_completeness * 100, snap.aggregate_score,
        )

        # 构建临时 bundle（用于 formatter 显示）
        from factors.models import FactorBundle
        bundle = FactorBundle(
            quality_report_id=snap.quality_report_id,
            vs_token_id=snap.vs_token_id,
            symbol=snap.symbol,
            computed_at_ms=snap.computed_at_ms,
            overall_completeness=snap.overall_completeness,
            errors=snap.errors,
            tier1_results=[r for r in results if r.factor_tier.value == "tier_1"],
            tier2_results=[r for r in results if r.factor_tier.value == "tier_2"],
            tier3_results=[r for r in results if r.factor_tier.value == "tier_3"],
            tier4_results=[r for r in results if r.factor_tier.value == "tier_4"],
            tier5_results=[r for r in results if r.factor_tier.value == "tier_5"],
        )

        factor_info = self._formatter.build_factor_info(pipeline.registry)
        self._formatter.print_bundle(bundle, factor_info)

        self._console.print(f"  [dim]快照已入库: factor_snapshots.id={snap.id}  "
                           f"quality_report_id={snap.quality_report_id}  "
                           f"source_data_id={snap.source_data_id}[/]")

        if self._json_path:
            self._logger.info("导出 JSON: %s", self._json_path)
            self._exporter.export(bundle, self._json_path)


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

@click.command()
@click.option(
    "--market", default="spot", type=click.Choice(["spot", "contract"]),
    help="市场类型：spot=现货, contract=合约",
)
@click.option("--symbol", default="BTC", help="代币符号，如 BTC、ETH")
@click.option(
    "--factor", "factor_name", default="",
    help="单个因子名称，不指定则计算全部因子",
)
@click.option("--json", "json_path", default="", help="导出 JSON 文件路径")
@click.option("--verbose", "-v", is_flag=True, help="启用 DEBUG 级别日志，输出管线内部细节")
@click.option("--adaptive", is_flag=True, help="启用 P2 市场状态检测与自适应权重分析")
@click.option("--collinearity", is_flag=True, help="启用 P2 因子间共线性检测（需历史快照数据）")
def main(market: str, symbol: str, factor_name: str, json_path: str, verbose: bool, adaptive: bool, collinearity: bool) -> None:
    """因子调试工具 — 支持全量/单因子两种模式，可导出 JSON。"""
    demo = FactorDemo(
        market=market,
        symbol=symbol,
        factor_name=factor_name,
        json_path=json_path,
        verbose=verbose,
        adaptive=adaptive,
        collinearity=collinearity,
    )
    asyncio.run(demo.run())


if __name__ == "__main__":
    main()
