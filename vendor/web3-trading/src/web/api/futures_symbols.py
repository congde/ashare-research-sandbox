# -*- coding: utf-8 -*-
"""KuCoin futures native symbol helpers (no heavy imports)."""


def spot_pair_to_native_futures_symbol(pair_or_symbol: str) -> str:
    """Convert BTC-USDT or BTC/USDT:USDT to KuCoin futures native symbol (e.g. XBTUSDTM)."""
    raw = str(pair_or_symbol or "").upper().replace("-", "/")
    pair = raw.split(":", 1)[0]
    if "/" in pair:
        base, quote = pair.split("/", 1)
    else:
        parts = pair.split("-")
        base = parts[0] if parts else "BTC"
        quote = parts[1] if len(parts) > 1 else "USDT"
    base_alias = {"BTC": "XBT"}.get(base, base)
    return f"{base_alias}{quote}M"
