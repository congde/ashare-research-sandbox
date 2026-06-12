# First-version PRD

## Problem

Learners can obtain many stock opinions but struggle to separate sourced facts,
interpretation, historical simulation, and future uncertainty.

## Core user path

1. Open the sample company page.
2. Read the sourced research summary.
3. choose short and long moving-average windows.
4. Run the historical backtest.
5. inspect return, maximum drawdown, trades, assumptions, and limitations.

## In scope

- Fixed sample data.
- Source-backed research cards.
- User and competitor research package ([research-report.md](research-report.md)).
- Moving-average crossover and buy-and-hold comparison.
- Browser interface and deterministic JSON API.

## Out of scope

- Real companies, live data, stock screening, brokerage accounts, orders,
  portfolio advice, and predicted returns.

## Acceptance

- `py scripts/course.py lab-10` passes.
- `/api/report` returns research, metrics, trades, and warnings.
- The page visibly states that results are educational and not investment
  advice.

