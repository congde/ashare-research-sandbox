# -*- coding: utf-8 -*-
"""Dashboard live trading and live result APIs."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from web.router import BaseRouter

logger = logging.getLogger(__name__)

_LIVE_LOG_DIR = Path("data/live_trades")
_MAX_DASHBOARD_SPOT_USD = 100.0
_MAX_DASHBOARD_FUTURES_NOTIONAL = 500.0
_MAX_DASHBOARD_FUTURES_MARGIN = 100.0
_MAX_DASHBOARD_TRANSFER_USD = 2000.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _trade_order(row: Dict[str, Any]) -> Dict[str, Any]:
    order = row.get("order")
    return order if isinstance(order, dict) else {}


def _append_live_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    _LIVE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _LIVE_LOG_DIR / f"trades_{day}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _trade_filled_usd(row: Dict[str, Any]) -> float:
    order = _trade_order(row)
    return _num(row.get("filled_usd") or order.get("cost") or 0)


def _trade_filled_qty(row: Dict[str, Any]) -> float:
    order = _trade_order(row)
    return _num(row.get("filled_qty") or order.get("filled_qty") or 0)


def _trade_filled_price(row: Dict[str, Any]) -> float:
    order = _trade_order(row)
    return _num(row.get("filled_price") or order.get("filled_price") or row.get("price") or 0)


def _trade_fee(row: Dict[str, Any]) -> float:
    order = _trade_order(row)
    fee = order.get("fee")
    if isinstance(fee, dict):
        return _num(fee.get("cost"))
    return _num(fee)


def _load_trade_rows(days: int = 30) -> List[Dict[str, Any]]:
    if not _LIVE_LOG_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    rows: List[Dict[str, Any]] = []
    for path in sorted(_LIVE_LOG_DIR.glob("trades_*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                ts = _parse_ts(row.get("timestamp"))
                if ts is not None and ts < cutoff:
                    continue
                row["_source_file"] = str(path)
                rows.append(row)
        except Exception as exc:
            logger.warning("read live trade log failed: %s %s", path, exc)
    rows.sort(key=lambda item: str(item.get("timestamp") or ""))
    return rows


def _spot_fifo_summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    lots: Dict[str, List[Dict[str, float]]] = {}
    realized = 0.0
    realized_cost = 0.0
    realized_returns: List[float] = []
    realized_pnls: List[float] = []
    realized_curve: List[Dict[str, Any]] = []

    for row in rows:
        if str(row.get("market_type") or "spot").lower() != "spot":
            continue
        action = str(row.get("action") or "").lower()
        status = str(row.get("status") or "").lower()
        if status not in {"filled", "closed", "partially_filled"}:
            continue
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        qty = _trade_filled_qty(row)
        cost = _trade_filled_usd(row)
        if qty <= 0 or cost <= 0:
            continue
        if action == "buy":
            lots.setdefault(symbol, []).append({"qty": qty, "cost": cost})
        elif action == "sell":
            remaining = qty
            avg_sell = cost / qty if qty else 0.0
            for lot in lots.setdefault(symbol, []):
                if remaining <= 0:
                    break
                if lot["qty"] <= 0:
                    continue
                matched = min(remaining, lot["qty"])
                buy_cost = lot["cost"] * (matched / lot["qty"])
                sell_proceeds = avg_sell * matched
                pnl = sell_proceeds - buy_cost
                realized += pnl
                realized_cost += buy_cost
                realized_pnls.append(pnl)
                if buy_cost > 0:
                    realized_returns.append(pnl / buy_cost)
                lot["qty"] -= matched
                lot["cost"] -= buy_cost
                remaining -= matched
            ts = _parse_ts(row.get("timestamp"))
            if ts:
                realized_curve.append({"time": int(ts.timestamp()), "value": round(realized, 8)})

    open_positions = []
    for symbol, symbol_lots in lots.items():
        qty = sum(max(0.0, lot["qty"]) for lot in symbol_lots)
        cost = sum(max(0.0, lot["cost"]) for lot in symbol_lots)
        if qty > 0:
            open_positions.append({
                "symbol": symbol,
                "qty": round(qty, 10),
                "cost_usd": round(cost, 8),
                "avg_price": round(cost / qty, 8) if qty else 0,
            })
    if not realized_curve:
        realized_curve.append({"time": int(datetime.now(timezone.utc).timestamp()), "value": 0.0})
    open_cost = sum(item["cost_usd"] for item in open_positions)
    capital_base = max(realized_cost + open_cost, open_cost, 1.0)
    equity_values = [capital_base + _num(item.get("value")) for item in realized_curve]
    peak = equity_values[0] if equity_values else capital_base
    max_drawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    avg_return = sum(realized_returns) / len(realized_returns) if realized_returns else 0.0
    if len(realized_returns) > 1:
        variance = sum((item - avg_return) ** 2 for item in realized_returns) / (len(realized_returns) - 1)
        sharpe = (avg_return / (variance ** 0.5)) * (len(realized_returns) ** 0.5) if variance > 0 else 0.0
    else:
        sharpe = None
    wins = sum(1 for item in realized_pnls if item > 0)
    return {
        "realized_pnl_usd": round(realized, 8),
        "open_positions": open_positions,
        "realized_curve": realized_curve,
        "performance": {
            "capital_base_usd": round(capital_base, 8),
            "realized_cost_usd": round(realized_cost, 8),
            "realized_return_pct": round(realized / capital_base * 100, 6) if capital_base > 0 else 0.0,
            "max_drawdown_pct": round(max_drawdown * 100, 6),
            "sharpe_ratio": round(sharpe, 6) if sharpe is not None else None,
            "closed_lots": len(realized_pnls),
            "win_rate_pct": round(wins / len(realized_pnls) * 100, 4) if realized_pnls else 0.0,
        },
    }


@contextmanager
def _temporary_env(values: Dict[str, str]):
    old_values = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _compact_order_result(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact = []
    for row in rows:
        order = _trade_order(row)
        compact.append({
            "timestamp": row.get("timestamp"),
            "source": row.get("source"),
            "account_id": row.get("account_id"),
            "symbol": row.get("symbol"),
            "action": row.get("action"),
            "quantity": row.get("quantity"),
            "price": row.get("price"),
            "order_usd": row.get("order_usd"),
            "filled_usd": _trade_filled_usd(row),
            "filled_qty": _trade_filled_qty(row),
            "filled_price": _trade_filled_price(row),
            "status": row.get("status"),
            "reason": row.get("reason"),
            "order_id": order.get("order_id") or (order.get("raw") or {}).get("id"),
            "order_status": order.get("status"),
            "error": order.get("error"),
            "dry_run": row.get("dry_run"),
        })
    return compact


def _configured_kucoin_account_ids() -> List[str]:
    account_ids: List[str] = []
    pattern = re.compile(r"^KUCOIN_ACCOUNT_(.+)_(?:API_KEY|KEY)$")
    for key, value in os.environ.items():
        if not value:
            continue
        match = pattern.match(key)
        if match:
            account_ids.append(match.group(1).lower())
    if os.getenv("KUCOIN_API_KEY") or os.getenv("CCXT_API_KEY"):
        account_ids.append("default")
    return list(dict.fromkeys(account_ids)) or ["default"]


def _resolve_live_account_id(body: Optional[Dict[str, Any]] = None, *, default: str = "default") -> str:
    body = body or {}
    value = str(body.get("accountId") or body.get("account_id") or default).strip().lower()
    return value or default


def _live_futures_account_id() -> str:
    """合约实盘固定账户：优先 QUANT_LIVE_FUTURES_ACCOUNT_ID，否则 CLAUDE 密钥，最后 default。"""
    explicit = str(os.getenv("QUANT_LIVE_FUTURES_ACCOUNT_ID") or "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("KUCOIN_ACCOUNT_CLAUDE_API_KEY") or os.getenv("KUCOIN_ACCOUNT_CLAUDE_KEY"):
        return "claude"
    return "default"


def _resolve_live_futures_account_id(body: Optional[Dict[str, Any]] = None) -> str:
    """合约划转/下单仅允许操作配置的实盘账户。"""
    allowed = _live_futures_account_id()
    requested = _resolve_live_account_id(body, default=allowed)
    return allowed if requested != allowed else allowed


def _compact_balance(balance: Dict[str, Any], assets: Iterable[str] = ("USDT", "KCS", "BTC", "ETH")) -> Dict[str, Any]:
    result = []
    total = balance.get("total") or {}
    free = balance.get("free") or {}
    used = balance.get("used") or {}
    for asset in assets:
        total_value = _num(total.get(asset))
        free_value = _num(free.get(asset))
        used_value = _num(used.get(asset))
        if total_value or free_value or used_value:
            result.append({"asset": asset, "total": total_value, "free": free_value, "used": used_value})
    return {"assets": result}


def _compact_native_spot_accounts(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result = []
    for row in rows:
        asset = str(row.get("currency") or "").upper()
        if not asset:
            continue
        total_value = _num(row.get("balance"))
        free_value = _num(row.get("available"))
        used_value = _num(row.get("holds"))
        if total_value or free_value or used_value:
            result.append({
                "asset": asset,
                "account_type": row.get("type") or "",
                "total": total_value,
                "free": free_value,
                "used": used_value,
            })
    return {"assets": result}


def _compact_native_futures_overview(data: Dict[str, Any]) -> Dict[str, Any]:
    asset = str(data.get("currency") or "USDT").upper()
    total_value = _num(data.get("accountEquity") or data.get("marginBalance") or data.get("totalMarginBalance"))
    free_value = _num(data.get("availableBalance") or data.get("available"))
    used_value = _num(data.get("positionMargin")) + _num(data.get("orderMargin"))
    if total_value or free_value or used_value:
        return {"assets": [{"asset": asset, "account_type": "futures", "total": total_value, "free": free_value, "used": used_value}]}
    return {"assets": []}


async def _enrich_assets_usdt_value(accounts: List[Dict[str, Any]]) -> None:
    """为所有账户的非 USDT 资产附加 usdt_value（折算金额）和 usdt_price（单价）。"""
    import httpx

    # 收集需要查价格的币种
    currencies: set = set()
    for acct in accounts:
        for asset_row in (acct.get("balance") or {}).get("assets") or []:
            asset_name = str(asset_row.get("asset") or "").upper()
            if asset_name and asset_name != "USDT" and _num(asset_row.get("total")) > 0:
                currencies.add(asset_name)

    if not currencies:
        return

    # 批量获取 ticker 价格
    prices: Dict[str, float] = {}
    async with httpx.AsyncClient(timeout=5, verify=False) as client:
        for currency in currencies:
            try:
                symbol = f"{currency}-USDT"
                resp = await client.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}")
                data = resp.json()
                ticker_data = data.get("data") or {}
                price = _num(ticker_data.get("price"))
                if price > 0:
                    prices[currency] = price
            except Exception:
                pass

    # 给每个 asset 补充折算值
    for acct in accounts:
        total_usdt_sum = 0.0
        for asset_row in (acct.get("balance") or {}).get("assets") or []:
            asset_name = str(asset_row.get("asset") or "").upper()
            total_qty = _num(asset_row.get("total"))
            if asset_name == "USDT":
                asset_row["usdt_value"] = round(total_qty, 4)
                total_usdt_sum += total_qty
            elif asset_name in prices:
                usdt_val = total_qty * prices[asset_name]
                asset_row["usdt_price"] = prices[asset_name]
                asset_row["usdt_value"] = round(usdt_val, 4)
                total_usdt_sum += usdt_val
        # 写入账户总折算值
        acct["total_usdt_value"] = round(total_usdt_sum, 4)
    # 补充占比
    for acct in accounts:
        acct_total = acct.get("total_usdt_value") or 0
        for asset_row in (acct.get("balance") or {}).get("assets") or []:
            usdt_val = asset_row.get("usdt_value")
            if usdt_val is not None and acct_total > 0:
                asset_row["pct"] = round(usdt_val / acct_total * 100, 2)


async def _fetch_order_safely(client: Any, order: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    order_id = str(order.get("id") or (order.get("info") or {}).get("orderId") or "")
    if not order_id:
        return order
    try:
        fetched = await client.fetch_order(order_id, symbol)
        if isinstance(fetched, dict):
            fetched.setdefault("create_order", order)
            return fetched
    except Exception as exc:
        order["fetch_order_error"] = str(exc)
    return order


def _futures_ledger_row(
    *,
    order: Dict[str, Any],
    symbol: str,
    action: str,
    contracts: int,
    price: float,
    contract_size: float,
    notional_usd: float,
    leverage: int,
    margin_mode: str,
    position_mode: str,
) -> Dict[str, Any]:
    info = order.get("info") or {}
    filled_qty = _num(order.get("filled") or order.get("amount") or info.get("size") or contracts)
    filled_price = _num(order.get("average") or order.get("price") or price)
    filled_usd = filled_qty * contract_size * filled_price if filled_qty > 0 and filled_price > 0 else 0.0
    status = str(order.get("status") or info.get("status") or "submitted")
    if status == "closed":
        status = "filled"
    fee = order.get("fee") if isinstance(order.get("fee"), dict) else None
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "market_type": "futures",
        "action": action,
        "quantity": contracts,
        "price": price,
        "order_usd": round(notional_usd, 8),
        "filled_usd": round(filled_usd, 8) if filled_usd > 0 else 0,
        "filled_qty": filled_qty,
        "filled_price": filled_price,
        "confidence": 1.0,
        "dry_run": False,
        "status": status,
        "leverage": leverage,
        "margin_mode": margin_mode,
        "position_mode": position_mode,
        "order": {
            "order_id": order.get("id") or info.get("orderId"),
            "status": status,
            "filled_qty": filled_qty,
            "filled_price": filled_price,
            "cost": round(filled_usd, 8) if filled_usd > 0 else 0,
            "fee": fee,
            "raw": order,
        },
    }


def _native_order_ok(response: Dict[str, Any]) -> bool:
    return str(response.get("code")) == "200000"


def _futures_position_side(open_side: str, position_mode: str) -> str:
    if position_mode == "HEDGE":
        return "LONG" if open_side == "buy" else "SHORT"
    return "BOTH"


def _native_futures_order_to_row(
    *,
    response: Dict[str, Any],
    detail: Dict[str, Any],
    symbol: str,
    native_symbol: str,
    side: str,
    contracts: int,
) -> Dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    info = detail.get("data") if _native_order_ok(detail) and isinstance(detail.get("data"), dict) else {}
    order_id = str(data.get("orderId") or data.get("id") or info.get("id") or "")
    filled = _num(info.get("filledSize") or info.get("dealSize") or info.get("size") or contracts)
    price = _num(info.get("dealPrice") or info.get("price"))
    status = str(info.get("status") or "submitted")
    return {
        "id": order_id,
        "status": status,
        "side": side,
        "amount": contracts,
        "filled": filled,
        "average": price,
        "price": price,
        "info": {
            "orderId": order_id,
            "symbol": native_symbol,
            "execution_provider": "kucoin_native_rest",
            "createOrder": response,
            "detail": detail,
            **info,
        },
    }


def _native_error_text(response: Dict[str, Any]) -> str:
    return str(response.get("msg") or response.get("message") or response.get("data") or response)


def _guess_native_futures_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().replace("-", "/")
    pair = raw.split(":", 1)[0]
    if "/" in pair:
        base, quote = pair.split("/", 1)
    else:
        base, quote = pair, "USDT"
    base_alias = {"BTC": "XBT"}.get(base, base)
    return f"{base_alias}{quote}M"


async def _resolve_native_futures_symbol(exchange: Any, symbol: str) -> str:
    try:
        await exchange._ensure_markets_loaded()
        market = exchange.client.market(symbol) or {}
        native = str(market.get("id") or "").strip().upper()
        if native:
            return native
    except Exception:
        pass
    return _guess_native_futures_symbol(symbol)


async def _run_futures_roundtrip(body: Dict[str, Any]) -> Dict[str, Any]:
    from quant.exchange import CCXTExchange
    from quant.kucoin_native import KuCoinNativeClient

    account_id = _resolve_live_futures_account_id(body)
    symbol = str(body.get("symbol") or "BTC/USDT:USDT").strip()
    side = str(body.get("side") or "buy").lower()
    contracts = int(_num(body.get("contracts"), 1))
    leverage = int(_num(body.get("leverage"), 10))
    margin_mode = str(body.get("marginMode") or "CROSS").upper()
    position_mode = str(body.get("positionMode") or "HEDGE").upper()
    max_notional_usd = min(_num(body.get("maxNotionalUsd"), 100), _MAX_DASHBOARD_FUTURES_NOTIONAL)
    max_margin_usd = min(_num(body.get("maxMarginUsd"), 10), _MAX_DASHBOARD_FUTURES_MARGIN)

    if side not in {"buy", "sell"}:
        return {"ok": False, "message": "side 只能是 buy 或 sell"}
    if contracts <= 0 or leverage <= 0:
        return {"ok": False, "message": "contracts/leverage 必须为正数"}
    if margin_mode not in {"CROSS", "ISOLATED"}:
        return {"ok": False, "message": "marginMode 只能是 CROSS 或 ISOLATED"}
    if position_mode not in {"HEDGE", "ONE_WAY"}:
        return {"ok": False, "message": "positionMode 只能是 HEDGE 或 ONE_WAY"}

    with _temporary_env({"QUANT_LIVE_TRADING": "true", "QUANT_EXCHANGE_SANDBOX": "false"}):
        exchange = CCXTExchange(exchange_id="kucoinfutures", market_type="swap", sandbox=False, account_id=account_id)
        try:
            await exchange._ensure_markets_loaded()
            market = exchange.client.market(symbol) or {}
            ticker = await exchange.client.fetch_ticker(symbol)
            price = _num(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
            contract_size = _num(market.get("contractSize"), 1.0)
            notional_usd = abs(contracts * contract_size * price)
            estimated_margin_usd = notional_usd / leverage if leverage else notional_usd
            native_enabled = os.getenv("QUANT_KUCOIN_NATIVE_REST", "true").lower() in {"1", "true", "yes", "y", "on"}
            native = KuCoinNativeClient("futures", account_id=account_id) if native_enabled else None
            if native:
                balance_response = await native.futures_account_overview("USDT")
                balance_data = balance_response.get("data") if _native_order_ok(balance_response) else {}
                free_usdt = _num((balance_data or {}).get("availableBalance"))
            else:
                balance = await exchange.client.fetch_balance()
                free_usdt = _num((balance.get("free") or {}).get("USDT"))
            preflight = {
                "account_id": account_id,
                "symbol": symbol,
                "execution_provider": "kucoin_native_rest" if native else "ccxt",
                "side": side,
                "contracts": contracts,
                "leverage": leverage,
                "margin_mode": margin_mode,
                "position_mode": position_mode,
                "price": price,
                "contract_size": contract_size,
                "notional_usd": round(notional_usd, 8),
                "estimated_margin_usd": round(estimated_margin_usd, 8),
                "free_usdt": free_usdt,
                "max_notional_usd": max_notional_usd,
                "max_margin_usd": max_margin_usd,
            }
            if price <= 0:
                return {"ok": False, "status": "preflight_failed", "reason": "invalid ticker price", "preflight": preflight}
            if notional_usd > max_notional_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "notional exceeds max", "preflight": preflight}
            if estimated_margin_usd > max_margin_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "estimated margin exceeds max", "preflight": preflight}
            if free_usdt < estimated_margin_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "insufficient futures USDT margin", "preflight": preflight}
            if native:
                native_symbol = await _resolve_native_futures_symbol(exchange, symbol)
                position_side = _futures_position_side(side, position_mode)
                preflight["native_symbol"] = native_symbol
                preflight["position_side"] = position_side
                open_response = await native.futures_order(
                    native_symbol,
                    side,
                    size=contracts,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    position_side=position_side,
                    reduce_only=False,
                    remark="dashboard-native-roundtrip-open",
                )
                if not _native_order_ok(open_response):
                    return {
                        "ok": False,
                        "status": "open_failed",
                        "preflight": preflight,
                        "open_error": _native_error_text(open_response),
                        "open_response": open_response,
                    }
                open_order_id = str((open_response.get("data") or {}).get("orderId") or "")
                open_detail = await native.futures_order_detail(open_order_id) if open_order_id else {}
                open_order = _native_futures_order_to_row(
                    response=open_response,
                    detail=open_detail,
                    symbol=symbol,
                    native_symbol=native_symbol,
                    side=side,
                    contracts=contracts,
                )
                close_side = "sell" if side == "buy" else "buy"
                close_response = await native.futures_order(
                    native_symbol,
                    close_side,
                    size=contracts,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    position_side=position_side,
                    reduce_only=True,
                    remark="dashboard-native-roundtrip-close",
                )
                if not _native_order_ok(close_response):
                    _append_live_rows([_futures_ledger_row(
                        order=open_order,
                        symbol=symbol,
                        action=side,
                        contracts=contracts,
                        price=price,
                        contract_size=contract_size,
                        notional_usd=notional_usd,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        position_mode=position_mode,
                    )])
                    return {
                        "ok": False,
                        "status": "close_failed",
                        "preflight": preflight,
                        "open_order": {
                            "id": open_order.get("id"),
                            "status": open_order.get("status"),
                            "side": open_order.get("side"),
                            "amount": open_order.get("amount"),
                        },
                        "close_error": _native_error_text(close_response),
                        "close_response": close_response,
                    }
                close_order_id = str((close_response.get("data") or {}).get("orderId") or "")
                close_detail = await native.futures_order_detail(close_order_id) if close_order_id else {}
                close_order = _native_futures_order_to_row(
                    response=close_response,
                    detail=close_detail,
                    symbol=symbol,
                    native_symbol=native_symbol,
                    side=close_side,
                    contracts=contracts,
                )
                _append_live_rows([
                    _futures_ledger_row(
                        order=open_order,
                        symbol=symbol,
                        action=side,
                        contracts=contracts,
                        price=price,
                        contract_size=contract_size,
                        notional_usd=notional_usd,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        position_mode=position_mode,
                    ),
                    _futures_ledger_row(
                        order=close_order,
                        symbol=symbol,
                        action=close_side,
                        contracts=contracts,
                        price=price,
                        contract_size=contract_size,
                        notional_usd=notional_usd,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        position_mode=position_mode,
                    ),
                ])
                return {
                    "ok": True,
                    "status": "submitted",
                    "preflight": preflight,
                    "open_order": {
                        "id": open_order.get("id"),
                        "status": open_order.get("status"),
                        "side": open_order.get("side"),
                        "amount": open_order.get("amount"),
                    },
                    "close_order": {
                        "id": close_order.get("id"),
                        "status": close_order.get("status"),
                        "side": close_order.get("side"),
                        "amount": close_order.get("amount"),
                    },
                }
            try:
                await exchange.client.set_leverage(leverage, symbol)
            except Exception as exc:
                preflight["set_leverage_warning"] = str(exc)
            try:
                if hasattr(exchange.client, "set_margin_mode"):
                    await exchange.client.set_margin_mode(margin_mode, symbol)
            except Exception as exc:
                preflight["set_margin_mode_warning"] = str(exc)
            order_params = {"leverage": leverage, "marginMode": margin_mode, "hedged": position_mode == "HEDGE"}
            open_order = await exchange.client.create_order(symbol=symbol, type="market", side=side, amount=contracts, price=None, params=order_params)
            open_order = await _fetch_order_safely(exchange.client, open_order, symbol)
            close_side = "sell" if side == "buy" else "buy"
            try:
                close_order = await exchange.client.create_order(symbol=symbol, type="market", side=close_side, amount=contracts, price=None, params={**order_params, "reduceOnly": True})
                close_order = await _fetch_order_safely(exchange.client, close_order, symbol)
            except Exception as exc:
                _append_live_rows([_futures_ledger_row(
                    order=open_order,
                    symbol=symbol,
                    action=side,
                    contracts=contracts,
                    price=price,
                    contract_size=contract_size,
                    notional_usd=notional_usd,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    position_mode=position_mode,
                )])
                return {
                    "ok": False,
                    "status": "close_failed",
                    "preflight": preflight,
                    "open_order": {
                        "id": open_order.get("id") or (open_order.get("info") or {}).get("orderId"),
                        "status": open_order.get("status"),
                        "side": open_order.get("side"),
                        "amount": open_order.get("amount"),
                    },
                    "close_error": str(exc),
                }
            _append_live_rows([
                _futures_ledger_row(
                    order=open_order,
                    symbol=symbol,
                    action=side,
                    contracts=contracts,
                    price=price,
                    contract_size=contract_size,
                    notional_usd=notional_usd,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    position_mode=position_mode,
                ),
                _futures_ledger_row(
                    order=close_order,
                    symbol=symbol,
                    action=close_side,
                    contracts=contracts,
                    price=price,
                    contract_size=contract_size,
                    notional_usd=notional_usd,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    position_mode=position_mode,
                ),
            ])
            return {
                "ok": True,
                "status": "submitted",
                "preflight": preflight,
                "open_order": {
                    "id": open_order.get("id") or (open_order.get("info") or {}).get("orderId"),
                    "status": open_order.get("status"),
                    "side": open_order.get("side"),
                    "amount": open_order.get("amount"),
                },
                "close_order": {
                    "id": close_order.get("id") or (close_order.get("info") or {}).get("orderId"),
                    "status": close_order.get("status"),
                    "side": close_order.get("side"),
                    "amount": close_order.get("amount"),
                },
            }
        finally:
            await exchange.close()


async def _run_futures_order(body: Dict[str, Any]) -> Dict[str, Any]:
    from quant.exchange import CCXTExchange
    from quant.kucoin_native import KuCoinNativeClient

    account_id = _resolve_live_futures_account_id(body)
    symbol = str(body.get("symbol") or "BTC/USDT:USDT").strip()
    side = str(body.get("side") or "buy").lower()
    contracts = int(_num(body.get("contracts"), 1))
    leverage = int(_num(body.get("leverage"), 10))
    margin_mode = str(body.get("marginMode") or "CROSS").upper()
    position_mode = str(body.get("positionMode") or "HEDGE").upper()
    reduce_only = bool(body.get("reduceOnly"))
    order_type = str(body.get("orderType") or body.get("order_type") or "market").lower()
    limit_price = body.get("price")
    max_notional_usd = min(_num(body.get("maxNotionalUsd"), 100), _MAX_DASHBOARD_FUTURES_NOTIONAL)
    max_margin_usd = min(_num(body.get("maxMarginUsd"), 10), _MAX_DASHBOARD_FUTURES_MARGIN)

    if side not in {"buy", "sell"}:
        return {"ok": False, "message": "side 只能是 buy 或 sell"}
    if contracts <= 0 or leverage <= 0:
        return {"ok": False, "message": "contracts/leverage 必须为正数"}
    if order_type == "limit" and not limit_price:
        return {"ok": False, "message": "限价单必须提供 price"}
    if margin_mode not in {"CROSS", "ISOLATED"}:
        return {"ok": False, "message": "marginMode 只能是 CROSS 或 ISOLATED"}
    if position_mode not in {"HEDGE", "ONE_WAY"}:
        return {"ok": False, "message": "positionMode 只能是 HEDGE 或 ONE_WAY"}

    with _temporary_env({"QUANT_LIVE_TRADING": "true", "QUANT_EXCHANGE_SANDBOX": "false"}):
        exchange = CCXTExchange(exchange_id="kucoinfutures", market_type="swap", sandbox=False, account_id=account_id)
        try:
            await exchange._ensure_markets_loaded()
            market = exchange.client.market(symbol) or {}
            ticker = await exchange.client.fetch_ticker(symbol)
            price = _num(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
            contract_size = _num(market.get("contractSize"), 1.0)
            notional_usd = abs(contracts * contract_size * price)
            estimated_margin_usd = notional_usd / leverage if leverage else notional_usd
            native_enabled = os.getenv("QUANT_KUCOIN_NATIVE_REST", "true").lower() in {"1", "true", "yes", "y", "on"}
            native = KuCoinNativeClient("futures", account_id=account_id) if native_enabled else None

            if native:
                balance_response = await native.futures_account_overview("USDT")
                balance_data = balance_response.get("data") if _native_order_ok(balance_response) else {}
                free_usdt = _num((balance_data or {}).get("availableBalance"))
            else:
                balance = await exchange.client.fetch_balance()
                free_usdt = _num((balance.get("free") or {}).get("USDT"))

            preflight = {
                "account_id": account_id,
                "symbol": symbol,
                "execution_provider": "kucoin_native_rest" if native else "ccxt",
                "side": side,
                "contracts": contracts,
                "leverage": leverage,
                "margin_mode": margin_mode,
                "position_mode": position_mode,
                "reduce_only": reduce_only,
                "price": price,
                "contract_size": contract_size,
                "notional_usd": round(notional_usd, 8),
                "estimated_margin_usd": round(estimated_margin_usd, 8),
                "free_usdt": free_usdt,
                "max_notional_usd": max_notional_usd,
                "max_margin_usd": max_margin_usd,
            }
            if price <= 0:
                return {"ok": False, "status": "preflight_failed", "reason": "invalid ticker price", "preflight": preflight}
            if notional_usd > max_notional_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "notional exceeds max", "preflight": preflight}
            if estimated_margin_usd > max_margin_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "estimated margin exceeds max", "preflight": preflight}
            if not reduce_only and free_usdt < estimated_margin_usd:
                return {"ok": False, "status": "preflight_failed", "reason": "insufficient futures USDT margin", "preflight": preflight}

            if native:
                native_symbol = await _resolve_native_futures_symbol(exchange, symbol)
                position_side = _futures_position_side(side, position_mode)
                preflight["native_symbol"] = native_symbol
                preflight["position_side"] = position_side
                response = await native.futures_order(
                    native_symbol,
                    side,
                    size=contracts,
                    leverage=leverage,
                    order_type=order_type if order_type in {"market", "limit"} else "market",
                    price=str(limit_price) if order_type == "limit" and limit_price else None,
                    margin_mode=margin_mode,
                    position_side=position_side,
                    reduce_only=reduce_only,
                    remark="dashboard-native-futures-order",
                )
                if not _native_order_ok(response):
                    return {
                        "ok": False,
                        "status": "submit_failed",
                        "preflight": preflight,
                        "error": _native_error_text(response),
                        "response": response,
                    }

                order_id = str((response.get("data") or {}).get("orderId") or "")
                detail = await native.futures_order_detail(order_id) if order_id else {}
                order = _native_futures_order_to_row(
                    response=response,
                    detail=detail,
                    symbol=symbol,
                    native_symbol=native_symbol,
                    side=side,
                    contracts=contracts,
                )
            else:
                try:
                    await exchange.client.set_leverage(leverage, symbol)
                except Exception as exc:
                    preflight["set_leverage_warning"] = str(exc)
                try:
                    if hasattr(exchange.client, "set_margin_mode"):
                        await exchange.client.set_margin_mode(margin_mode, symbol)
                except Exception as exc:
                    preflight["set_margin_mode_warning"] = str(exc)
                order_params = {
                    "leverage": leverage,
                    "marginMode": margin_mode,
                    "hedged": position_mode == "HEDGE",
                    "reduceOnly": reduce_only,
                }
                ccxt_type = order_type if order_type in {"market", "limit"} else "market"
                ccxt_price = _num(limit_price) if ccxt_type == "limit" and limit_price else None
                order = await exchange.client.create_order(
                    symbol=symbol,
                    type=ccxt_type,
                    side=side,
                    amount=contracts,
                    price=ccxt_price,
                    params=order_params,
                )
                order = await _fetch_order_safely(exchange.client, order, symbol)

            ledger_row = _futures_ledger_row(
                order=order,
                symbol=symbol,
                action=side,
                contracts=contracts,
                price=price,
                contract_size=contract_size,
                notional_usd=notional_usd,
                leverage=leverage,
                margin_mode=margin_mode,
                position_mode=position_mode,
            )
            _append_live_rows([ledger_row])

            return {
                "ok": True,
                "status": "submitted",
                "preflight": preflight,
                "order": {
                    "id": order.get("id") or (order.get("info") or {}).get("orderId"),
                    "status": order.get("status"),
                    "side": order.get("side"),
                    "amount": order.get("amount"),
                    "reduce_only": reduce_only,
                },
                "ledger": _compact_order_result([ledger_row]),
            }
        finally:
            await exchange.close()


async def _run_futures_order_test(body: Dict[str, Any]) -> Dict[str, Any]:
    """Submit KuCoin futures test order (no real fill, no fund transfer)."""
    from quant.exchange import CCXTExchange
    from quant.kucoin_native import KuCoinNativeClient

    account_id = _resolve_live_futures_account_id(body)
    symbol = str(body.get("symbol") or "BTC/USDT:USDT").strip()
    side = str(body.get("side") or "buy").lower()
    contracts = int(_num(body.get("contracts"), 1))
    leverage = int(_num(body.get("leverage"), 10))
    margin_mode = str(body.get("marginMode") or "CROSS").upper()
    position_mode = str(body.get("positionMode") or "HEDGE").upper()

    if side not in {"buy", "sell"}:
        return {"ok": False, "message": "side 只能是 buy 或 sell"}
    if contracts <= 0 or leverage <= 0:
        return {"ok": False, "message": "contracts/leverage 必须为正数"}
    if margin_mode not in {"CROSS", "ISOLATED"}:
        return {"ok": False, "message": "marginMode 只能是 CROSS 或 ISOLATED"}
    if position_mode not in {"HEDGE", "ONE_WAY"}:
        return {"ok": False, "message": "positionMode 只能是 HEDGE 或 ONE_WAY"}

    with _temporary_env({"QUANT_LIVE_TRADING": "true", "QUANT_EXCHANGE_SANDBOX": "false"}):
        exchange = CCXTExchange(exchange_id="kucoinfutures", market_type="swap", sandbox=False, account_id=account_id)
        try:
            await exchange._ensure_markets_loaded()
            market = exchange.client.market(symbol) or {}
            ticker = await exchange.client.fetch_ticker(symbol)
            price = _num(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
            contract_size = _num(market.get("contractSize"), 1.0)
            notional_usd = abs(contracts * contract_size * price)
            estimated_margin_usd = notional_usd / leverage if leverage else notional_usd

            if price <= 0:
                return {"ok": False, "status": "preflight_failed", "reason": "invalid ticker price"}

            native = KuCoinNativeClient("futures", account_id=account_id)
            native_symbol = await _resolve_native_futures_symbol(exchange, symbol)
            position_side = _futures_position_side(side, position_mode)
            response = await native.futures_order_test(
                native_symbol,
                side,
                size=contracts,
                leverage=leverage,
                margin_mode=margin_mode,
                position_side=position_side,
            )
            preflight = {
                "account_id": account_id,
                "symbol": symbol,
                "native_symbol": native_symbol,
                "execution_provider": "kucoin_native_rest",
                "side": side,
                "contracts": contracts,
                "leverage": leverage,
                "margin_mode": margin_mode,
                "position_mode": position_mode,
                "position_side": position_side,
                "price": price,
                "contract_size": contract_size,
                "notional_usd": round(notional_usd, 8),
                "estimated_margin_usd": round(estimated_margin_usd, 8),
            }

            if not _native_order_ok(response):
                return {
                    "ok": False,
                    "status": "test_failed",
                    "preflight": preflight,
                    "error": _native_error_text(response),
                    "response": response,
                }

            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            return {
                "ok": True,
                "status": "tested",
                "preflight": preflight,
                "test_order": {
                    "order_id": data.get("orderId") or data.get("id") or "",
                    "raw": response,
                },
                "note": "这是 test order 验证，不会真实成交，也不会写入实盘成交流水。",
            }
        finally:
            await exchange.close()


class LiveTradingApi(BaseRouter):
    """Live trading endpoints under /api/dashboard/live/*"""

    def __init__(self):
        super().__init__()

        @self._router.get("/dashboard/live/summary")
        async def live_summary(days: int = 30):
            rows = _load_trade_rows(days=days)
            status_counts: Dict[str, int] = {}
            symbols = set()
            filled_usd = 0.0
            requested_usd = 0.0
            fee_total = 0.0
            live_rows = []
            dry_run_rows = []
            for row in rows:
                status = str(row.get("status") or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                if row.get("symbol"):
                    symbols.add(str(row.get("symbol")))
                requested_usd += _num(row.get("order_usd"))
                filled_usd += _trade_filled_usd(row)
                fee_total += _trade_fee(row)
                if row.get("dry_run"):
                    dry_run_rows.append(row)
                else:
                    live_rows.append(row)
            fifo = _spot_fifo_summary(live_rows)
            return JSONResponse({
                "ok": True,
                "days": days,
                "total_records": len(rows),
                "live_records": len(live_rows),
                "dry_run_records": len(dry_run_rows),
                "status_counts": status_counts,
                "symbols": sorted(symbols),
                "requested_usd": round(requested_usd, 8),
                "filled_usd": round(filled_usd, 8),
                "fee_total": round(fee_total, 8),
                "realized_pnl_usd": fifo["realized_pnl_usd"],
                "performance": fifo["performance"],
                "open_positions": fifo["open_positions"],
                "realized_curve": fifo["realized_curve"],
                "recent_trades": _compact_order_result(rows[-50:][::-1]),
                "pnl_note": "当前只按现货买卖成交做 FIFO 已实现盈亏；未平仓浮盈亏、Earn 收益、合约资金费率和人工交易尚未纳入。",
            })

        @self._router.get("/dashboard/live/valuescan-context")
        async def live_valuescan_context(request: Request, symbols: str = "BTC,ETH"):
            """ValueScan 大盘情绪 + 监控币种追踪摘要（实盘控制台用）。"""
            from web.api.dashboard_service import fetch_market_stats
            from web.api.valuescan_signal_digest import fetch_multi_symbol_digest

            raw = [s.strip() for s in (symbols or "BTC,ETH").replace(";", ",").split(",") if s.strip()]
            bases = []
            seen: set[str] = set()
            for item in raw:
                sym = item.upper().split("-")[0].split("/")[0]
                if sym and sym not in seen:
                    seen.add(sym)
                    bases.append(sym)
            if not bases:
                bases = ["BTC", "ETH"]

            marks: Dict[str, float] = {}
            for sym in bases:
                try:
                    market = await fetch_market_stats(f"{sym}-USDT")
                    marks[sym] = float(market.get("last") or 0)
                except Exception:
                    marks[sym] = 0.0

            try:
                from web.api.valuescan_sse_worker import get_worker_status, update_watch_symbols

                await update_watch_symbols(bases)
                bundle = await fetch_multi_symbol_digest(bases, marks)
                bundle["sseWorker"] = get_worker_status()
                return JSONResponse({"ok": True, **bundle})
            except Exception as exc:
                logger.exception("live valuescan context failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)

        @self._router.get("/dashboard/live/position-vs-alerts")
        async def live_position_vs_alerts(
            request: Request,
            accountId: str = "",
            symbols: str = "",
        ):
            """持仓 × ValueScan 风险/机会/SSE 实时告警。"""
            from web.api.position_vs_alerts import build_position_vs_alerts

            account_id = (accountId or "").strip() or _resolve_live_futures_account_id({})
            extra = [s.strip() for s in (symbols or "").replace(";", ",").split(",") if s.strip()]
            try:
                payload = await build_position_vs_alerts(account_id, extra_symbols=extra)
                return JSONResponse(payload)
            except Exception as exc:
                logger.exception("position vs alerts failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)

        @self._router.get("/dashboard/live/vs-sse-status")
        async def live_vs_sse_status():
            from web.api.valuescan_sse_worker import get_worker_status

            return JSONResponse({"ok": True, **get_worker_status()})

        @self._router.get("/dashboard/live/kucoin-accounts")
        async def live_kucoin_accounts(scope: str = ""):
            from quant.kucoin_native import KuCoinNativeClient

            if scope.lower() == "futures":
                account_ids = [_live_futures_account_id()]
            else:
                account_ids = _configured_kucoin_account_ids()
            accounts = []
            for account_id in account_ids:
                client = KuCoinNativeClient("spot", account_id=account_id)
                accounts.append({
                    "account_id": account_id,
                    "api_key_tail": client.api_key_tail,
                    "has_credentials": bool(client.api_key and client.api_secret and client.api_passphrase),
                    "locked": scope.lower() == "futures",
                })
            return JSONResponse({
                "ok": True,
                "accounts": accounts,
                "default_account_id": _live_futures_account_id() if scope.lower() == "futures" else "",
            })

        @self._router.get("/dashboard/live/account")
        async def live_account(market: str = "spot", symbols: str = "KCS/USDT,BTC/USDT", accountId: str = ""):
            from quant.exchange import CCXTExchange
            from quant.kucoin_native import KuCoinNativeClient
            from quant.live_trader import LiveTrader

            market_normalized = market.lower()
            symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]
            requested_accounts = [item.strip().lower() for item in str(accountId or "").split(",") if item.strip()]
            if market_normalized in {"futures", "swap"}:
                account_ids = [_live_futures_account_id()]
            else:
                account_ids = requested_accounts or _configured_kucoin_account_ids()

            async def read_one_account(account_id: str) -> Dict[str, Any]:
                compact_balance: Dict[str, Any] = {"assets": []}
                positions: List[Dict[str, Any]] = []
                open_order_count = 0
                native_message = ""
                native_error = ""
                ccxt_error = ""
                provider = "kucoin_native_rest"
                native_client = KuCoinNativeClient("futures" if market_normalized in {"futures", "swap"} else "spot", account_id=account_id)
                try:
                    if market_normalized in {"futures", "swap"}:
                        native_response = await native_client.futures_account_overview("USDT")
                        native_message = native_response.get("msg") or native_response.get("message") or ""
                        if str(native_response.get("code")) == "200000":
                            compact_balance = _compact_native_futures_overview(native_response.get("data") or {})
                    else:
                        native_response = await native_client.spot_accounts()
                        native_message = native_response.get("msg") or native_response.get("message") or ""
                        if str(native_response.get("code")) == "200000":
                            compact_balance = _compact_native_spot_accounts(native_response.get("data") or [])
                except Exception as exc:
                    native_error = str(exc)
                    provider = "ccxt"
                    logger.warning("live account KuCoin native snapshot failed, falling back to CCXT: account=%s %s", account_id, exc)

                if not compact_balance.get("assets"):
                    trader = None
                    try:
                        if market_normalized in {"futures", "swap"}:
                            exchange = CCXTExchange(exchange_id="kucoinfutures", market_type="swap", sandbox=False, account_id=account_id)
                        else:
                            exchange = CCXTExchange(exchange_id="kucoin", market_type="spot", sandbox=False, account_id=account_id)
                        trader = LiveTrader(exchange=exchange, dry_run=True, account_id=account_id)
                        snapshot = await trader.get_account_snapshot(symbol_list)
                        compact_balance = _compact_balance(snapshot.get("balance") or {})
                        positions = snapshot.get("positions") or []
                        open_order_count = len(snapshot.get("openOrders") or [])
                        if compact_balance.get("assets"):
                            provider = "kucoin_native_rest+ccxt_fallback" if native_error or native_message else "ccxt"
                    except Exception as exc:
                        ccxt_error = str(exc)
                        logger.warning("live account CCXT fallback failed: account=%s %s", account_id, exc)
                    finally:
                        if trader is not None:
                            await trader.close()

                return {
                    "account_id": account_id,
                    "account_profile": {
                        "account_id": account_id,
                        "api_key_tail": native_client.api_key_tail,
                        "execution_provider": provider,
                        "sandbox": False,
                        "live_trading_env": os.getenv("QUANT_LIVE_TRADING", "").lower() == "true",
                        "native_error": native_error,
                        "native_message": native_message,
                        "ccxt_error": ccxt_error,
                    },
                    "balance": compact_balance,
                    "positions": positions,
                    "open_order_count": open_order_count,
                }

            accounts = [await read_one_account(account_id) for account_id in account_ids]
            primary = next((item for item in accounts if (item.get("balance") or {}).get("assets")), accounts[0] if accounts else {})

            if accounts and all(not (item.get("balance") or {}).get("assets") for item in accounts):
                profile = primary.get("account_profile") or {}
                message = profile.get("native_error") or profile.get("ccxt_error") or profile.get("native_message") or "未读到账户资产"
                return JSONResponse({"ok": False, "message": message, "accounts": accounts}, status_code=502)

            # 为非 USDT 资产附加 USDT 折算值
            await _enrich_assets_usdt_value(accounts)

            return JSONResponse({
                "ok": True,
                "market": market_normalized,
                "account_profile": primary.get("account_profile") or {},
                "balance": primary.get("balance") or {"assets": []},
                "positions": primary.get("positions") or [],
                "open_order_count": primary.get("open_order_count") or 0,
                "accounts": accounts,
            })

        @self._router.get("/dashboard/live/earn")
        async def live_earn(currency: str = "KCS"):
            from quant.kucoin_native import KuCoinNativeClient

            client = KuCoinNativeClient("spot")
            try:
                current_page = 1
                page_size = 20
                holdings = await client.request("GET", "/api/v1/earn/hold-assets", params={"currency": currency, "currentPage": current_page, "pageSize": page_size}, auth=True, timeout=20)
                savings = await client.request("GET", "/api/v1/earn/saving/products", params={"currency": currency, "currentPage": current_page, "pageSize": page_size}, auth=True, timeout=20)
                kcs_staking = await client.request("GET", "/api/v1/earn/kcs-staking/products", params={"currency": currency, "currentPage": current_page, "pageSize": page_size}, auth=True, timeout=20)
                return JSONResponse({
                    "ok": True,
                    "currency": currency,
                    "holdings": holdings,
                    "savings": savings,
                    "kcs_staking": kcs_staking,
                    "write_supported": False,
                    "write_note": "当前 KuCoin Earn 本地 skill 只覆盖 GET 只读接口；申购/赎回写接口尚未接入，不能从 dashboard 直接操作理财。",
                })
            except Exception as exc:
                logger.exception("live earn query failed")
                return JSONResponse({"ok": False, "message": str(exc), "write_supported": False}, status_code=502)

        @self._router.post("/dashboard/live/spot-order")
        async def live_spot_order(request: Request):
            from quant.live_trader import LiveTrader

            body = await request.json()
            symbol = str(body.get("symbol") or "KCS/USDT").strip().upper().replace("-", "/")
            side = str(body.get("side") or "sell").lower()
            usd = _num(body.get("usd"), 1.0)
            max_usd = min(_num(body.get("maxUsd"), 2.0), _MAX_DASHBOARD_SPOT_USD)
            confirm_live = str(body.get("confirmLive") or "")
            if confirm_live != "CONFIRM":
                return JSONResponse({"ok": False, "message": "真实下单必须输入 CONFIRM"}, status_code=400)
            if side not in {"buy", "sell"}:
                return JSONResponse({"ok": False, "message": "side 只能是 buy 或 sell"}, status_code=400)
            if usd <= 0 or max_usd <= 0 or usd > max_usd:
                return JSONResponse({"ok": False, "message": "usd 必须为正数且不能超过 maxUsd"}, status_code=400)
            with _temporary_env({
                "QUANT_LIVE_TRADING": "true",
                "QUANT_EXCHANGE_SANDBOX": "false",
                "QUANT_EXCHANGE_ID": "kucoin",
                "QUANT_MARKET_TYPE": "spot",
                "QUANT_REQUIRE_PROTECTIVE_ORDERS": "false",
            }):
                trader = LiveTrader(dry_run=False, max_order_usd=max_usd)
                try:
                    price = await trader.exchange.get_ticker_price(symbol)
                    if not price or price <= 0:
                        return JSONResponse({"ok": False, "message": f"无法获取价格: {price}"}, status_code=502)
                    quantity = usd / price
                    decision = {
                        "symbol": symbol,
                        "action": side,
                        "quantity": quantity,
                        "quote_amount": usd if side == "buy" else None,
                        "price": price,
                        "confidence": 1.0,
                        "stop_loss": price * 0.98 if side == "buy" else None,
                        "take_profit": price * 1.02 if side == "buy" else None,
                        "rationale": "dashboard tiny live spot connectivity test",
                    }
                    result = await trader.execute_decisions([decision], {symbol: price})
                    return JSONResponse({"ok": True, "price": price, "result": _compact_order_result(result)})
                except Exception as exc:
                    logger.exception("live spot order failed")
                    return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)
                finally:
                    await trader.close()

        @self._router.post("/dashboard/live/futures-roundtrip")
        async def live_futures_roundtrip(request: Request):
            body = await request.json()
            confirm_live = str(body.get("confirmLive") or "")
            if confirm_live != "CONFIRM":
                return JSONResponse({"ok": False, "message": "真实合约下单必须输入 CONFIRM"}, status_code=400)
            try:
                result = await _run_futures_roundtrip(body)
                return JSONResponse(result, status_code=200 if result.get("ok") else 422)
            except Exception as exc:
                logger.exception("live futures roundtrip failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/futures-order")
        async def live_futures_order(request: Request):
            body = await request.json()
            confirm_live = str(body.get("confirmLive") or "")
            if confirm_live != "CONFIRM":
                return JSONResponse({"ok": False, "message": "真实合约下单必须输入 CONFIRM"}, status_code=400)
            try:
                result = await _run_futures_order(body)
                return JSONResponse(result, status_code=200 if result.get("ok") else 422)
            except Exception as exc:
                logger.exception("live futures order failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/futures-order-test")
        async def live_futures_order_test(request: Request):
            body = await request.json()
            try:
                result = await _run_futures_order_test(body)
                return JSONResponse(result, status_code=200 if result.get("ok") else 422)
            except Exception as exc:
                logger.exception("live futures test order failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/llm-futures-run")
        async def live_llm_futures_run(request: Request):
            from web.api.llm_futures_executor import run_llm_futures_batch

            body = await request.json()
            try:
                result = await run_llm_futures_batch(body)
                status_code = 200 if result.get("ok") else 400
                return JSONResponse(result, status_code=status_code)
            except Exception as exc:
                logger.exception("llm futures run failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/llm-futures/start")
        async def live_llm_futures_start(request: Request):
            from web.api.llm_futures_runner import start_runner

            body = await request.json()
            try:
                status = await start_runner(body)
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("llm futures runner start failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/llm-futures/stop")
        async def live_llm_futures_stop():
            from web.api.llm_futures_runner import stop_runner

            try:
                status = await stop_runner()
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("llm futures runner stop failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.get("/dashboard/live/llm-futures/status")
        async def live_llm_futures_status():
            from web.api.llm_futures_runner import get_status

            return JSONResponse({"ok": True, **get_status()})

        @self._router.post("/dashboard/live/automation/run")
        async def live_automation_run(request: Request):
            from web.api.live_automation import run_live_automation_round

            body = await request.json()
            try:
                result = await run_live_automation_round(body)
                status_code = 200 if result.get("ok", True) else 400
                return JSONResponse(result, status_code=status_code)
            except Exception as exc:
                logger.exception("live automation run failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/automation/start")
        async def live_automation_start(request: Request):
            from web.api.live_automation_runner import start_runner

            body = await request.json()
            try:
                status = await start_runner(body)
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("live automation start failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/automation/stop")
        async def live_automation_stop():
            from web.api.live_automation_runner import stop_runner

            try:
                status = await stop_runner()
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("live automation stop failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.get("/dashboard/live/automation/status")
        async def live_automation_status():
            from web.api.live_automation_runner import get_status

            return JSONResponse({"ok": True, **get_status()})

        async def _spot_transfer_source(native: Any, currency: str, amount: float) -> tuple[str, float]:
            """Pick trade/main spot wallet with enough balance for inner-transfer to contract."""
            accounts = await native.spot_accounts(currency=currency)
            balances: Dict[str, float] = {}
            if str(accounts.get("code")) == "200000":
                for row in accounts.get("data") or []:
                    account_type = str(row.get("type") or "").lower()
                    if account_type in {"trade", "main"}:
                        balances[account_type] = max(balances.get(account_type, 0.0), _num(row.get("available") or row.get("balance")))
            for source in ("trade", "main"):
                available = balances.get(source, 0.0)
                if available >= amount:
                    return source, available
            return "", max(balances.get("trade", 0.0), balances.get("main", 0.0))

        @self._router.post("/dashboard/live/transfer-futures")
        async def live_transfer_futures(request: Request):
            from quant.kucoin_native import KuCoinNativeClient

            body = await request.json()
            currency = str(body.get("currency") or "USDT").strip().upper()
            amount = _num(body.get("amount"), 0.0)
            max_amount = min(_num(body.get("maxAmount"), 10.0), _MAX_DASHBOARD_TRANSFER_USD)
            account_id = _resolve_live_futures_account_id(body)
            confirm_live = str(body.get("confirmLive") or "")
            if confirm_live != "CONFIRM":
                return JSONResponse({"ok": False, "message": "真实划转必须输入 CONFIRM"}, status_code=400)
            if currency != "USDT":
                return JSONResponse({"ok": False, "message": "dashboard 当前只允许 USDT 划转到合约账户"}, status_code=400)
            if amount <= 0 or amount > max_amount:
                return JSONResponse({"ok": False, "message": "amount 必须为正数且不能超过 maxAmount"}, status_code=400)

            native = KuCoinNativeClient("spot", account_id=account_id)
            try:
                from_account, available = await _spot_transfer_source(native, currency, amount)
                if not from_account:
                    return JSONResponse({
                        "ok": False,
                        "status": "preflight_failed",
                        "reason": "spot main/trade balance insufficient",
                        "currency": currency,
                        "amount": amount,
                        "available": available,
                        "account_id": account_id,
                    }, status_code=422)
                amount_text = f"{amount:.8f}".rstrip("0").rstrip(".")
                transfer = await native.request(
                    "POST",
                    "/api/v2/accounts/inner-transfer",
                    body={
                        "clientOid": f"dashboard-transfer-{uuid.uuid4().hex[:24]}",
                        "currency": currency,
                        "amount": amount_text,
                        "from": from_account,
                        "to": "contract",
                    },
                    auth=True,
                    timeout=20,
                )
                if str(transfer.get("code")) != "200000":
                    return JSONResponse({
                        "ok": False,
                        "status": "transfer_failed",
                        "currency": currency,
                        "amount": amount,
                        "available": available,
                        "account_id": account_id,
                        "from": from_account,
                        "transfer": transfer,
                    }, status_code=502)
                futures = KuCoinNativeClient("futures", account_id=account_id)
                overview = await futures.request("GET", "/api/v1/account-overview", params={"currency": currency}, auth=True, timeout=20)
                return JSONResponse({
                    "ok": True,
                    "currency": currency,
                    "amount": amount,
                    "account_id": account_id,
                    "from": from_account,
                    "to": "contract",
                    "transfer": transfer,
                    "futures_account": overview,
                })
            except Exception as exc:
                logger.exception("live futures transfer failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/paper-arena/run")
        async def live_paper_arena_run(request: Request):
            from quant.paper_arena import run_strategy_paper_arena

            body = await request.json()
            symbol = str(body.get("symbol") or "BTC-USDT").strip().upper()
            if "-" not in symbol and "/" not in symbol:
                symbol = f"{symbol}-USDT"
            kline_type = {"15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}.get(str(body.get("type") or "1hour"), "1hour")
            limit = max(80, min(5000, int(_num(body.get("limit"), 500))))
            initial_cash = max(10.0, _num(body.get("initialCash"), 10000.0))
            allocation_pct = max(0.01, min(1.0, _num(body.get("allocationPct"), 0.2)))
            slippage_pct = max(0.0, min(5.0, _num(body.get("slippagePct"), 0.05)))
            commission_pct = max(0.0, min(1.0, _num(body.get("commissionPct"), 0.1)))
            stop_loss = max(0.1, min(50.0, _num(body.get("stopLoss"), 3.0)))
            take_profit = max(0.1, min(100.0, _num(body.get("takeProfit"), 5.0)))
            trailing_stop = max(0.0, min(50.0, _num(body.get("trailingStop"), 0.0)))
            max_hold_bars = max(0, min(2000, int(_num(body.get("maxHoldBars"), 0))))
            market_type = str(body.get("marketType") or "spot").lower()
            if market_type not in {"spot", "swap", "futures", "margin"}:
                market_type = "spot"
            allow_short = bool(body.get("allowShort"))
            try:
                result = await run_strategy_paper_arena(
                    symbol=symbol,
                    kline_type=kline_type,
                    limit=limit,
                    strategies=body.get("strategies") or [],
                    initial_cash=initial_cash,
                    allocation_pct=allocation_pct,
                    slippage_pct=slippage_pct,
                    commission_pct=commission_pct,
                    stop_loss_pct=stop_loss,
                    take_profit_pct=take_profit,
                    trailing_stop_pct=trailing_stop,
                    max_hold_bars=max_hold_bars,
                    allow_short=allow_short,
                    market_type=market_type,
                )
                return JSONResponse({"ok": True, **result})
            except Exception as exc:
                logger.exception("paper arena run failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/paper-arena/session/tick")
        async def live_paper_arena_session_tick(request: Request):
            from quant.paper_arena import advance_strategy_paper_session, reset_strategy_paper_session

            body = await request.json()
            session_id = str(body.get("sessionId") or "").strip()
            reset = bool(body.get("reset") or not session_id)
            warmup_limit = max(80, min(1000, int(_num(body.get("warmupLimit") or body.get("limit"), 300))))
            try:
                if reset:
                    symbol = str(body.get("symbol") or "BTC-USDT").strip().upper()
                    if "-" not in symbol and "/" not in symbol:
                        symbol = f"{symbol}-USDT"
                    kline_type = {"15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}.get(str(body.get("type") or "1hour"), "1hour")
                    initial_cash = max(10.0, _num(body.get("initialCash"), 10000.0))
                    allocation_pct = max(0.01, min(1.0, _num(body.get("allocationPct"), 0.2)))
                    slippage_pct = max(0.0, min(5.0, _num(body.get("slippagePct"), 0.05)))
                    commission_pct = max(0.0, min(1.0, _num(body.get("commissionPct"), 0.1)))
                    stop_loss = max(0.1, min(50.0, _num(body.get("stopLoss"), 3.0)))
                    take_profit = max(0.1, min(100.0, _num(body.get("takeProfit"), 5.0)))
                    trailing_stop = max(0.0, min(50.0, _num(body.get("trailingStop"), 0.0)))
                    max_hold_bars = max(0, min(2000, int(_num(body.get("maxHoldBars"), 0))))
                    market_type = str(body.get("marketType") or "spot").lower()
                    if market_type not in {"spot", "swap", "futures", "margin"}:
                        market_type = "spot"
                    result = await reset_strategy_paper_session(
                        symbol=symbol,
                        kline_type=kline_type,
                        strategies=body.get("strategies") or [],
                        initial_cash=initial_cash,
                        allocation_pct=allocation_pct,
                        slippage_pct=slippage_pct,
                        commission_pct=commission_pct,
                        stop_loss_pct=stop_loss,
                        take_profit_pct=take_profit,
                        trailing_stop_pct=trailing_stop,
                        max_hold_bars=max_hold_bars,
                        allow_short=bool(body.get("allowShort")),
                        market_type=market_type,
                        warmup_limit=warmup_limit,
                        process_now=True,
                    )
                else:
                    result = await advance_strategy_paper_session(session_id, warmup_limit=warmup_limit)
                return JSONResponse({"ok": True, **result})
            except Exception as exc:
                logger.exception("paper arena session tick failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.get("/dashboard/live/paper-arena/session")
        async def live_paper_arena_session_state(sessionId: str):
            from quant.paper_arena import get_strategy_paper_session

            try:
                result = await get_strategy_paper_session(sessionId)
                return JSONResponse({"ok": True, **result})
            except Exception as exc:
                logger.exception("paper arena session state failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=404)

        @self._router.post("/dashboard/live/paper-arena/session/start")
        async def live_paper_arena_session_start(request: Request):
            from quant.paper_runner import start_runner

            body = await request.json()
            try:
                status = await start_runner(body)
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("paper arena runner start failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/paper-arena/session/stop")
        async def live_paper_arena_session_stop():
            from quant.paper_runner import stop_runner

            try:
                status = await stop_runner()
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("paper arena runner stop failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.get("/dashboard/live/paper-arena/session/status")
        async def live_paper_arena_runner_status():
            from quant.paper_runner import get_status

            return JSONResponse({"ok": True, **get_status()})

        @self._router.post("/dashboard/live/agent-arena/start")
        async def live_agent_arena_start(request: Request):
            from arena.dashboard_runner import start_runner

            body = await request.json()
            try:
                status = await start_runner(body)
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("agent arena start failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.post("/dashboard/live/agent-arena/stop")
        async def live_agent_arena_stop():
            from arena.dashboard_runner import stop_runner

            try:
                status = await stop_runner()
                return JSONResponse({"ok": True, **status})
            except Exception as exc:
                logger.exception("agent arena stop failed")
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

        @self._router.get("/dashboard/live/agent-arena/status")
        async def live_agent_arena_status():
            from arena.dashboard_runner import get_status

            return JSONResponse({"ok": True, **get_status()})

        @self._router.post("/dashboard/live/strategy-compare")
        async def live_strategy_compare(request: Request):
            from web.api.backtest_service import execute_backtest
            from web.api.backtest_strategies import list_strategies

            body = await request.json()
            symbol = str(body.get("symbol") or "BTC-USDT").strip().upper()
            if "-" not in symbol:
                symbol = f"{symbol}-USDT"
            kline_type = {"15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}.get(str(body.get("type") or "1hour"), "1hour")
            limit = max(60, min(1500, int(_num(body.get("limit"), 300))))
            stop_loss = max(0.5, min(20.0, _num(body.get("stopLoss"), 3.0)))
            take_profit = max(0.5, min(50.0, _num(body.get("takeProfit"), 5.0)))
            trailing_stop = max(0.0, min(20.0, _num(body.get("trailingStop"), 0.0)))
            max_hold_bars = max(0, min(500, int(_num(body.get("maxHoldBars"), 0))))
            known = {item["name"]: item.get("displayName") or item["name"] for item in list_strategies()}
            requested = body.get("strategies") or ["technical_signal", "ma_crossover", "rsi_mean_reversion", "macd", "buy_and_hold"]
            strategy_names = []
            for item in requested:
                name = str(item).strip()
                if name in known and name not in strategy_names:
                    strategy_names.append(name)
            if not strategy_names:
                return JSONResponse({"ok": False, "message": "没有可运行的策略"}, status_code=400)

            results = []
            for strategy_name in strategy_names:
                try:
                    result = await execute_backtest(
                        symbol=symbol,
                        kline_type=kline_type,
                        limit=limit,
                        stop_loss_pct=stop_loss,
                        take_profit_pct=take_profit,
                        trailing_stop_pct=trailing_stop,
                        max_hold_bars=max_hold_bars,
                        strategy_name=strategy_name,
                        optimize=False,
                    )
                    payload = asdict(result)
                    curve = payload.get("equity_curve") or []
                    if len(curve) > 400:
                        step = max(1, len(curve) // 400)
                        curve = curve[::step] + ([] if curve[-1] in curve[::step] else [curve[-1]])
                    results.append({
                        "name": strategy_name,
                        "displayName": known.get(strategy_name, strategy_name),
                        "total_return_pct": payload.get("total_return_pct"),
                        "max_drawdown_pct": payload.get("max_drawdown_pct"),
                        "win_rate": payload.get("win_rate"),
                        "total_trades": payload.get("total_trades"),
                        "sharpe_ratio": payload.get("sharpe_ratio"),
                        "profit_factor": payload.get("profit_factor"),
                        "equity_curve": [{"time": item.get("ts"), "value": item.get("equity")} for item in curve],
                    })
                except Exception as exc:
                    logger.warning("strategy compare failed: %s %s", strategy_name, exc)
                    results.append({"name": strategy_name, "displayName": known.get(strategy_name, strategy_name), "error": str(exc)})
            return JSONResponse({"ok": True, "symbol": symbol, "type": kline_type, "limit": limit, "results": results})
