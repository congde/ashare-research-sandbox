# -*- coding: utf-8 -*-
"""交易所抽象层。

默认使用 CCXT 对接 KuCoin，支持 dry-run 上层保护；真实下单由 LiveTrader 再次校验。
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional


def _account_key_variants(account_id: Optional[str]) -> list[str]:
    raw = str(account_id or "").strip()
    if not raw or raw.lower() == "default":
        return []
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    variants = [normalized]
    if normalized.endswith("_AGENT"):
        variants.append(normalized[:-6])
    if "_" in normalized:
        variants.append(normalized.split("_", 1)[0])
    result: list[str] = []
    for item in variants:
        if item and item not in result:
            result.append(item)
    return result


def _credential_value(account_id: Optional[str], names: tuple[str, ...], fallback_names: tuple[str, ...]) -> str:
    for account_key in _account_key_variants(account_id):
        prefix = f"KUCOIN_ACCOUNT_{account_key}"
        for name in names:
            value = os.getenv(f"{prefix}_{name}")
            if value:
                return value
    for name in fallback_names:
        value = os.getenv(name)
        if value:
            return value
    return ""


class OrderResult:
    """标准化订单执行结果。"""

    def __init__(
        self,
        success: bool,
        order_id: str = "",
        filled_price: float = 0,
        filled_qty: float = 0,
        fee: float = 0,
        raw: Optional[dict] = None,
        error: str = "",
    ):
        self.success = success
        self.order_id = order_id
        self.filled_price = filled_price
        self.filled_qty = filled_qty
        self.fee = fee
        self.raw = raw or {}
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "filled_price": self.filled_price,
            "filled_qty": self.filled_qty,
            "fee": self.fee,
            "error": self.error,
            "raw": self.raw,
        }


class ExchangeBase(ABC):
    """统一交易所接口。"""

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        ...

    @abstractmethod
    async def get_ticker_price(self, symbol: str) -> Optional[float]:
        ...

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        return OrderResult(success=False, error="Live trading not supported on this exchange")

    async def cancel_order(self, symbol: str, order_id: str) -> OrderResult:
        return OrderResult(success=False, error="Cancel order not supported")

    async def supports_protective_orders(self, symbol: str, action: str) -> bool:
        return False

    async def get_balance(self) -> dict:
        return {}

    async def get_positions(self, symbols: Optional[list[str]] = None) -> list[dict]:
        return []

    async def get_open_orders(self, symbol: str = "") -> list[dict]:
        return []

    async def close(self) -> None:
        return None


class CCXTExchange(ExchangeBase):
    """CCXT 交易所实现，默认 KuCoin。

    环境变量：
    - QUANT_EXCHANGE_ID: kucoin / kucoinfutures / binance / okx ...
    - QUANT_MARKET_TYPE: spot / swap / futures
    - KUCOIN_API_KEY / KUCOIN_API_SECRET / KUCOIN_API_PASSPHRASE
    - CCXT_API_KEY / CCXT_API_SECRET / CCXT_API_PASSWORD（通用兜底）
    """

    def __init__(
        self,
        exchange_id: Optional[str] = None,
        sandbox: bool = True,
        market_type: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        try:
            import ccxt.async_support as ccxt_async
        except ImportError as exc:
            raise ImportError("ccxt not installed. Run: pip install ccxt") from exc

        self.exchange_id = exchange_id or os.getenv("QUANT_EXCHANGE_ID", "kucoin")
        self.market_type = market_type or os.getenv("QUANT_MARKET_TYPE", "spot")
        self.account_id = account_id or os.getenv("QUANT_ACCOUNT_ID") or os.getenv("QUANT_ARENA_ACCOUNT_ID") or "default"
        exchange_class = getattr(ccxt_async, self.exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unknown exchange: {self.exchange_id}")

        api_key = _credential_value(self.account_id, ("API_KEY", "KEY"), ("KUCOIN_API_KEY", "CCXT_API_KEY"))
        secret = _credential_value(self.account_id, ("API_SECRET", "SECRET"), ("KUCOIN_API_SECRET", "CCXT_API_SECRET"))
        password = _credential_value(self.account_id, ("API_PASSPHRASE", "PASSPHRASE", "PASSWORD"), ("KUCOIN_API_PASSPHRASE", "CCXT_API_PASSWORD"))

        config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": self.market_type},
        }
        if api_key and secret:
            config.update({"apiKey": api_key, "secret": secret})
            if password:
                config["password"] = password

        self.client = exchange_class(config)
        if sandbox and hasattr(self.client, "set_sandbox_mode"):
            try:
                self.client.set_sandbox_mode(True)
            except Exception:
                # KuCoin 部分市场无 CCXT 沙盒，保持上层 dry_run 兜底。
                pass

    async def _ensure_markets_loaded(self) -> None:
        if self.exchange_id == "kucoin" and self.market_type == "spot":
            await self.client.load_markets(False, {"marginables": False})
            return
        await self.client.load_markets()

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[dict]:
        rows = await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            {
                "t": int(row[0]),
                "tsSec": int(row[0] // 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5]),
            }
            for row in rows
        ]

    async def get_ticker_price(self, symbol: str) -> Optional[float]:
        await self._ensure_markets_loaded()
        ticker = await self.client.fetch_ticker(symbol)
        value = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
        return float(value) if value is not None else None

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        try:
            await self._ensure_markets_loaded()
            order = await self.client.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=quantity,
                price=price if order_type == "limit" else None,
            )
            filled_price = order.get("average") or order.get("price") or 0
            filled_qty = order.get("filled") or order.get("amount") or quantity
            fee = 0.0
            raw_fee = order.get("fee") or {}
            if isinstance(raw_fee, dict):
                fee = float(raw_fee.get("cost") or 0)
            return OrderResult(
                success=True,
                order_id=str(order.get("id") or ""),
                filled_price=float(filled_price or 0),
                filled_qty=float(filled_qty or 0),
                fee=fee,
                raw=order,
            )
        except Exception as exc:
            return OrderResult(success=False, error=str(exc))

    async def cancel_order(self, symbol: str, order_id: str) -> OrderResult:
        try:
            await self._ensure_markets_loaded()
            data = await self.client.cancel_order(order_id, symbol=symbol)
            return OrderResult(success=True, order_id=order_id, raw=data)
        except Exception as exc:
            return OrderResult(success=False, order_id=order_id, error=str(exc))

    async def get_balance(self) -> dict:
        await self._ensure_markets_loaded()
        # KuCoin 现货：显式请求 trade 类型避免 CCXT 默认走 HF 接口（需额外权限）
        params = {"type": "trade"} if self.exchange_id == "kucoin" and self.market_type == "spot" else {}
        balance = await self.client.fetch_balance(params)
        # KuCoin 现货：合并 main + trade 子账户余额，确保风控和 LLM 能看到全部可用资金
        # 实际下单前由 live_trader 的 inner_transfer 完成 main→trade 划转
        if self.exchange_id == "kucoin" and self.market_type == "spot":
            try:
                main_balance = await self.client.fetch_balance({"type": "main"})
                for key in ("free", "total", "used"):
                    merged = dict(balance.get(key) or {})
                    for asset, amount in (main_balance.get(key) or {}).items():
                        merged[asset] = float(merged.get(asset) or 0) + float(amount or 0)
                    balance[key] = merged
            except Exception:
                pass
        return balance

    async def get_positions(self, symbols: Optional[list[str]] = None) -> list[dict]:
        if self.market_type == "spot":
            return await self._get_spot_positions(symbols)
        if not hasattr(self.client, "fetch_positions"):
            return []
        try:
            return await self.client.fetch_positions(symbols=symbols)
        except Exception:
            return []

    async def get_open_orders(self, symbol: str = "") -> list[dict]:
        await self._ensure_markets_loaded()
        return await self.client.fetch_open_orders(symbol or None)

    async def _get_spot_positions(self, symbols: Optional[list[str]] = None) -> list[dict]:
        balance = await self.get_balance()
        total = balance.get("total") or {}
        free = balance.get("free") or {}
        used = balance.get("used") or {}
        target_symbols = symbols or [f"{asset}/USDT" for asset, amount in total.items() if asset != "USDT" and float(amount or 0) > 0]
        positions: list[dict] = []

        for symbol in target_symbols:
            base = symbol.split("/")[0] if "/" in symbol else symbol.split("-")[0]
            try:
                amount = float(total.get(base) or 0)
                free_amount = float(free.get(base) or 0)
                used_amount = float(used.get(base) or 0)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue

            mark_price = 0.0
            notional = 0.0
            try:
                mark_price = float(await self.get_ticker_price(symbol) or 0)
                notional = amount * mark_price
            except Exception:
                pass

            positions.append({
                "symbol": symbol,
                "asset": base,
                "side": "long",
                "contracts": amount,
                "amount": amount,
                "free": free_amount,
                "used": used_amount,
                "notional": notional,
                "markPrice": mark_price,
                "marketType": "spot",
            })
        return positions

    async def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            await close()


def get_exchange(sandbox: bool = True, account_id: Optional[str] = None) -> ExchangeBase:
    return CCXTExchange(sandbox=sandbox, account_id=account_id)
