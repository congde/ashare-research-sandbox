"""Point-in-time (PIT) data helpers — teaching stub for A-share extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PitRecord:
    permno: str
    value: float
    announce_date: str
    pdate: str
    start_date: str
    end_date: str


def compute_start_date(announce_date: str, pdate: str) -> str:
    """Effective availability is the later of announce and provider dates."""
    return max(announce_date, pdate)


def validate_pit_intervals(records: list[PitRecord]) -> list[str]:
    """Return validation errors for a PIT table."""
    errors: list[str] = []
    by_permno: dict[str, list[PitRecord]] = {}
    for record in records:
        by_permno.setdefault(record.permno, []).append(record)
        if record.start_date > record.end_date:
            errors.append(f"{record.permno}: start_date after end_date")

    for permno, rows in by_permno.items():
        ordered = sorted(rows, key=lambda item: item.start_date)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.start_date <= prev.end_date:
                errors.append(f"{permno}: overlapping intervals {prev.end_date} / {cur.start_date}")
    return errors


TEACHING_PIT_SAMPLE: list[dict[str, Any]] = [
    {
        "permno": "DEMO001",
        "item": "roe",
        "value": 0.12,
        "announce_date": "2024-03-31",
        "pdate": "2024-04-28",
        "start_date": "2024-04-28",
        "end_date": "2024-08-14",
        "note": "As-filed Q1 ROE — not restated series.",
    },
    {
        "permno": "DEMO002",
        "item": "roe",
        "value": -0.35,
        "announce_date": "2024-03-31",
        "pdate": "2024-04-30",
        "start_date": "2024-04-30",
        "end_date": "2024-06-01",
        "note": "Delisted issuer retained for survivorship-free universe.",
    },
]


def pit_teaching_summary() -> dict[str, Any]:
    """Static teaching artifact describing PIT requirements."""
    records = [
        PitRecord(
            permno=row["permno"],
            value=float(row["value"]),
            announce_date=row["announce_date"],
            pdate=row["pdate"],
            start_date=row["start_date"],
            end_date=row["end_date"],
        )
        for row in TEACHING_PIT_SAMPLE
    ]
    return {
        "ok": True,
        "records": TEACHING_PIT_SAMPLE,
        "validation_errors": validate_pit_intervals(records),
        "checklist": [
            "Use start_date = max(announce_date, pdate).",
            "Rebuild investable universe on each rebalance date.",
            "Include delisted names and terminal returns.",
            "Never filter today's tickers retroactively.",
        ],
    }
