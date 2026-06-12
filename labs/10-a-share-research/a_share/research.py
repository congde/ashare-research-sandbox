from __future__ import annotations

import json
from pathlib import Path


def load_company(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_research_summary(company: dict) -> dict:
    financials = company["financials"]
    sources = company["sources"]
    return {
        "company": f'{company["name"]}（{company["symbol"]}）',
        "fictional": company["fictional"],
        "facts": [
            {
                "claim": (
                    f'{financials["period"]} 营业收入为 '
                    f'{financials["revenue_million"]} 百万元，'
                    f'同比增长 {financials["revenue_growth_pct"]}%。'
                ),
                "source_id": "S1",
            },
            {
                "claim": (
                    f'净利润为 {financials["net_profit_million"]} 百万元，'
                    f'同比增长 {financials["net_profit_growth_pct"]}%。'
                ),
                "source_id": "S1",
            },
            {
                "claim": "主要客户续约，但公告未披露合同金额。",
                "source_id": "S2",
            },
        ],
        "interpretation": (
            "收入与利润均增长，但利润增速低于收入增速；客户续约提供了"
            "业务连续性证据，同时客户集中度风险仍需继续检查。"
        ),
        "unknowns": [
            "重大客户续约金额及收入确认节奏未知。",
            "固定样本不包含同行业估值与完整现金流数据。",
        ],
        "sources": sources,
    }

