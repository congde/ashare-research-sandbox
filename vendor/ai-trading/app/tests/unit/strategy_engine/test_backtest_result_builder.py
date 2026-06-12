"""Unit tests for the backtest ResultBuilder (Parquet + S3 publish path).

The boundary under test is ``publish_backtest_result`` — given a
finalised ``BacktestResult``, does it:

  1. Serialise the trades + equity curve into valid Parquet?
  2. Round-trip the Decimal columns without losing precision?
  3. Upload to the right S3 keys with the right content-type?
  4. Return a ``PublishedResult`` with the right metadata?

Uploads are stubbed via a recording fake — no boto3, no MinIO, no
network. The real ``storage_service.upload_bytes`` is integration-
tested separately.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

# pyarrow is a hard dep for this module — skip the whole file if it's
# missing rather than failing each test individually (e.g. when running
# the test matrix in a stripped-down image).
pytest.importorskip("pyarrow")

from app.strategy_engine.backtest.models import (  # noqa: E402
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
)
from app.strategy_engine.backtest.result_builder import (  # noqa: E402
    EQUITY_FILENAME,
    S3_KEY_PREFIX,
    TRADES_FILENAME,
    deserialise_equity,
    deserialise_trades,
    publish_backtest_result,
)

# ── Recording fake uploader ──────────────────────────────────────


class _RecordingUploader:
    """Captures every ``upload_bytes`` call so we can assert keys,
    content types, and recover the bytes for a round-trip check."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.calls.append(
            {
                "key": key,
                "data": data,
                "content_type": content_type,
            }
        )
        return f"http://fake-s3/{key}"

    def find(self, suffix: str) -> dict[str, Any]:
        """Locate the call whose key ends with ``suffix``. Raises if
        not exactly one match — keeps tests honest about which
        artefact they're inspecting."""
        matches = [c for c in self.calls if c["key"].endswith(suffix)]
        assert len(matches) == 1, f"Expected exactly one {suffix} upload, got {len(matches)}"
        return matches[0]


# ── Fixtures ─────────────────────────────────────────────────────


def _t(ts_iso: str) -> datetime:
    """ISO-8601 → tz-aware UTC datetime — keeps the test data terse."""
    return datetime.fromisoformat(ts_iso).replace(tzinfo=UTC)


def _make_result(*, n_trades: int = 3, n_equity: int = 5) -> BacktestResult:
    """Build a minimal but realistic ``BacktestResult``. Decimal values
    chosen to expose any string round-trip precision loss
    (sub-satoshi quantities, awkward fee fractions)."""
    base_ts = _t("2026-05-01T00:00:00")
    trades = [
        BacktestTrade(
            ts=base_ts + timedelta(minutes=i),
            symbol="BTC/USDT",
            side="buy" if i % 2 == 0 else "sell",
            qty=Decimal("0.00012345"),
            price=Decimal(f"{60000 + i * 10}.50"),
            fee=Decimal("0.00000123"),
            realized_pnl=Decimal(f"{i * 1.5}") if i % 2 else Decimal("0"),
        )
        for i in range(n_trades)
    ]
    equity_curve = [
        (base_ts + timedelta(minutes=i), Decimal(f"{1000 + i * 0.5}"))
        for i in range(n_equity)
    ]
    metrics = BacktestMetrics(
        period_start=base_ts,
        period_end=base_ts + timedelta(minutes=n_equity),
        total_trades=n_trades,
        win_rate=0.5,
        pnl_pct=2.0,
        pnl_abs=Decimal("20"),
        sharpe=1.2,
        sortino=1.8,
        max_drawdown_pct=1.0,
        final_equity=Decimal("1020"),
    )
    return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)


# ── publish_backtest_result ──────────────────────────────────────


def test_publish_uploads_both_artefacts() -> None:
    """Exactly two uploads: trades.parquet + equity.parquet."""
    fake = _RecordingUploader()
    result = _make_result()
    handle = publish_backtest_result("bt-abc", result, uploader=fake)
    assert len(fake.calls) == 2
    assert handle.trades_row_count == 3
    assert handle.equity_row_count == 5


