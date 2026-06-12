# First-version PRD

## Problem

Learners can find many Web3 market opinions but struggle to separate sourced
facts, interpretation, historical simulation, and future uncertainty.

## Core user path

1. Open the fictional Web3 asset page.
2. Read the sourced fixed-snapshot summary.
3. Choose short and long moving-average windows.
4. Run the deterministic historical backtest.
5. Inspect return, drawdown, trades, assumptions, and limitations.

## In scope

- Fixed offline Web3 sample data.
- Source-backed research cards.
- Moving-average crossover and buy-and-hold comparison.
- Browser interface and deterministic JSON API.

## Out of scope

- Live markets, real tokens, wallets, exchange accounts, orders, portfolio
  advice, and predicted returns.

## Acceptance

- `py scripts/course.py lab-10` passes.
- `/api/report` returns research, metrics, trades, and warnings.
- The page visibly states that results are educational and cannot execute trades.
