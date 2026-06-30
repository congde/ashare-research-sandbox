from __future__ import annotations

from typing import Any


def market_overview(items: list[dict[str, Any]], total_scanned: int) -> str:
    if not items:
        return "暂无足够数据生成市场概览。"
    buy_count = sum(1 for item in items if item.get("signal") in ("BUY", "WEAK_BUY"))
    sell_count = sum(1 for item in items if item.get("signal") in ("SELL", "WEAK_SELL"))
    neutral_count = sum(1 for item in items if item.get("signal") == "NEUTRAL")
    if buy_count > sell_count * 2:
        sentiment = "整体偏多"
    elif sell_count > buy_count * 2:
        sentiment = "整体偏空"
    else:
        sentiment = "方向分化"
    top_desc = "、".join(f"{item['symbol']}({item['label']})" for item in items[:3])
    return (
        f"扫描 {total_scanned} 个币种，市场{sentiment}。"
        f"多头 {buy_count}、空头 {sell_count}、中性 {neutral_count}。"
        f"综合靠前：{top_desc}。"
    )
