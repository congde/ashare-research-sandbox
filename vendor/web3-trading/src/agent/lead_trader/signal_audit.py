# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib
from typing import Dict, List, Optional


class SignalStatus(str, Enum):
    PENDING = "pending"
    CHECKED = "checked"


class SignalOrigin(str, Enum):
    RULE_ENGINE = "rule_engine"
    LLM = "llm"


@dataclass
class SignalAuditRecord:
    signal_id: str
    audit_hash: str
    trader_id: str
    strategy_version_id: str
    strategy_id: str
    symbol: str
    pair: str
    direction: str
    score: float
    confidence: float
    price_at_signal: float
    status: SignalStatus = SignalStatus.PENDING
    origin: SignalOrigin = SignalOrigin.RULE_ENGINE

    def __post_init__(self) -> None:
        if not self.audit_hash:
            self.audit_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        raw = "|".join([
            self.signal_id,
            self.trader_id,
            self.strategy_version_id,
            self.strategy_id,
            self.symbol,
            self.pair,
            self.direction,
            f"{self.score:.8f}",
            f"{self.confidence:.8f}",
            f"{self.price_at_signal:.8f}",
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        return self.audit_hash == self._compute_hash()

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["origin"] = self.origin.value
        return data


class SignalAuditStore:
    def __init__(self):
        self._records: Dict[str, SignalAuditRecord] = {}

    async def append(self, record: SignalAuditRecord) -> None:
        if record.signal_id in self._records:
            raise ValueError(f"signal_id {record.signal_id} already exists")
        self._records[record.signal_id] = record

    async def get(self, signal_id: str) -> Optional[Dict]:
        row = self._records.get(signal_id)
        return row.to_dict() if row else None

    async def check_consistency(self, trader_id: str, display_records: List[Dict]) -> Dict:
        by_signal = {
            item.get("signal_id"): item
            for item in (display_records or [])
            if isinstance(item, dict) and item.get("signal_id")
        }
        mismatches = []
        for record in self._records.values():
            if record.trader_id != trader_id:
                continue
            shown = by_signal.get(record.signal_id)
            if not shown:
                mismatches.append({"signal_id": record.signal_id, "reason": "missing_in_display"})
                continue
            for key in ("direction", "score", "confidence", "price_at_signal"):
                if shown.get(key) != getattr(record, key):
                    mismatches.append({"signal_id": record.signal_id, "field": key})
                    break
        return {"is_consistent": len(mismatches) == 0, "mismatches": mismatches}


_audit_store: Optional[SignalAuditStore] = None


def get_audit_store() -> SignalAuditStore:
    global _audit_store
    if _audit_store is None:
        _audit_store = SignalAuditStore()
    return _audit_store
