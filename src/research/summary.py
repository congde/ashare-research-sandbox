from __future__ import annotations

import json
from pathlib import Path


def load_company(path: Path) -> dict:
    """Load the teaching asset.

    The function name is kept for compatibility with existing course links.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def build_research_summary(asset: dict) -> dict:
    snapshot = asset["market_snapshot"]
    return {
        "company": f'{asset["name"]}（{asset["symbol"]}）',
        "fictional": asset["fictional"],
        "facts": [
            {
                "claim": (
                    f'{snapshot["period"]} 数据包包含 '
                    f'{snapshot["sample_days"]} 个日线收盘价，'
                    f'参考起始价格为 {snapshot["reference_price"]} USDT。'
                ),
                "source_id": "S1",
            },
            {
                "claim": (
                    f'固定样本中的成交量指数为 {snapshot["volume_index"]}，'
                    f'活跃地址指数为 {snapshot["active_address_index"]}。'
                ),
                "source_id": "S2",
            },
            {
                "claim": "该资产与全部市场、链上活动数据均为虚构离线样本。",
                "source_id": "S3",
            },
        ],
        "interpretation": (
            "固定样本适合验证研究流程、策略接口和回测指标是否可重复，"
            "但不能据此判断任何真实 Web3 资产的价值或未来表现。"
        ),
        "unknowns": [
            "样本不包含真实交易所深度、滑点、资金费率或链上拥堵。",
            "样本不代表真实协议基本面、代币经济模型或治理风险。",
        ],
        "sources": asset["sources"],
    }
