# -*- coding: utf-8 -*-
"""因子置信度校准工具 — 从回测报告提取 Hit Rate，校准后存入 Redis + 本地文件。

环境变量:
    MONGO_DB_TRADING_NAME  MongoDB 库名（默认: web3-trading）

用法:
    # 从已有回测报告校准
    python example/05_calibrate_demo.py calibrate --report-id <uuid>

    # 查看当前 Redis 校准状态
    python example/05_calibrate_demo.py status
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_PATH = _PROJECT_ROOT / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

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
# CalibrationFormatter — 校准结果可视化
# ═══════════════════════════════════════════════════════════════════════════

class CalibrationFormatter:
    """将校准结果渲染为 Rich 终端输出。"""

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    def print_calibration_result(self, record) -> None:
        """打印校准记录摘要。"""
        calibrated = [c for c in record.calibrations if not c.cold_start]
        cold = [c for c in record.calibrations if c.cold_start]

        self._console.print(f"\n  [bold]报告 ID:[/] {record.backtest_report_id}")
        self._console.print(f"  [bold]市场类型:[/] {record.market_type}")
        self._console.print(f"  [bold]已校准:[/] [green]{len(calibrated)}[/] 个因子")
        self._console.print(f"  [bold]冷启动（跳过）:[/] [yellow]{len(cold)}[/] 个因子")

        if calibrated:
            table = Table(title="校准结果（按校准后置信度降序）")
            table.add_column("因子", style="bright_white", width=24)
            table.add_column("样本数", justify="right")
            table.add_column("原始 Hit Rate", justify="right")
            table.add_column("校准置信度", justify="right")
            table.add_column("变化", justify="right")

            sorted_cals = sorted(calibrated, key=lambda c: c.calibrated_confidence, reverse=True)
            for c in sorted_cals:
                diff = c.calibrated_confidence - c.raw_hit_rate
                diff_str = f"[green]+{diff:+.4f}[/]" if diff >= 0 else f"[red]{diff:+.4f}[/]"
                table.add_row(
                    c.factor_name,
                    str(c.sample_count),
                    f"{c.raw_hit_rate:.4f}",
                    f"[bold]{c.calibrated_confidence:.4f}[/]",
                    diff_str,
                )

            self._console.print()
            self._console.print(table)

        if cold:
            self._console.print()
            self._console.print("  [yellow]冷启动因子（样本 < 阈值，未回写 Redis）:[/]")
            for c in cold:
                self._console.print(f"    - {c.factor_name} (样本 {c.sample_count})")

    def print_status(self, status_map: dict[str, float]) -> None:
        """打印 Redis 中当前校准状态。"""
        if not status_map:
            self._console.print("\n  [yellow]Redis 中暂无校准数据[/]")
            return

        table = Table(title=f"Redis 校准状态（{len(status_map)} 个因子）")
        table.add_column("因子", style="bright_white", width=28)
        table.add_column("校准置信度", justify="right")

        for name in sorted(status_map):
            conf = status_map[name]
            color = "green" if conf >= 0.60 else ("yellow" if conf >= 0.40 else "red")
            table.add_row(name, f"[{color}]{conf:.4f}[/]")

        self._console.print()
        self._console.print(table)


# ═══════════════════════════════════════════════════════════════════════════
# CalibrationDemo — 编排器
# ═══════════════════════════════════════════════════════════════════════════

class CalibrationDemo:
    """校准编排器 — 连接回测报告 / ConfidenceCalibrator 与格式化器。"""

    def __init__(
        self,
        action: str,
        report_id: str = "",
        console: Optional[Console] = None,
    ) -> None:
        self._action = action
        self._report_id = report_id
        self._console = console or Console()
        self._formatter = CalibrationFormatter(self._console)
        self._logger = logging.getLogger("calibration.demo")

    async def run(self) -> None:
        from web.config import init_config
        init_config(str(_PROJECT_ROOT / "conf" / "default.yaml"))

        if self._action == "calibrate":
            await self._run_calibrate()
        elif self._action == "status":
            await self._run_status()

    async def _run_calibrate(self) -> None:
        from factors import ConfidenceCalibrator
        from factors.backtest.models import BacktestReport
        from factors.local_store import load_backtest_report
        from web.component import component
        from dao.cache.redis import RedisCache

        doc = await load_backtest_report(self._report_id)
        if not doc:
            self._console.print(f"\n  [red]未找到回测报告: {self._report_id}[/]")
            return
        report = BacktestReport(**doc)

        redis_client = component.get('redis').client
        cache = RedisCache(redis_client, prefix='confidence')
        calibrator = ConfidenceCalibrator(redis_cache=cache)

        self._logger.info("开始校准 — 报告 %s", self._report_id)
        record = await calibrator.calibrate_from_report(report)
        self._formatter.print_calibration_result(record)

    async def _run_status(self) -> None:
        from factors import ConfidenceCalibrator
        from web.component import component

        redis_client = component.get('redis').client
        status_map = await ConfidenceCalibrator.load_from_redis(redis_client)
        self._formatter.print_status(status_map)


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

@click.group()
def cli() -> None:
    """因子置信度校准工具 — 从回测报告校准 / 查看状态。"""


@cli.command()
@click.option("--report-id", required=True, help="回测报告 ID。")
def calibrate(report_id: str) -> None:
    """从已有回测报告执行置信度校准。"""
    demo = CalibrationDemo(action="calibrate", report_id=report_id)
    asyncio.run(demo.run())


@cli.command()
def status() -> None:
    """查看 Redis 中当前的校准状态。"""
    demo = CalibrationDemo(action="status")
    asyncio.run(demo.run())


if __name__ == "__main__":
    cli()

# python example/05_calibrate_demo.py calibrate --report-id <uuid>
# python example/05_calibrate_demo.py status
