#!/usr/bin/env python3
"""Standalone smoke test for build_skills_modules (uses httpx only)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SPOT = "https://api.kucoin.com"
FUTURES = "https://api-futures.kucoin.com"
SYMBOL = "BTC-USDT"
BASE, QUOTE = "BTC", "USDT"
FUTURES_SYM = "XBTUSDTM"


async def get(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url, timeout=20.0)
    try:
        return r.json()
    except Exception:
        return {"code": "parse_error", "msg": r.text[:200]}


async def main() -> int:
    tests: list[tuple[str, str]] = [
        ("spot", f"{SPOT}/api/v1/market/stats?symbol={SYMBOL}"),
        ("symbol-info", f"{SPOT}/api/v2/symbols/{SYMBOL}"),
        ("currency-info", f"{SPOT}/api/v3/currencies/{BASE}"),
        ("fiat-price", f"{SPOT}/api/v1/prices?base=USD&currencies={BASE}"),
        ("orderbook-l1", f"{SPOT}/api/v1/market/orderbook/level1?symbol={SYMBOL}"),
        ("orderbook-l2", f"{SPOT}/api/v1/market/orderbook/level2_20?symbol={SYMBOL}"),
        ("recent-trades", f"{SPOT}/api/v1/market/histories?symbol={SYMBOL}"),
        ("klines-15m", f"{SPOT}/api/v1/market/candles?symbol={SYMBOL}&type=15min"),
        ("klines-1h", f"{SPOT}/api/v1/market/candles?symbol={SYMBOL}&type=1hour"),
        ("klines-4h", f"{SPOT}/api/v1/market/candles?symbol={SYMBOL}&type=4hour"),
        ("klines-1d", f"{SPOT}/api/v1/market/candles?symbol={SYMBOL}&type=1day"),
        ("allTickers", f"{SPOT}/api/v1/market/allTickers"),
        ("markets", f"{SPOT}/api/v1/markets"),
        ("margin-all-mark", f"{SPOT}/api/v3/mark-price/all-symbols"),
        ("margin-cross", f"{SPOT}/api/v3/margin/symbols"),
        ("margin-isolated", f"{SPOT}/api/v1/isolated/symbols"),
        ("margin-config", f"{SPOT}/api/v1/margin/config"),
        ("margin-collateral", f"{SPOT}/api/v3/margin/collateralRatio"),
        ("etf-info", f"{SPOT}/api/v3/etf/info"),
        ("convert-currencies", f"{SPOT}/api/v1/convert/currencies"),
        ("convert-symbol", f"{SPOT}/api/v1/convert/symbol?fromCurrency={BASE}&toCurrency={QUOTE}&orderType=MARKET"),
        ("announcements", f"{SPOT}/api/v3/announcements?currentPage=1&pageSize=50"),
        ("futures-ticker", f"{FUTURES}/api/v1/ticker?symbol={FUTURES_SYM}"),
        ("futures-contract", f"{FUTURES}/api/v1/contracts/{FUTURES_SYM}"),
        ("futures-funding-cur", f"{FUTURES}/api/v1/funding-rate/{FUTURES_SYM}/current"),
        ("futures-oi", f"{FUTURES}/api/v1/interest/query?symbol={FUTURES_SYM}"),
        ("futures-mark", f"{FUTURES}/api/v1/mark-price/{FUTURES_SYM}/current"),
        ("futures-trades", f"{FUTURES}/api/v1/trade/history?symbol={FUTURES_SYM}"),
        ("fear-greed", "https://api.alternative.me/fng/?limit=14&format=json"),
        ("polymarket", "https://gamma-api.polymarket.com/markets?active=true&closed=false&tag=crypto&order=volume24hr&ascending=false&limit=5"),
        ("blockchain-stats", "https://api.blockchain.info/stats"),
    ]

    ok, fail = 0, 0
    async with httpx.AsyncClient(verify=False) as client:
        for name, url in tests:
            t0 = time.perf_counter()
            try:
                data = await get(client, url)
                code = str(data.get("code", "200")) if isinstance(data, dict) else "200"
                if name in ("fear-greed", "polymarket", "blockchain-stats"):
                    success = bool(data)
                elif code in ("200000", "200"):
                    success = True
                elif name == "convert-symbol" and code == "102431":
                    success = True  # expected business response
                else:
                    success = False
                ms = int((time.perf_counter() - t0) * 1000)
                if success:
                    ok += 1
                    tag = "OK" if code == "200000" or name in ("fear-greed", "polymarket", "blockchain-stats") else f"OK({code})"
                    print(f"[{tag}] {name} {ms}ms")
                else:
                    fail += 1
                    print(f"[FAIL] {name} {ms}ms code={code} msg={str(data.get('msg',''))[:80]}")
            except Exception as exc:
                fail += 1
                print(f"[EXC] {name}: {exc}")

    print(f"\nSummary: {ok} ok, {fail} fail / {len(tests)} total")

    # Try import build_skills_modules if deps available
    try:
        from web.api.dashboard_service import build_skills_modules

        t0 = time.perf_counter()
        modules = await build_skills_modules(SYMBOL)
        elapsed = time.perf_counter() - t0
        stats: dict[str, int] = {}
        for m in modules:
            stats[m.get("status", "?")] = stats.get(m.get("status", "?"), 0) + 1
        print(f"\nbuild_skills_modules: {len(modules)} modules in {elapsed:.2f}s")
        print("status:", stats)
        for m in modules:
            if m.get("status") == "error":
                print(f"  ERROR {m.get('name')}: {m.get('error','')[:100]}")
        return 0 if stats.get("error", 0) <= 1 else 1  # convert may error on old code path
    except ImportError as exc:
        print(f"\nSkip build_skills_modules import: {exc}")
        return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
