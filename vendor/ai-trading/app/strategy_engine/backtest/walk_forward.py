"""Walk-forward analysis — out-of-sample stability check for a backtest.

Sprint-S4 DoD: "walk-forward pass 字段集成到 Metrics". The cleanest
implementation isn't to bolt a ``walk_forward_pass`` boolean onto
``BacktestMetrics`` (which describes ONE run) — it's to expose a
separate analysis that consumes the engine multiple times and reports
whether the strategy generalises.

The contract:

  * Given a strategy callable + candle series, split the data into
    consecutive folds.
  * Run the engine independently on each fold.
  * Report per-fold metrics + a single ``pass_`` boolean that captures
    "the strategy behaved similarly across folds".

Why this matters: an overfit strategy can look amazing on a single
1y backtest by picking up a market regime that won't repeat. Splitting
into 4–5 folds and checking that PNL doesn't flip sign / Sharpe doesn't
degrade by > 50 % between folds catches the common overfit shapes.

What this is NOT:

  * Not a hyperparameter optimiser. The strategy callable is taken as a
    black box; we don't fit anything. (Hyperopt is parked to v1.5 per
    the architecture doc.)
  * Not a true train/test split — for a no-fit strategy, "train" and
    "test" are the same operation (run engine on that data). The
    multi-fold spread IS the test.
  * Not anchored walk-forward (where fold N+1 trains on folds 0..N).
    For no-fit strategies that's equivalent to running on the
    cumulative prefix — the marginal signal lives in fold-by-fold
    variance, which our rolling-fold variant captures directly.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.market_data import Candle
from app.strategy_engine.backtest.engine import BacktestEngine, StrategyFn
from app.strategy_engine.backtest.models import (
    BacktestMetrics,
    ConstantBpsFee,
    ConstantBpsSlippage,
    FeeModel,
    SlippageModel,
)

# A factory returns a fresh strategy closure on every call. Walk-forward
# requires this because strategies routinely hold state (rolling SMAs,
# position flags, etc.) in closures — passing one closure across folds
# would let state leak from in-sample into out-of-sample.
StrategyFactory = Callable[[], StrategyFn]


# Default acceptance bands — tight enough to flag real overfit, loose
# enough to not flag noise. These are documented as part of the
# ``WalkForwardReport`` so consumers can interpret a fail.

#: PNL direction must agree across ≥ this fraction of folds for pass_.
#: At 0.8 with 5 folds, 4 of 5 must share sign (positive or negative).
DEFAULT_DIRECTION_AGREEMENT = 0.8

#: Sharpe variability tolerance: stdev(fold_sharpes) / |mean(fold_sharpes)|.
#: A coefficient of variation > 1.5 means folds disagree wildly.
DEFAULT_SHARPE_CV_MAX = 1.5

#: Minimum folds to call the analysis meaningful. 2 is the theoretical
#: floor (need ≥ 2 samples to compute variance); 3 is what we recommend.
MIN_FOLDS = 2


# ── Result types ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FoldResult:
    """One fold's outcome. ``period`` is inclusive on both ends."""

    fold_index: int
    period_start: datetime
    period_end: datetime
    candle_count: int
    metrics: BacktestMetrics


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Summary of a walk-forward run.

    ``pass_`` is the single yes/no a UI would surface. The supporting
    fields explain WHY when it's no — keeping the failure interpretable
    instead of a black-box boolean.
    """

    folds: int
    fold_results: list[FoldResult]
    direction_agreement: float
    sharpe_cv: float | None
    pass_: bool
    reason: str
    # Echo the acceptance bands so a UI / downstream consumer can show
    # the user what threshold they tripped instead of guessing.
    direction_agreement_threshold: float = DEFAULT_DIRECTION_AGREEMENT
    sharpe_cv_max: float = DEFAULT_SHARPE_CV_MAX
    # Per-fold PNL pct + Sharpe — convenience so UI doesn't have to
    # drill into ``fold_results`` for the headline numbers.
    fold_pnl_pct: list[float] = field(default_factory=list)
    fold_sharpe: list[float] = field(default_factory=list)


# ── Public entry point ───────────────────────────────────────────


def walk_forward_analysis(
    strategy_factory: StrategyFactory,
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    *,
    folds: int = 5,
    initial_capital: Decimal = Decimal("1000"),
    fee_model: FeeModel | None = None,
    slippage_model: SlippageModel | None = None,
    direction_agreement_threshold: float = DEFAULT_DIRECTION_AGREEMENT,
    sharpe_cv_max: float = DEFAULT_SHARPE_CV_MAX,
) -> WalkForwardReport:
    """Run the strategy independently on ``folds`` consecutive chunks
    of ``candles`` and report cross-fold stability.

    ``strategy_factory`` is called once per fold; the returned callable
    is given to a fresh ``BacktestEngine``. This forces strategy state
    (closures, dicts, rolling buffers) to reset between folds — without
    this guarantee, an "out-of-sample" fold inherits in-sample state
    and the analysis becomes meaningless.

    If your strategy is stateless, ``strategy_factory=lambda: my_fn``
    is the trivial adapter.

    Args:
      strategy_factory: zero-arg callable returning a fresh strategy
        function. Called ``folds`` times.
      candles: full history. Split into ``folds`` near-equal chunks.
      symbol / timeframe: forwarded to each fold's engine run.
      folds: number of non-overlapping chunks (must be ≥ MIN_FOLDS).
      initial_capital / fee_model / slippage_model: forwarded.
      direction_agreement_threshold / sharpe_cv_max: acceptance bands.

    Raises:
      ValueError: when ``folds < MIN_FOLDS`` or there are not enough
        candles to make each fold non-empty.
    """
    if folds < MIN_FOLDS:
        raise ValueError(f"folds={folds} below minimum {MIN_FOLDS}")
    if len(candles) < folds:
        raise ValueError(
            f"need at least {folds} candles to make {folds} folds, "
            f"got {len(candles)}"
        )

    fold_results = _run_folds(
        strategy_factory=strategy_factory,
        candles=candles,
        symbol=symbol,
        timeframe=timeframe,
        folds=folds,
        initial_capital=initial_capital,
        fee_model=fee_model or ConstantBpsFee(),
        slippage_model=slippage_model or ConstantBpsSlippage(),
    )

    # Aggregate the fold metrics into the pass/fail signal.
    fold_pnl_pct = [f.metrics.pnl_pct for f in fold_results]
    fold_sharpe = [f.metrics.sharpe for f in fold_results]

    direction_agreement = _direction_agreement(fold_pnl_pct)
    sharpe_cv = _coefficient_of_variation(fold_sharpe)

    # Pass criteria — BOTH must hold. Direction is the louder signal
    # (an overfit strategy commonly flips sign across folds); Sharpe-CV
    # catches the subtler case where sign holds but magnitudes are
    # erratic.
    direction_ok = direction_agreement >= direction_agreement_threshold
    sharpe_ok = sharpe_cv is None or sharpe_cv <= sharpe_cv_max

    pass_ = direction_ok and sharpe_ok
    reason = _build_reason(
        pass_=pass_,
        direction_ok=direction_ok,
        sharpe_ok=sharpe_ok,
        direction_agreement=direction_agreement,
        sharpe_cv=sharpe_cv,
        direction_threshold=direction_agreement_threshold,
        sharpe_cv_max=sharpe_cv_max,
    )

    return WalkForwardReport(
        folds=folds,
        fold_results=fold_results,
        direction_agreement=direction_agreement,
        sharpe_cv=sharpe_cv,
        pass_=pass_,
        reason=reason,
        direction_agreement_threshold=direction_agreement_threshold,
        sharpe_cv_max=sharpe_cv_max,
        fold_pnl_pct=fold_pnl_pct,
        fold_sharpe=fold_sharpe,
    )


# ── Internals ────────────────────────────────────────────────────


def _run_folds(
    *,
    strategy_factory: StrategyFactory,
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    folds: int,
    initial_capital: Decimal,
    fee_model: FeeModel,
    slippage_model: SlippageModel,
) -> list[FoldResult]:
    """Slice ``candles`` into ``folds`` non-overlapping chunks and run
    the engine on each. Each chunk gets its own engine instance AND a
    fresh strategy closure from ``strategy_factory()`` to keep
    pending-order book + strategy state isolated."""
    fold_chunks = _split_into_folds(candles, folds)
    results: list[FoldResult] = []
    for idx, chunk in enumerate(fold_chunks):
        engine = BacktestEngine(
            strategy_fn=strategy_factory(),
            initial_capital=initial_capital,
            fee_model=fee_model,
            slippage_model=slippage_model,
        )
        result = engine.run(chunk, symbol=symbol, timeframe=timeframe)
        results.append(
            FoldResult(
                fold_index=idx,
                period_start=chunk[0].ts,
                period_end=chunk[-1].ts,
                candle_count=len(chunk),
                metrics=result.metrics,
            )
        )
    return results


def _split_into_folds(candles: list[Candle], folds: int) -> list[list[Candle]]:
    """Slice ``candles`` into ``folds`` near-equal-length chunks.

    When ``len(candles)`` isn't a multiple of ``folds``, extra candles
    are distributed across the first chunks (so all chunks differ by
    at most 1 candle). This avoids a tiny tail-chunk whose metrics
    would be noise.
    """
    n = len(candles)
    base, remainder = divmod(n, folds)
    chunks: list[list[Candle]] = []
    cursor = 0
    for i in range(folds):
        size = base + (1 if i < remainder else 0)
        chunks.append(candles[cursor : cursor + size])
        cursor += size
    return chunks


def _direction_agreement(pnl_pcts: list[float]) -> float:
    """Fraction of folds whose PNL sign matches the modal sign.

    Returns 1.0 if all folds share a sign; 0.5 means half-and-half.
    A fold with exactly 0 PNL is counted as neither — it neither agrees
    nor disagrees, which is the conservative interpretation.
    """
    if not pnl_pcts:
        return 0.0
    positives = sum(1 for p in pnl_pcts if p > 0)
    negatives = sum(1 for p in pnl_pcts if p < 0)
    if positives == 0 and negatives == 0:
        # All-zero PNL — strategy didn't act. Treat as "no signal"
        # rather than perfect agreement.
        return 0.0
    return max(positives, negatives) / len(pnl_pcts)


def _coefficient_of_variation(sharpes: list[float]) -> float | None:
    """Coefficient of variation: stdev / |mean|.

    Returns None when undefined (mean ≈ 0 → CV diverges; treat the
    metric as inapplicable rather than emitting infinity). The caller
    interprets None as "skip the Sharpe gate" — same effect as a pass.
    """
    if len(sharpes) < 2:
        return None
    mean = statistics.fmean(sharpes)
    if abs(mean) < 1e-9:
        return None
    stdev = statistics.stdev(sharpes)
    return stdev / abs(mean)


def _build_reason(
    *,
    pass_: bool,
    direction_ok: bool,
    sharpe_ok: bool,
    direction_agreement: float,
    sharpe_cv: float | None,
    direction_threshold: float,
    sharpe_cv_max: float,
) -> str:
    """One-line human-readable verdict. Both pass and fail get a
    reason so the UI can show the same field uniformly.
    """
    if pass_:
        if sharpe_cv is None:
            return (
                f"pass: direction agreement {direction_agreement:.0%} "
                f"≥ {direction_threshold:.0%}; sharpe CV undefined "
                f"(mean ≈ 0)"
            )
        return (
            f"pass: direction agreement {direction_agreement:.0%} "
            f"≥ {direction_threshold:.0%}; sharpe CV {sharpe_cv:.2f} "
            f"≤ {sharpe_cv_max:.2f}"
        )

    parts: list[str] = []
    if not direction_ok:
        parts.append(
            f"direction agreement {direction_agreement:.0%} "
            f"< {direction_threshold:.0%}"
        )
    if not sharpe_ok and sharpe_cv is not None:
        parts.append(f"sharpe CV {sharpe_cv:.2f} > {sharpe_cv_max:.2f}")
    return "fail: " + "; ".join(parts) if parts else "fail"
