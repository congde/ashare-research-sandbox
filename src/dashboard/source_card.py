"""Small source-card helpers for dashboard teaching data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DOMAIN_BY_DATASET = {
    "market_tickers": "行情",
    "market_candles": "行情",
    "token_fund": "资金",
    "sector_fund": "资金",
    "onchain": "链上",
    "ai_picks": "情绪",
    "opportunity_scan": "情绪",
}


@dataclass(frozen=True, slots=True)
class SourceCard:
    dataset: str
    domain: str
    origin: str
    updated_at: str
    path: str
    complete: bool
    reason: str
    can_answer: str
    cannot_answer: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_market_row(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not row.get("source"):
        errors.append("missing source")
    if not row.get("observed_at"):
        errors.append("missing observed_at")
    if float(row.get("close") or 0) <= 0:
        errors.append("invalid close")
    return errors


def source_card_from_manifest(dataset: str, manifest: dict[str, Any]) -> SourceCard:
    entry = (manifest.get("datasets") or {}).get(dataset) or {}
    origin = str(entry.get("origin") or "unknown")
    complete = bool(entry.get("complete"))
    reason = str(entry.get("reason") or "")
    domain = DOMAIN_BY_DATASET.get(dataset, "其他")
    return SourceCard(
        dataset=dataset,
        domain=domain,
        origin=origin,
        updated_at=str(entry.get("updated_at") or ""),
        path=str(entry.get("path") or ""),
        complete=complete,
        reason=reason,
        can_answer=f"{domain}数据在该来源和保存时间下的样本事实",
        cannot_answer="不能单独证明因果关系、未来收益或实盘执行指令",
    )
