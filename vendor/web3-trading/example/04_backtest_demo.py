# -*- coding: utf-8 -*-
"""回测框架调试工具 — 录制因子快照 + 运行回测评估。

环境变量:
    VS_OPEN_API_KEY       API Key (ak_...)
    VS_OPEN_SECRET_KEY    Secret Key (sk_...)
    VS_OPEN_API_BASE_URL  Base URL (默认: https://api.valuescan.io/api/open/v1)
    MONGO_DB_TRADING_NAME MongoDB 库名（默认: web3-trading）

用法:
    # 录制单个币种快照
    python example/04_backtest_demo.py record --symbol BTC --market spot

    # 批量录制
    python example/04_backtest_demo.py record --symbol BTC --symbol ETH --market spot

    # 运行回测并输出报告
    python example/04_backtest_demo.py backtest --symbol BTC --lookback 30

    # 回测并导出 Markdown 报告
    python example/04_backtest_demo.py backtest --symbol BTC --lookback 7 --output report.md
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_PATH = _PROJECT_ROOT / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# 加载 .env 环境变量（数据库密码等）
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
# BacktestFormatter — 回测结果可视化
# ═══════════════════════════════════════════════════════════════════════════

class BacktestFormatter:
    """将回测结果渲染为 Rich 终端输出。"""

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    def print_record_result(self, snapshots: list, duration_ms: int) -> None:
        table = Table(title="录制结果")
        table.add_column("代币", style="bright_white")
        table.add_column("快照 ID", style="dim")
        table.add_column("综合得分", justify="right")
        table.add_column("因子数", justify="right")
        table.add_column("错误", justify="right")

        for snap in snapshots:
            score_str = f"[green]{snap.aggregate_score:+.3f}[/]" if snap.aggregate_score > 0 else f"[red]{snap.aggregate_score:+.3f}[/]"
            table.add_row(
                snap.symbol,
                snap.id,
                score_str,
                str(len(snap.factor_results)),
                str(len(snap.errors)),
            )

        self._console.print(table)
        self._console.print(f"  [dim]耗时: {duration_ms}ms  │  快照数: {len(snapshots)}[/]")

    def print_backtest_report(self, report) -> None:
        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("报告 ID", report.id)
        summary.add_row("因子总数", str(len({m.factor_name for m in report.per_factor})))
        summary.add_row("指标总数", str(len(report.per_factor)))
        avg_hr = report.aggregate_summary.get("avg_hit_rate", 0)
        summary.add_row("平均 Hit Rate", f"{avg_hr:.2%}")

        self._console.print(Panel(summary, title="回测报告", border_style="bold"))

        # 因子排名表
        table = Table(title="因子绩效排名（按 IR 降序，Top 20）")
        table.add_column("因子", style="bright_white", width=24)
        table.add_column("类别", width=14)
        table.add_column("周期", width=6)
        table.add_column("IC Mean", justify="right")
        table.add_column("IC Std", justify="right")
        table.add_column("IR", justify="right")
        table.add_column("Hit Rate", justify="right")
        table.add_column("样本", justify="right")

        sorted_metrics = sorted(report.per_factor, key=lambda m: m.ir, reverse=True)[:20]
        for m in sorted_metrics:
            table.add_row(
                m.factor_name,
                m.category or "—",
                m.horizon,
                f"{m.ic_mean:+.4f}",
                f"{m.ic_std:.4f}",
                f"{m.ir:+.4f}",
                f"{m.hit_rate:.2%}",
                str(m.sample_count),
            )

        self._console.print(table)

        # Top 因子
        if report.top_factors_by_ir:
            self._console.print()
            self._console.print(f"  [bold]IR Top 5:[/] {', '.join(report.top_factors_by_ir[:5])}")
            self._console.print(f"  [bold]IC Top 5:[/] {', '.join(report.top_factors_by_ic[:5])}")

        # 分类汇总
        if report.per_category:
            self._console.print()
            cat_table = Table(title="分类别汇总")
            cat_table.add_column("类别")
            cat_table.add_column("因子数", justify="right")
            cat_table.add_column("平均 IC", justify="right")
            cat_table.add_column("平均 IR", justify="right")
            cat_table.add_column("平均 Hit Rate", justify="right")
            for cat in report.per_category:
                cat_table.add_row(
                    cat.get("category", "—"),
                    str(cat.get("factor_count", 0)),
                    f"{cat.get('avg_ic_mean', 0):+.4f}",
                    f"{cat.get('avg_ir', 0):+.4f}",
                    f"{cat.get('avg_hit_rate', 0):.2%}",
                )
            self._console.print(cat_table)


# ═══════════════════════════════════════════════════════════════════════════
# BacktestDemo — 编排器
# ═══════════════════════════════════════════════════════════════════════════

class BacktestDemo:
    """回测编排器 — 连接 DataRecorder / BacktestEngine 与格式化器。"""

    def __init__(
        self,
        symbols: tuple[str, ...],
        market: str,
        action: str,
        lookback_days: int = 30,
        output_path: str = "",
        console: Optional[Console] = None,
    ) -> None:
        self._symbols = list(symbols)
        self._market = market
        self._action = action
        self._lookback_days = lookback_days
        self._output_path = output_path
        self._console = console or Console()
        self._formatter = BacktestFormatter(self._console)
        self._logger = logging.getLogger("backtest.demo")

    async def run(self) -> None:
        self._validate_env()

        # 初始化配置和组件服务（加载 YAML → env 覆盖 → Apollo → init_component）
        from web.config import init_config
        init_config(str(_PROJECT_ROOT / "conf" / "default.yaml"))

        from factors import MarketType, PipelineConfig
        from libs.kucoin_openapi import KuCoinClient
        from libs.valuescan import ValueScanClient

        market_type = MarketType(self._market)
        market_cn = "现货" if market_type == MarketType.SPOT else "合约"
        config = (
            PipelineConfig.for_spot()
            if market_type == MarketType.SPOT
            else PipelineConfig.for_contract()
        )

        self._logger.info("初始化客户端 — %s模式", market_cn)
        client = ValueScanClient.from_env()
        kucoin = KuCoinClient()

        if self._action == "record":
            await self._run_record(client, kucoin, config)
        elif self._action == "backtest":
            await self._run_backtest(kucoin)

    # ------------------------------------------------------------------
    # 录制
    # ------------------------------------------------------------------

    async def _run_record(self, client, kucoin, config) -> None:
        from factors import FactorPipeline
        from factors.backtest import DataRecorder

        import time as _time
        start = _time.monotonic()

        pipeline = FactorPipeline(client, config, kucoin=kucoin)
        recorder = DataRecorder(pipeline, kucoin)

        # 解析 symbol → vs_token_id
        vs_token_ids: dict[str, str] = {}
        for sym in self._symbols:
            vs_id, _coin_key = await client.resolve_symbol(sym)
            if vs_id is None:
                self._console.print(f"  [red]✗ 无法解析代币: {sym}[/]")
                continue
            vs_token_ids[sym] = vs_id
            self._logger.info("代币解析: %s → vs_token_id=%s", sym, vs_id)

        if not vs_token_ids:
            self._console.print("[red]没有可解析的代币[/]")
            return

        self._console.print(f"\n  正在录制: [bold]{', '.join(vs_token_ids.keys())}[/] ...")

        snapshots = await recorder.record_batch(
            list(vs_token_ids.keys()), vs_token_ids
        )

        elapsed_ms = int((_time.monotonic() - start) * 1000)
        self._formatter.print_record_result(snapshots, elapsed_ms)

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------

    async def _run_backtest(self, kucoin) -> None:
        from factors.backtest import BacktestConfig, BacktestEngine

        config = BacktestConfig(
            symbols=self._symbols,
            lookback_days=self._lookback_days,
            min_snapshots=5,
        )

        self._console.print(
            f"\n  回测参数: 币种={self._symbols}  回看={self._lookback_days}天"
        )
        self._console.print("  正在评估 ...")

        engine = BacktestEngine(kucoin)
        report = await engine.run(config)

        self._formatter.print_backtest_report(report)

        if self._output_path:
            markdown = engine._reporter.generate(report)
            with open(self._output_path, "w", encoding="utf-8") as f:
                f.write(markdown)
            self._console.print(f"\n  [green]报告已导出:[/] {self._output_path}")

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def _validate_env(self) -> None:
        missing = [k for k in ("VS_OPEN_API_KEY", "VS_OPEN_SECRET_KEY") if not os.environ.get(k)]
        if missing:
            self._console.print(f"[red]错误: 缺少环境变量 {', '.join(missing)}[/]")
            self._console.print("  export VS_OPEN_API_KEY='ak_...'")
            self._console.print("  export VS_OPEN_SECRET_KEY='sk_...'")
            self._console.print("  export VS_OPEN_API_BASE_URL='https://api.valuescan.io/api/open/v1'")
            sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

@click.group()
def cli() -> None:
    """回测框架调试工具 — 录制因子快照 / 运行回测评估。"""


@cli.command()
@click.option(
    "--symbol", "-s", multiple=True, required=True,
    help="代币符号，如 BTC。可重复指定多个（-s BTC -s ETH）。",
)
@click.option(
    "--market", default="spot", type=click.Choice(["spot", "contract"]),
    help="市场类型：spot=现货, contract=合约",
)
def record(symbol: tuple[str, ...], market: str) -> None:
    """运行 DataRecorder，录制因子快照到本地 JSONL。"""
    demo = BacktestDemo(symbols=symbol, market=market, action="record")
    asyncio.run(demo.run())


@cli.command()
@click.option(
    "--symbol", "-s", "symbols", multiple=True, required=True,
    help="代币符号，如 BTC。可重复指定多个。",
)
@click.option(
    "--lookback", default=30, type=int,
    help="回看天数（默认 30）。",
)
@click.option(
    "--output", "-o", "output_path", default="",
    help="导出 Markdown 报告文件路径。",
)
def backtest(symbols: tuple[str, ...], lookback: int, output_path: str) -> None:
    """运行 BacktestEngine，产出回测评估报告。"""
    demo = BacktestDemo(
        symbols=symbols,
        market="spot",
        action="backtest",
        lookback_days=lookback,
        output_path=output_path,
    )
    asyncio.run(demo.run())


if __name__ == "__main__":
    cli()

# example/04_backtest_demo.py record -s BTC --market spot
# example/04_backtest_demo.py backtest -s BTC --lookback 30