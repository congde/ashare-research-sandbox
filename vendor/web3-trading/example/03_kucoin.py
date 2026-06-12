# -*- coding: utf-8 -*-
"""KuCoin OpenAPI 调试工具 — K线 + 衍生品，仅公开接口。

用法:
    # 全部接口，分组展示
    python example/02_kucoin.py

    # 只执行某一分组
    python example/02_kucoin.py --group 1

    # 只执行单个接口（最常用调试模式）
    python example/02_kucoin.py --method get_kline --symbol BTC-USDT

    # 指定交易对
    python example/02_kucoin.py --symbol ETH-USDT

    # 查看所有可用方法和分组
    python example/02_kucoin.py --list

    # 合约 K线 + 衍生品
    python example/02_kucoin.py --market futures --symbol XBTUSDTM --method get_futures_kline
"""

from __future__ import annotations

import asyncio
import logging
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
# MethodRegistry — KuCoin 接口定义与分组
# ═══════════════════════════════════════════════════════════════════════════

_SPOT_TO_FUTURES = {
    "BTC-USDT": "XBTUSDTM",
    "ETH-USDT": "ETHUSDTM",
    "SOL-USDT": "SOLUSDTM",
}


class MethodRegistry:
    """KuCoin OpenAPI 方法注册表。"""

    GROUP_LABELS: ClassVar[Dict[int, str]] = {
        1: "现货 K线",
        2: "合约 K线",
        3: "合约衍生品（资金费率/持仓量）",
    }

    def __init__(self, client, symbol: str) -> None:
        self._client = client
        self._symbol = symbol
        # 合约 API 需要合约符号格式（如 XBTUSDTM）
        self._fsymbol = _SPOT_TO_FUTURES.get(symbol, symbol)
        self._methods: List[Dict[str, Any]] = self._build()

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

    def _build(self) -> List[Dict[str, Any]]:
        c = self._client
        symbol = self._symbol
        fs = self._fsymbol
        return [
            _m("get_kline",              "现货 K线 (1H)",     1, lambda: c.get_kline(symbol, granularity=_g("1hour"))),
            _m("get_multi_tf_kline",     "多周期现货 K线",     1, lambda: c.get_multi_tf_kline(symbol)),
            _m("get_futures_kline",          "合约 K线 (1H)",      2, lambda: c.get_futures_kline(fs)),
            _m("get_futures_multi_tf_kline", "多周期合约 K线",      2, lambda: c.get_futures_multi_tf_kline(fs)),
            _m("get_current_funding_rate",  "当前资金费率",  3, lambda: c.get_current_funding_rate(fs)),
            _m("get_funding_rate_history",  "资金费率历史",  3, lambda: c.get_funding_rate_history(fs)),
            _m("get_open_interest",         "当前总持仓量",  3, lambda: c.get_open_interest(fs)),
        ]


def _m(name: str, label: str, group: int, factory) -> Dict[str, Any]:
    return {"name": name, "label": label, "group": group, "factory": factory}


def _g(value: str):
    from libs.kucoin_openapi import KlineGranularity
    return KlineGranularity(value)


# ═══════════════════════════════════════════════════════════════════════════
# KuCoinFormatter — API 响应可视化
# ═══════════════════════════════════════════════════════════════════════════