def test_publish_uses_expected_s3_key_layout() -> None:
    """Keys follow ``backtests/<id>/{trades,equity}.parquet`` —
    mirrors the PG table name so MinIO buckets stay self-describing."""
    fake = _RecordingUploader()
    handle = publish_backtest_result("bt-xyz", _make_result(), uploader=fake)
    assert handle.trades_key == f"{S3_KEY_PREFIX}/bt-xyz/{TRADES_FILENAME}"
    assert handle.equity_key == f"{S3_KEY_PREFIX}/bt-xyz/{EQUITY_FILENAME}"
    keys = {c["key"] for c in fake.calls}
    assert handle.trades_key in keys
    assert handle.equity_key in keys


def test_publish_uses_parquet_content_type() -> None:
    """Both artefacts ship as ``application/vnd.apache.parquet`` so
    the browser doesn't try to render them inline."""
    fake = _RecordingUploader()
    publish_backtest_result("bt-1", _make_result(), uploader=fake)
    for call in fake.calls:
        assert call["content_type"] == "application/vnd.apache.parquet"


# ── Round-trip schema / precision ────────────────────────────────


def test_trades_roundtrip_preserves_decimal_precision() -> None:
    """Decimals are serialised as strings to avoid Parquet DECIMAL
    precision-trap; the round-trip must recover the original values
    exactly."""
    fake = _RecordingUploader()
    result = _make_result(n_trades=3)
    publish_backtest_result("bt-1", result, uploader=fake)

    blob = fake.find(TRADES_FILENAME)["data"]
    rows = deserialise_trades(blob)

    assert len(rows) == 3
    assert rows[0]["symbol"] == "BTC/USDT"
    # qty / price / fee / realized_pnl recovered as Decimal with original precision
    assert rows[0]["qty"] == Decimal("0.00012345")
    assert rows[0]["price"] == Decimal("60000.50")
    assert rows[0]["fee"] == Decimal("0.00000123")
    # ts column survives as a tz-aware datetime
    assert isinstance(rows[0]["ts"], datetime)
    assert rows[0]["ts"].tzinfo is not None


def test_equity_roundtrip_preserves_tuple_shape() -> None:
    """``deserialise_equity`` returns the original ``(ts, Decimal)``
    tuples — the UI plots that shape directly without re-mapping."""
    fake = _RecordingUploader()
    result = _make_result(n_equity=5)
    publish_backtest_result("bt-1", result, uploader=fake)

    blob = fake.find(EQUITY_FILENAME)["data"]
    points = deserialise_equity(blob)

    assert len(points) == 5
    # Original tuple shape: (datetime, Decimal)
    assert all(isinstance(ts, datetime) for ts, _ in points)
    assert all(isinstance(eq, Decimal) for _, eq in points)
    # First point matches the synthesised fixture
    assert points[0][1] == Decimal("1000")


def test_empty_trades_still_writes_valid_parquet() -> None:
    """A no-trade run is a valid outcome (strategy never fired). The
    publisher must still emit a syntactically valid Parquet with the
    expected schema, not error out."""
    fake = _RecordingUploader()
    result = _make_result(n_trades=0, n_equity=3)
    handle = publish_backtest_result("bt-empty", result, uploader=fake)

    assert handle.trades_row_count == 0
    blob = fake.find(TRADES_FILENAME)["data"]
    rows = deserialise_trades(blob)
    assert rows == []


def test_empty_equity_still_writes_valid_parquet() -> None:
    """Mirror of the empty-trades case — empty equity curve must
    serialise cleanly. Defensive: in practice the engine always
    records at least one point, but the publisher shouldn't assume."""
    fake = _RecordingUploader()
    result = _make_result(n_trades=2, n_equity=0)
    handle = publish_backtest_result("bt-no-eq", result, uploader=fake)

    assert handle.equity_row_count == 0
    blob = fake.find(EQUITY_FILENAME)["data"]
    points = deserialise_equity(blob)
    assert points == []


