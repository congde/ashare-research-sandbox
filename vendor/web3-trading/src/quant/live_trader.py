# -*- coding: utf-8 -*-
"""实盘/模拟交易执行器。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from quant.exchange import ExchangeBase, get_exchange


class LiveTrader:
    """将交易决策转为订单；默认 dry_run，不真实下单。"""

    def __init__(
        self,
        exchange: Optional[ExchangeBase] = None,
        dry_run: bool = True,
        max_order_usd: float = 500.0,
        log_dir: str = "data/live_trades",
        account_id: str = "default",
    ):
        self.account_id = account_id or "default"
        self.exchange = exchange or get_exchange(sandbox=self._use_sandbox(), account_id=self.account_id)
        self.dry_run = dry_run
        self.max_order_usd = max_order_usd
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._trade_log: list[dict] = []

    @staticmethod
    def _is_live() -> bool:
        return os.getenv("QUANT_LIVE_TRADING", "").lower() == "true" or os.getenv("QUANT_ARENA_LIVE", "").lower() == "true"

    @classmethod
    def _use_sandbox(cls) -> bool:
        raw = os.getenv("QUANT_EXCHANGE_SANDBOX")
        if raw not in (None, ""):
            return str(raw).lower() in ("1", "true", "yes", "y")
        return not cls._is_live()

    @staticmethod
    def _require_protective_orders() -> bool:
        raw = os.getenv("QUANT_REQUIRE_PROTECTIVE_ORDERS", "true")
        return raw.lower() in ("1", "true", "yes", "y")

    @classmethod
    def from_env(cls) -> "LiveTrader":
        dry_run = os.getenv("QUANT_LIVE_DRY_RUN", "true").lower() != "false"
        max_order = float(os.getenv("QUANT_LIVE_MAX_ORDER_USD", "500"))
        account_id = os.getenv("QUANT_ACCOUNT_ID") or os.getenv("QUANT_ARENA_ACCOUNT_ID") or "default"
        return cls(dry_run=dry_run, max_order_usd=max_order, account_id=account_id)

    async def get_account_snapshot(self, symbols: Optional[list[str]] = None) -> dict:
        # 优先使用 KuCoin Native API 获取余额（更可靠，不走 HF 接口）
        balance = await self._get_native_balance()
        if not balance:
            balance = await self.exchange.get_balance()
        positions = await self.exchange.get_positions(symbols=symbols)
        open_orders = []
        for sym in symbols or []:
            try:
                open_orders.extend(await self.exchange.get_open_orders(sym))
            except Exception:
                continue
        return {"balance": balance, "positions": positions, "openOrders": open_orders}

    async def _get_native_balance(self) -> dict:
        """用 KuCoin Native REST 获取 main+trade 合并余额，返回 CCXT 兼容格式。"""
        try:
            from quant.kucoin_native import KuCoinNativeClient
            import logging
            logger = logging.getLogger(__name__)
            native = KuCoinNativeClient("spot", account_id=self.account_id)
            resp = await native.spot_accounts()
            if str(resp.get("code")) != "200000":
                logger.warning(f"[NativeBalance] account_id={self.account_id} code={resp.get('code')}")
                return {}
            accounts = resp.get("data") or []
            free: dict = {}
            total: dict = {}
            used: dict = {}
            for item in accounts:
                currency = item.get("currency", "")
                available = float(item.get("available") or 0)
                holds = float(item.get("holds") or 0)
                bal = float(item.get("balance") or 0)
                # 合并 main + trade + trade_hf 等所有子账户
                free[currency] = free.get(currency, 0) + available
                used[currency] = used.get(currency, 0) + holds
                total[currency] = total.get(currency, 0) + bal
            logger.info(f"[NativeBalance] account_id={self.account_id} USDT free={free.get('USDT', 0):.2f} total={total.get('USDT', 0):.2f}")
            return {"free": free, "total": total, "used": used}
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[NativeBalance] account_id={self.account_id} error: {e}")
            return {}

    async def execute_decisions(self, decisions: list[dict], current_prices: dict[str, float]) -> list[dict]:
        results = []
        for decision in decisions:
            result = await self._execute_one(decision, current_prices)
            results.append(result)
            self._trade_log.append(result)
        self._save_log()
        return results

    async def _execute_one(self, decision: dict, current_prices: dict[str, float]) -> dict:
        symbol = decision.get("symbol", "")
        action = str(decision.get("action") or "hold").lower()
        quantity = float(decision.get("quantity") or 0)
        confidence = float(decision.get("confidence") or 0)
        stop_loss = decision.get("stop_loss") or decision.get("stopLoss")
        profit_target = decision.get("profit_target") or decision.get("take_profit") or decision.get("takeProfit")
        justification = decision.get("rationale") or decision.get("justification") or ""

        ts = datetime.now(timezone.utc).isoformat()
        price = float(decision.get("price") or current_prices.get(symbol, 0) or 0)
        order_usd = abs(quantity * price)
        record = {
            "timestamp": ts,
            "account_id": self.account_id,
            "source": decision.get("source") or decision.get("arenaAgent") or decision.get("strategy") or "manual",
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "order_usd": round(order_usd, 2),
            "confidence": confidence,
            "stop_loss": stop_loss,
            "profit_target": profit_target,
            "justification": justification,
            "dry_run": self.dry_run,
        }

        if action == "hold":
            record["status"] = "skipped"
            record["reason"] = "hold decision"
            return record
        if action not in ("buy", "sell", "short", "cover"):
            record["status"] = "rejected"
            record["reason"] = f"unsupported action: {action}"
            return record
        if quantity <= 0 or price <= 0:
            record["status"] = "rejected"
            record["reason"] = "invalid quantity or price"
            return record
        if order_usd > self.max_order_usd:
            record["status"] = "rejected"
            record["reason"] = f"order ${order_usd:,.2f} exceeds max ${self.max_order_usd:,.2f}"
            return record

        is_entry = action in ("buy", "short")
        if is_entry and not self.dry_run and self._is_live():
            if stop_loss in (None, "") or profit_target in (None, ""):
                record["status"] = "rejected"
                record["reason"] = "live entry requires stop_loss and take_profit"
                return record
            if self._require_protective_orders():
                supported = await self.exchange.supports_protective_orders(symbol, action)
                if not supported:
                    record["status"] = "rejected"
                    record["reason"] = "exchange-side protective orders/OCO not confirmed; rejecting live entry"
                    record["protective_orders_required"] = True
                    return record

        ccxt_side = "buy" if action in ("buy", "cover") else "sell"
        if self.dry_run or not self._is_live():
            record["status"] = "dry_run"
            record["ccxt_side"] = ccxt_side
            record["reason"] = "dry_run or QUANT_LIVE_TRADING not enabled"
            record["protective_orders_required"] = is_entry and self._require_protective_orders()
            return record

        # 买入前尝试将 main 子账户资金划转到 trade（KuCoin 现货下单需要 trade 余额）
        if action in ("buy", "cover"):
            try:
                from quant.kucoin_native import KuCoinNativeClient
                native = KuCoinNativeClient(market="spot", account_id=self.account_id)
                transfer_amount = str(round(order_usd * 1.01, 2))  # 多划转1%覆盖手续费
                transfer_result = await native.inner_transfer("USDT", transfer_amount, from_account="main", to_account="trade")
                import logging
                logging.getLogger(__name__).info(f"inner_transfer main→trade {transfer_amount} USDT: {transfer_result}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"inner_transfer failed (non-fatal): {e}")

        order = await self.exchange.place_order(symbol, ccxt_side, quantity)
        record["status"] = "filled" if order.success else "failed"
        record["order"] = order.to_dict()
        return record

    def _save_log(self) -> None:
        if not self._trade_log:
            return
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.log_dir / f"trades_{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for row in self._trade_log:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._trade_log.clear()

    async def close(self) -> None:
        await self.exchange.close()