class KuCoinFormatter:
    """将 KuCoin API 响应渲染为 Rich 终端输出。"""

    _MAX_STRING_LEN = 80
    _MAX_LIST_ITEMS = 8

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    def print_method_list(self, registry: MethodRegistry) -> None:
        for group, label in registry.group_names().items():
            methods = registry.by_group(group)
            self._console.print(f"\n[bold]Group {group} — {label}[/]")
            for m in methods:
                self._console.print(f"  [cyan]{m['name']:<36}[/] {m['label']}")

    def print_result(self, name: str, label: str, elapsed: float, result: Any = None, error: Optional[Exception] = None) -> None:
        status = "❌" if error else "✅"
        self._console.print(f"\n── {label} ([cyan]{name}[/])  {status} {elapsed:.2f}s ──")
        if error:
            self._console.print(f"   [red]{type(error).__name__}: {error}[/]")
        elif result is not None:
            self._inspect(result)
        else:
            self._console.print("   (空响应)")

    def print_summary(self, ok: int, fail: int, total: int) -> None:
        self._console.print()
        self._console.print(Rule(style="dim"))
        self._console.print(f"  结果: [green]{ok} 成功[/], [red]{fail} 失败[/], {total} 总计")
        self._console.print(Rule(style="dim"))

    def print_header(self, label: str, count: int) -> None:
        self._console.print()
        self._console.print(Rule(f"{label} ({count} 个接口)", style="bold"))

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
        elif isinstance(result, dict):
            self._console.print(f"{prefix}类型: [bold]dict[/] ({len(result)} 个键)")
            for k, v in list(result.items())[:self._MAX_LIST_ITEMS]:
                self._console.print(f"{prefix}  {k}: {self._fmt(v)}")
        elif hasattr(result, "model_dump"):
            d = result.model_dump()
            self._console.print(f"{prefix}类型: [bold]{type(result).__name__}[/] ({len(d)} 个字段)")
            self._show_fields(result, indent)
        else:
            self._console.print(f"{prefix}{self._fmt(result)}")

    def _show_fields(self, obj: Any, indent: int = 0) -> None:
        prefix = " " * indent
        if hasattr(obj, "model_dump"):
            for k, v in obj.model_dump().items():
                if v is not None and v != [] and v != {} and v != "":
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
            return f"[{len(v)} items]"
        if isinstance(v, dict):
            return f"{{{len(v)} keys}}"
        return repr(v)[:cls._MAX_STRING_LEN]


# ═══════════════════════════════════════════════════════════════════════════
# KuCoinDebugger — 编排器
# ═══════════════════════════════════════════════════════════════════════════

class KuCoinDebugger:
    """KuCoin OpenAPI 调试编排器。"""

    def __init__(
        self,
        symbol: str = "BTC-USDT",
        market: str = "spot",
        group: Optional[int] = None,
        method_name: str = "",
        list_only: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
    ) -> None:
        self._symbol = symbol
        self._market = market
        self._group = group
        self._method_name = method_name
        self._list_only = list_only
        self._verbose = verbose
        self._console = console or Console()
        self._formatter = KuCoinFormatter(self._console)
        self._logger = logging.getLogger("kucoin.debug")

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.getLogger("libs.kucoin_openapi").setLevel(logging.DEBUG)
        else:
            logging.getLogger("libs.kucoin_openapi").setLevel(logging.INFO)

    async def run(self) -> None:
        from libs.kucoin_openapi import KuCoinClient

        client = KuCoinClient()
        registry = MethodRegistry(client, self._symbol)

        if self._list_only:
            self._formatter.print_method_list(registry)
            return

        self._console.print(f"\n[bold]KuCoin OpenAPI[/] — {self._symbol}  (market={self._market})")

        if self._method_name:
            await self._run_single(registry)
        elif self._group is not None:
            await self._run_group(registry)
        else:
            await self._run_all(registry)

    async def _run_single(self, registry: MethodRegistry) -> None:
        m = registry.by_name(self._method_name)
        if m is None:
            available = [x["name"] for x in registry.all]
            self._console.print(f"\n[red]未找到方法: {self._method_name}[/]")
            self._console.print(f"可用方法: {', '.join(available)}")
            return

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
        self._formatter.print_header(label, len(methods))
        ok, fail = await self._execute_batch(methods)
        self._formatter.print_summary(ok, fail, len(methods))

    async def _run_all(self, registry: MethodRegistry) -> None:
        methods = registry.all
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
@click.option("--symbol", default="BTC-USDT", help="交易对符号")
@click.option("--market", default="spot", help="市场类型: spot / futures")
@click.option("--group", type=int, default=None, help="只执行某一分组 (1-3)")
@click.option("--method", "method_name", default="", help="只执行单个接口，如 get_kline")
@click.option("--list", "list_only", is_flag=True, help="列出所有可用方法和分组")
@click.option("--verbose", "-v", is_flag=True, help="启用 DEBUG 级别日志")
def main(symbol: str, market: str, group: Optional[int], method_name: str, list_only: bool, verbose: bool) -> None:
    """KuCoin OpenAPI 调试工具 — K线 + 衍生品，仅公开接口。"""
    debugger = KuCoinDebugger(
        symbol=symbol,
        market=market,
        group=group,
        method_name=method_name,
        list_only=list_only,
        verbose=verbose,
    )
    asyncio.run(debugger.run())


if __name__ == "__main__":
    main()
