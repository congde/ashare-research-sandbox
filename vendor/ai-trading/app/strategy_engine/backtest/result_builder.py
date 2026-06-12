"""Backtest result → Parquet → MinIO/S3 publication path.

Per ADR-0009. A backtest run produces three artefact streams:

  * ``BacktestMetrics`` — small JSON-shaped struct, persisted as the
    PG ``backtests.metrics`` JSONB column. Handled at the service layer,
    not here.
  * ``trades`` — list of fills. Variable length, may be 10s of thousands
    for a long backtest. Parquet beats JSON by ~10× on disk + supports
    columnar reads from the UI.
  * ``equity_curve`` — one row per candle. For a 1y 1m backtest this
    is ~525k rows. Same Parquet rationale as trades.

This module is the **publish** boundary: it takes a finalised
``BacktestResult`` and writes two Parquet files under
``backtests/<backtest_id>/`` on MinIO, returning the S3 keys (NOT
presigned URLs — those are minted on demand by the UI gateway).

Why a separate module and not a method on ``BacktestEngine``: the engine
is intentionally pure / synchronous / no IO. Parquet + S3 belong to a
separate concern that can be mocked out cleanly in engine tests and run
async / batched in the worker.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.strategy_engine.backtest.models import BacktestResult


# ── Uploader Protocol ────────────────────────────────────────────


class _UploaderProtocol(Protocol):
    """Structural type for any module / object that exposes the same
    ``upload_bytes(key, data, content_type) -> str`` shape as
    :mod:`app.services.storage_service`. Lets us inject fakes in tests
    without subclassing.
    """

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str: ...


# ── Constants ────────────────────────────────────────────────────

# S3 key layout — keep it human-scannable. ``backtests/<id>/trades.parquet``
# and ``backtests/<id>/equity.parquet``. The ``backtests/`` prefix mirrors
# the PG table name so MinIO buckets stay self-describing.
S3_KEY_PREFIX = "backtests"
TRADES_FILENAME = "trades.parquet"
EQUITY_FILENAME = "equity.parquet"


# ── Result handle ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PublishedResult:
    """Where the artefacts ended up. Returned by the publisher so the
    service layer can persist the keys on the ``backtests`` row.

    ``trades_key`` and ``equity_key`` are S3 object keys (not URLs).
    The UI gateway turns them into presigned URLs on demand —
    keeping presigning concerns out of the worker boundary.
    """

    trades_key: str
    equity_key: str
    trades_row_count: int
    equity_row_count: int


# ── Parquet serialisation ────────────────────────────────────────


def _serialise_trades(result: BacktestResult) -> bytes:
    """Encode the trade log as Parquet bytes.

    Decimal columns are written as strings — Parquet's DECIMAL type
    needs an explicit precision/scale we don't have a clean way to
    derive, and the UI / replay path never does arithmetic on these
    values without re-converting to Decimal anyway.
    """
    # Lazy import — pyarrow is ~30 MB and only loaded when a backtest
    # is actually being published. Keeps import-time cost off the
    # critical path.
    import pyarrow as pa
    import pyarrow.parquet as pq

    trades = result.trades
    table = pa.table(
        {
            "ts": pa.array([t.ts for t in trades], type=pa.timestamp("us", tz="UTC")),
            "symbol": pa.array([t.symbol for t in trades], type=pa.string()),
            "side": pa.array([t.side for t in trades], type=pa.string()),
            "qty": pa.array([str(t.qty) for t in trades], type=pa.string()),
            "price": pa.array([str(t.price) for t in trades], type=pa.string()),
            "fee": pa.array([str(t.fee) for t in trades], type=pa.string()),
            "realized_pnl": pa.array(
                [str(t.realized_pnl) for t in trades], type=pa.string()
            ),
        }
    )

    buf = io.BytesIO()
    # SNAPPY: ~2× faster decompress than GZIP at ~10 % larger files.
    # For the equity-curve scale (~500k rows) decompress speed dominates
    # the UI's render path, so SNAPPY wins on user-perceived latency.
    pq.write_table(table, buf, compression="SNAPPY")
    return buf.getvalue()


def _serialise_equity(result: BacktestResult) -> bytes:
    """Encode the equity curve as Parquet bytes.

    Equity is the larger of the two artefacts (one row per candle).
    Same Decimal-as-string convention as trades.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    points = result.equity_curve
    table = pa.table(
        {
            "ts": pa.array([ts for ts, _ in points], type=pa.timestamp("us", tz="UTC")),
            "equity": pa.array([str(eq) for _, eq in points], type=pa.string()),
        }
    )

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="SNAPPY")
    return buf.getvalue()