# ── Sortino metric (separate from publish path but in scope) ─────


def test_sortino_present_on_metrics_with_mixed_returns() -> None:
    """A run with both winners and losers should report a finite,
    non-zero Sortino. Sanity check that the formula is wired
    end-to-end through ``compute_metrics``."""
    from app.strategy_engine.backtest.models import compute_metrics

    base_ts = _t("2026-05-01T00:00:00")
    # Need ≥ 2 negative steps. Sequence designed so steps 2, 4, 6
    # are losses (1050→980, 1020→990, 1010→995) and the rest are
    # winners — enough downside samples for a finite Sortino.
    equity = [
        (base_ts + timedelta(minutes=i), Decimal(v))
        for i, v in enumerate(
            ["1000", "1050", "980", "1020", "990", "1010", "995", "1100"]
        )
    ]
    metrics = compute_metrics(Decimal("1000"), trades=[], equity_curve=equity)
    # With multiple downside samples the Sortino should be finite
    # AND distinct from Sharpe (downside stdev < total stdev usually).
    assert metrics.sortino != 0.0
    # Sortino uses downside-only denominator → typically larger than
    # Sharpe when negative returns are not dominant. This dataset has
    # one big drawdown so Sortino < Sharpe; the invariant we assert is
    # finiteness, not ordering.
    import math

    assert math.isfinite(metrics.sortino)


def test_sortino_zero_when_no_negative_returns() -> None:
    """A monotonically-increasing equity curve has 0 negative returns,
    so Sortino is undefined. The contract reports 0.0 (not +inf) to
    keep downstream sorts well-defined."""
    from app.strategy_engine.backtest.models import compute_metrics

    base_ts = _t("2026-05-01T00:00:00")
    equity = [
        (base_ts + timedelta(minutes=i), Decimal(1000 + i * 10))
        for i in range(5)
    ]
    metrics = compute_metrics(Decimal("1000"), trades=[], equity_curve=equity)
    assert metrics.sortino == 0.0


def test_sortino_zero_when_too_few_samples() -> None:
    """Need ≥ 2 downside samples to compute sample stdev; otherwise
    report 0.0 — same rationale as Sharpe."""
    from app.strategy_engine.backtest.models import compute_metrics

    base_ts = _t("2026-05-01T00:00:00")
    # Only one negative step (1010 → 1005).
    equity = [
        (base_ts + timedelta(minutes=i), Decimal(v))
        for i, v in enumerate(["1000", "1010", "1005", "1020"])
    ]
    metrics = compute_metrics(Decimal("1000"), trades=[], equity_curve=equity)
    assert metrics.sortino == 0.0


# ── Schema invariants (catch silent column renames) ──────────────


def test_trades_parquet_schema_columns() -> None:
    """If anyone renames a column in ``_serialise_trades``, the UI
    breaks. Pin the schema explicitly."""
    import pyarrow.parquet as pq

    fake = _RecordingUploader()
    publish_backtest_result("bt-schema", _make_result(), uploader=fake)
    blob = fake.find(TRADES_FILENAME)["data"]

    import io as _io

    table = pq.read_table(_io.BytesIO(blob))
    assert set(table.schema.names) == {
        "ts",
        "symbol",
        "side",
        "qty",
        "price",
        "fee",
        "realized_pnl",
    }


def test_equity_parquet_schema_columns() -> None:
    """Mirror of trades schema pin — equity is just ``(ts, equity)``."""
    import pyarrow.parquet as pq

    fake = _RecordingUploader()
    publish_backtest_result("bt-schema-eq", _make_result(), uploader=fake)
    blob = fake.find(EQUITY_FILENAME)["data"]

    import io as _io

    table = pq.read_table(_io.BytesIO(blob))
    assert set(table.schema.names) == {"ts", "equity"}
