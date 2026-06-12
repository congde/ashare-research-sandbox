# -*- coding: utf-8 -*-
"""ValueScan API 调试工具 — 支持全量/分组/单接口三种模式。

环境变量:
    VS_OPEN_API_KEY       API Key (ak_...)
    VS_OPEN_SECRET_KEY    Secret Key (sk_...)
    VS_OPEN_API_BASE_URL  Base URL (默认: https://api.valuescan.io/api/open/v1)

用法:
    # 全部接口，分组展示
    python example/01_valuescan.py

    # 只执行某一分组
    python example/01_valuescan.py --group 2

    # 只执行单个接口（最常用调试模式）
    python example/01_valuescan.py --method get_realtime_fund --symbol ETH

    # 指定代币
    python example/01_valuescan.py --symbol BTC

    # 查看所有可用方法和分组
    python example/01_valuescan.py --list
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import click
from rich.console import Console
from rich.rule import Rule

_SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ═══════════════════════════════════════════════════════════════════════════
# MethodRegistry — ValueScan 接口定义与分组
# ═══════════════════════════════════════════════════════════════════════════

class MethodRegistry:
    """ValueScan API 方法注册表，声明式定义每个接口的元数据。"""

    GROUP_LABELS: ClassVar[Dict[int, str]] = {
        1: "代币解析",
        2: "交易所资金监控",
        3: "主力成本",
        4: "链上大额 / 持仓",
        5: "市场指标",
        6: "AI 信号",
    }

    def __init__(self, client, vs_id: int, symbol: str) -> None:
        self._client = client
        self._vs_id = vs_id
        self._symbol = symbol
        self._methods: List[Dict[str, Any]] = self._build()

    # ------------------------------------------------------------------
    # 公开查询方法
    # ------------------------------------------------------------------

    @property
    def all(self) -> List[Dict[str, Any]]:
        return self._methods

    def by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for m in self._methods:
            if m["name"] == name:
                return m
        return None

    def by_group(self, group: int) -> List[Dict[str, Any]]:
        return [m for m in self._methods if m["group"] == group]

    def group_names(self) -> Dict[int, str]:
        return dict(self.GROUP_LABELS)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build(self) -> List[Dict[str, Any]]:
        c = self._client
        vs_id = self._vs_id
        symbol = self._symbol
        return [
            # Group 1: Token resolution
            _m("search_token",       "搜索代币",        1, lambda: c.search_token(symbol)),
            _m("get_token_by_symbol","按符号获取代币",   1, lambda: c.get_token_by_symbol(symbol)),
            _m("get_vs_token_id",    "获取 vs_token_id", 1, lambda: c.get_vs_token_id(symbol)),
            _m("get_token_detail",   "代币详情",         1, lambda: c.get_token_detail(vs_id)),
            _m("get_coin_key",       "Coin Key",         1, lambda: c.get_coin_key(vs_id)),
            _m("resolve_symbol",     "解析符号",         1, lambda: c.resolve_symbol(symbol)),

            # Group 2: Exchange fund monitoring
            _m("get_token_flow",         "代币资金流向",    2, lambda: c.get_token_flow(vs_id)),
            _m("get_realtime_fund",      "实时资金数据",    2, lambda: c.get_realtime_fund(vs_id)),
            _m("get_fund_snapshot",      "资金快照",        2, lambda: c.get_fund_snapshot(vs_id)),
            _m("get_fund_market_cap_ratio","资金市值比",     2, lambda: c.get_fund_market_cap_ratio(vs_id)),
            _m("get_sector_fund_list",   "板块资金列表",    2, lambda: c.get_sector_fund_list(1)),
            _m("get_kline",              "K线数据",         2, lambda: c.get_kline(vs_id, bucket_type="1h", days=1)),

            # Group 3: Whale cost
            _m("get_whale_cost", "主力成本", 3, lambda: c.get_whale_cost(vs_id, days=7)),

            # Group 4: On-chain large tx / holders
            _m("get_large_transactions", "大额转账", 4, lambda: c.get_large_transactions(vs_id, page=1, page_size=5)),
            _m("get_holder_list",        "持仓地址", 4, lambda: c.get_holder_list(vs_id, page=1, page_size=5)),

            # Group 5: Market indicators
            _m("get_price_indicators",  "价格指标", 5, lambda: c.get_price_indicators(vs_id, days=7)),
            _m("get_support_resistance","支撑阻力", 5, lambda: c.get_support_resistance(vs_id, days=7)),
            _m("get_social_sentiment",  "社媒情绪", 5, lambda: c.get_social_sentiment(vs_id)),

            # Group 6: AI signals
            _m("get_chance_coin_list",  "机会代币列表", 6, lambda: c.get_chance_coin_list()),
            _m("get_risk_coin_list",    "风险代币列表", 6, lambda: c.get_risk_coin_list()),
            _m("get_funds_coin_list",   "资金代币列表", 6, lambda: c.get_funds_coin_list()),
            _m("get_ai_messages:chance","AI 机会消息",  6, lambda: c.get_ai_messages(vs_id, msg_type="chance")),
            _m("get_ai_messages:risk",  "AI 风险消息",  6, lambda: c.get_ai_messages(vs_id, msg_type="risk")),
        ]


def _m(name: str, label: str, group: int, factory) -> Dict[str, Any]:
    """快捷工厂：创建单个方法注册项。"""
    return {"name": name, "label": label, "group": group, "factory": factory}


# ═══════════════════════════════════════════════════════════════════════════
# ValueScanFormatter — API 响应可视化
# ═══════════════════════════════════════════════════════════════════════════

class ValueScanFormatter:
    """将 ValueScan API 响应渲染为 Rich 终端输出。"""

    _MAX_STRING_LEN = 80
    _MAX_LIST_ITEMS = 8

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def print_method_list(self, registry: MethodRegistry) -> None:
        """列出所有可用方法及其分组。"""
        for group, label in registry.group_names().items():
            methods = registry.by_group(group)
            self._console.print(f"\n[bold]Group {group} — {label}[/]")
            for m in methods:
                self._console.print(f"  [cyan]{m['name']:<36}[/] {m['label']}")

    def print_result(self, name: str, label: str, elapsed: float, result: Any = None, error: Optional[Exception] = None) -> None:
        """输出单个接口调用结果。"""
        status = "❌" if error else "✅"
        self._console.print(f"\n── {label} ([cyan]{name}[/])  {status} {elapsed:.2f}s ──")
        if error:
            self._console.print(f"   [red]{type(error).__name__}: {error}[/]")
        elif result is not None:
            self._inspect(result)
        else:
            self._console.print("   (空响应)")

    def print_summary(self, ok: int, fail: int, total: int) -> None:
        """输出执行汇总。"""
        self._console.print()
        self._console.print(Rule(style="dim"))
        self._console.print(
            f"  结果: [green]{ok} 成功[/], "
            f"[red]{fail} 失败[/], "
            f"{total} 总计"
        )
        self._console.print(Rule(style="dim"))

    def print_header(self, label: str, count: int) -> None:
        """输出分组或全量模式的标题。"""
        self._console.print()
        self._console.print(Rule(f"{label} ({count} 个接口)", style="bold"))

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _inspect(self, result: Any, indent: int = 2) -> None:
        prefix = " " * indent
        if result is None:
            self._console.print(f"{prefix}(None)")
        elif isinstance(result, list):
            self._console.print(f"{prefix}共 {len(result)} 条记录")
            for i, item in enumerate(result[:self._MAX_LIST_ITEMS]):
                self._console.print(f"{prefix}── [{i}] ──")
                self._show_fields(item, indent + 4)
            if len(result) > self._MAX_LIST_ITEMS:
                self._console.print(f"{prefix}[dim]... 还有 {len(result) - self._MAX_LIST_ITEMS} 条[/]")
        elif hasattr(result, "model_dump"):
            d = result.model_dump()
            self._console.print(f"{prefix}类型: [bold]{type(result).__name__}[/] ({len(d)} 个字段)")
            self._show_fields(result, indent)
        elif isinstance(result, dict):
            self._console.print(f"{prefix}{len(result)} 个键")
            for k, v in list(result.items())[:self._MAX_LIST_ITEMS]:
                self._console.print(f"{prefix}  {k}: {self._fmt(v)}")
        else:
            self._console.print(f"{prefix}{self._fmt(result)}")

    def _show_fields(self, obj: Any, indent: int = 0) -> None:
        prefix = " " * indent
        if hasattr(obj, "model_dump"):
            for k, v in obj.model_dump().items():
                if v is not None and v != [] and v != {} and v != "":
                    self._console.print(f"{prefix}{k}: {self._fmt(v)}")
        elif hasattr(obj, "__dataclass_fields__"):
            for k in obj.__dataclass_fields__:
                v = getattr(obj, k, None)
                if v is not None:
                    self._console.print(f"{prefix}{k}: {self._fmt(v)}")

    @classmethod
    def _fmt(cls, v: Any) -> str:
        if v is None:
            return "None"
        if isinstance(v, (int, float)):
            if isinstance(v, float):
                return f"{v:,.4f}" if abs(v) < 1000 else f"{v:,.2f}"
            return f"{v:,}"
        if isinstance(v, str):
            if len(v) > cls._MAX_STRING_LEN:
                return repr(v[:cls._MAX_STRING_LEN] + "...")
            return repr(v)
        if isinstance(v, list):
            if not v:
                return "[]"
            return f"[{len(v)} items] {cls._fmt(v[0])}" if len(v) == 1 else f"[{len(v)} items]"
        if isinstance(v, dict):
            return f"{{{len(v)} keys}}"
        return repr(v)[:cls._MAX_STRING_LEN]


# ═══════════════════════════════════════════════════════════════════════════
# ValueScanDebugger — 编排器
# ═══════════════════════════════════════════════════════════════════════════

class ValueScanDebugger:
    """ValueScan API 调试编排器 — 解析代币、调度接口、格式化输出。"""

    def __init__(
        self,
        symbol: str = "BTC",
        group: Optional[int] = None,
        method_name: str = "",
        list_only: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
    ) -> None:
        self._symbol = symbol
        self._group = group
        self._method_name = method_name
        self._list_only = list_only
        self._verbose = verbose
        self._console = console or Console()
        self._formatter = ValueScanFormatter(self._console)
        self._logger = logging.getLogger("vs.debug")

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.getLogger("libs.valuescan").setLevel(logging.DEBUG)
        else:
            logging.getLogger("libs.valuescan").setLevel(logging.INFO)

    async def run(self) -> None:
        self._validate_env()

        from libs.valuescan import ValueScanClient

        client = ValueScanClient.from_env()

        vs_id, coin_key = await self._resolve_token(client)

        registry = MethodRegistry(client, vs_id, self._symbol)

        if self._list_only:
            self._formatter.print_method_list(registry)
            return

        if self._method_name:
            await self._run_single(registry)
        elif self._group is not None:
            await self._run_group(registry)
        else:
            await self._run_all(registry)

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

    async def _resolve_token(self, client) -> tuple:
        self._logger.info("正在解析代币: %s ...", self._symbol)
        tokens = await client.search_token(self._symbol)
        if not tokens:
            self._logger.error("未找到代币: %s", self._symbol)
            sys.exit(1)

        token_info = tokens[0]
        vs_id: int = token_info.id
        coin_key = await client.get_coin_key(vs_id)
        self._logger.info("vs_token_id=%s, coin_key=%s", vs_id, coin_key)
        return vs_id, coin_key

    async def _run_single(self, registry: MethodRegistry) -> None:
        m = registry.by_name(self._method_name)
        if m is None:
            self._logger.error("未找到方法: %s", self._method_name)
            available = [x["name"] for x in registry.all]
            self._logger.info("可用方法: %s", available)
            self._console.print(f"\n[red]未找到方法: {self._method_name}[/]")
            self._console.print(f"可用方法: {', '.join(available)}")
            return

        self._logger.info("调用: %s (%s)", m["label"], m["name"])
        t0 = time.monotonic()
        error = None
        result = None
        try:
            result = await m["factory"]()
        except Exception as exc:
            error = exc
        elapsed = time.monotonic() - t0

        self._formatter.print_result(m["name"], m["label"], elapsed, result=result, error=error)

    async def _run_group(self, registry: MethodRegistry) -> None:
        methods = registry.by_group(self._group)
        if not methods:
            self._logger.error("无效分组: %s", self._group)
            return

        label = registry.group_names().get(self._group, f"Group {self._group}")
        self._logger.info("执行分组: %s (%d 个接口)", label, len(methods))
        self._formatter.print_header(label, len(methods))

        ok, fail = await self._execute_batch(methods)
        self._formatter.print_summary(ok, fail, len(methods))

    async def _run_all(self, registry: MethodRegistry) -> None:
        methods = registry.all
        self._logger.info("执行全部接口 (%d 个)", len(methods))
        self._formatter.print_header("全部接口", len(methods))

        ok, fail = await self._execute_batch(methods)
        self._formatter.print_summary(ok, fail, len(methods))

    async def _execute_batch(self, methods: List[Dict[str, Any]]) -> tuple:
        ok = fail = 0
        for m in methods:
            t0 = time.monotonic()
            error = None
            result = None
            try:
                result = await m["factory"]()
                ok += 1
            except Exception as exc:
                error = exc
                fail += 1
            elapsed = time.monotonic() - t0
            self._formatter.print_result(m["name"], m["label"], elapsed, result=result, error=error)
        return ok, fail


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

@click.command()
@click.option("--symbol", default="BTC", help="代币符号，如 BTC、ETH")
@click.option("--group", type=int, default=None, help="只执行某一分组 (1-6)")
@click.option("--method", "method_name", default="", help="只执行单个接口，如 get_realtime_fund")
@click.option("--list", "list_only", is_flag=True, help="列出所有可用方法和分组")
@click.option("--verbose", "-v", is_flag=True, help="启用 DEBUG 级别日志，输出 HTTP 请求细节")
def main(symbol: str, group: Optional[int], method_name: str, list_only: bool, verbose: bool) -> None:
    """ValueScan API 调试工具 — 支持全量/分组/单接口三种模式。"""
    debugger = ValueScanDebugger(
        symbol=symbol,
        group=group,
        method_name=method_name,
        list_only=list_only,
        verbose=verbose,
    )
    asyncio.run(debugger.run())


if __name__ == "__main__":
    main()