# ── Upload boundary ──────────────────────────────────────────────


def publish_backtest_result(
    backtest_id: str,
    result: BacktestResult,
    *,
    uploader: _UploaderProtocol | None = None,
) -> PublishedResult:
    """Serialise the result to Parquet and upload to MinIO/S3.

    ``backtest_id`` is the PG row UUID — used both as the S3 key prefix
    and as the foreign-key reference on the ``backtests`` row that
    stores ``s3_report_url``.

    ``uploader`` is any object exposing the
    :class:`_UploaderProtocol` shape (``upload_bytes(key, data,
    content_type) -> str``). Defaults to
    ``app.services.storage_service`` which talks to MinIO. Injection
    keeps unit tests offline.
    """
    if uploader is None:
        # Local import — boto3 import is expensive (~150 ms cold) and
        # we want pure-Python unit tests to skip it via dependency
        # injection. The default-path import is intentional, not lazy
        # for performance. The cast tells mypy the module-as-namespace
        # is structurally compatible with the Protocol.
        from app.services import storage_service as _ss

        uploader = _ss

    # ``uploader`` is non-None after the resolution above. Help mypy.
    assert uploader is not None
    upload_fn = uploader.upload_bytes

    trades_bytes = _serialise_trades(result)
    equity_bytes = _serialise_equity(result)

    trades_key = f"{S3_KEY_PREFIX}/{backtest_id}/{TRADES_FILENAME}"
    equity_key = f"{S3_KEY_PREFIX}/{backtest_id}/{EQUITY_FILENAME}"

    # Parquet content-type per RFC. Some browsers serve octet-stream
    # instead, but we control both writer and reader so we may as well
    # be explicit.
    upload_fn(trades_key, trades_bytes, "application/vnd.apache.parquet")
    upload_fn(equity_key, equity_bytes, "application/vnd.apache.parquet")

    return PublishedResult(
        trades_key=trades_key,
        equity_key=equity_key,
        trades_row_count=len(result.trades),
        equity_row_count=len(result.equity_curve),
    )


# ── Read-back helpers (used by tests + the UI gateway) ───────────


def deserialise_trades(blob: bytes) -> list[dict[str, Any]]:
    """Inverse of ``_serialise_trades``. Used by unit tests to assert
    schema round-trip, and by the UI gateway when streaming the trade
    log back to the browser.

    Return type is ``list[dict[str, Any]]`` because each column has a
    different runtime type (datetime / str / Decimal) — narrowing it
    further would force every consumer to cast.
    """
    import pyarrow.parquet as pq

    buf = io.BytesIO(blob)
    table = pq.read_table(buf)
    rows: list[dict[str, Any]] = table.to_pylist()
    # Re-hydrate Decimal columns. The string-on-the-wire is a
    # serialisation detail; consumers expect Decimals.
    for row in rows:
        for col in ("qty", "price", "fee", "realized_pnl"):
            row[col] = Decimal(row[col])
    return rows


def deserialise_equity(blob: bytes) -> list[tuple[datetime, Decimal]]:
    """Inverse of ``_serialise_equity``. Returns the original tuple
    shape so the UI can plot it directly."""
    import pyarrow.parquet as pq

    buf = io.BytesIO(blob)
    table = pq.read_table(buf)
    rows = table.to_pylist()
    return [(row["ts"], Decimal(row["equity"])) for row in rows]
