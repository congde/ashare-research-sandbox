# ai-trading upstream baseline

This directory preserves selected product-core modules copied from:

- Repository: <https://github.com/johnnywuj81/ai-trading>
- Commit: `b5f98e6cb602d63a55ffcde11afc2a5d8cb76214`
- Copied on: `2026-06-12`
- License: Apache-2.0; the upstream `LICENSE` is preserved here.

## Copied product core

- `app/strategy_engine/`: restricted DSL, event-driven backtest, runtime, and
  risk manager.
- `app/services/`: selected research, strategy architect, strategy card, and
  backtest services.
- `app/domain/market_data/`, `app/connectors/protocol.py`,
  `app/connectors/ws_aggregator.py`, and `app/ai_trading_api/`: supporting
  interfaces required for later extraction.
- selected unit tests, examples, ADRs, and detailed-design documents.
- `web/`: React 19 + Vite Quant Atelier frontend and frontend tests.

The baseline intentionally excludes databases, migrations, exchange adapters,
real-order routes, settlement, contracts, and organization/workflow modules.

## Current import status

The restricted strategy DSL is independently importable and is the first
candidate for adaptation. The event-driven backtest package currently imports
through upstream package initializers that require broader dependencies such as
SQLAlchemy. Extract its small domain interfaces before connecting it to the
A-share teaching project.

## Fusion boundary

Candidate behavior to adapt:

- AST strategy validation and restricted safelist;
- lookahead-bias checks;
- event-driven backtest contracts and fee/slippage models;
- risk-manager rules and audit-friendly results;
- Research/Strategy Agent interfaces;
- Quant Atelier React design system and backtest/research pages.

Behavior that must not enter the teaching MVP:

- exchange credentials or authenticated connectors;
- real-order routing and live deployment;
- databases, Redis, ClickHouse, MinIO, or settlement contracts;
- automatic strategy publication or trading approval.

Run the baseline smoke check:

```powershell
py vendor/ai-trading/verify_baseline.py
```
