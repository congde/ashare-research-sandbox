# Upstream fusion plan

Two upstream repositories are preserved as read-only baselines under `vendor/`.
All runnable product code lives under `src/`, aligned with the web3-trading
`src/` layout.

| Product concern | Primary source | Secondary source | Local decision |
|---|---|---|---|
| Product shape and runtime | `web3-trading` | none | Main case; preserve baseline and adapt incrementally |
| Backtest metrics and reports | `web3-trading` | `ai-trading` result models | Use deterministic fixed-sample tests |
| Safe user-authored strategy | `ai-trading` restricted DSL | none | Forbid filesystem, network, process, and dynamic execution |
| Risk controls | `ai-trading` risk manager | `web3-trading` hooks | Adapt as simulation warnings and validation gates |
| Frontend | `web3-trading` Jinja dashboard | `ai-trading` React Quant Atelier | Keep both baselines; teaching page in `src/web/static/` |

## Integration order

1. Preserve both upstream baselines and source records in `vendor/`.
2. Keep `web3-trading` as the main product and code case.
3. Adapt pure metrics, report contracts, and frontend panels into `src/`.
4. Add the `ai-trading` restricted DSL and risk controls under `src/strategy_engine/`.
5. Keep live trading, credentials, wallet signing, and order execution disabled.

## Completed fusion

| Upstream | Local module | Behavior |
|---|---|---|
| `ai-trading/app/strategy_engine/dsl/` | `src/strategy_engine/dsl/` | AST safelist, validation, lookahead linter |
| `web3-trading/src/backtest/metrics.py::compute_calmar` | `src/backtest/runner.py::calmar_ratio` | Negative-drawdown-aware Calmar |
| `web3-trading/src/backtest/metrics.py::compute_sharpe` | `src/backtest/metrics.py::sharpe_ratio` | Daily equity Sharpe with `sqrt(365)` |
| `ai-trading/app/strategy_engine/runtime/risk_manager.py` | `src/risk/simulation.py` | Post-backtest simulation gates |
| `ai-trading/app/strategy_engine/backtest/engine.py` | `src/strategy_engine/backtest/` + `src/backtest/runner.py` | Event-driven loop with `on_tick` MA crossover |
| Both | `src/research/report.py` | Unified JSON report with `fusion`, `risk_checks` |
| `ai-trading` DSL API shape | `app.py::POST /api/validate-strategy` | Browser-side strategy validation |
| Teaching UI | `src/web/static/` | Metrics, risk checks, DSL validator panel |

See also [`AI_TRADING_MIGRATION.md`](AI_TRADING_MIGRATION.md) for the remaining
ai-trading migration backlog.

## Still baseline-only (not wired into the teaching app)

- `vendor/web3-trading/src/web/` Jinja dashboard
- `vendor/ai-trading/web/` React Quant Atelier
- Live runtime, order routers, MongoDB, exchange connectors from both upstreams

The runnable product lives at the repository root under `src/`. The legacy
`labs/` tree has been removed.
