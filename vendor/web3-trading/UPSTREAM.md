# web3-trading upstream baseline

Read-only reference copy from [web3-trading](https://github.com/congde/web3-trading).
The runnable teaching product lives in repository-root `src/`; do not import this tree
from product code.

## What this baseline preserves

| Area | Path | Used for |
|------|------|----------|
| Backtest metrics | `src/backtest/` | Calmar / Sharpe shapes, engine reference |
| Dashboard APIs | `src/web/api/` | ValueScan, DexScan, KuCoin, opportunity scan |
| Jinja dashboard UI | `src/web/static/dashboard*.js` | Product shape comparison |
| Config sample | `conf/default.yaml` | Env key names and defaults |

## Local adaptation

See [`../FUSION.md`](../FUSION.md). Product dashboard data is implemented under
`src/dashboard/` with snapshot offline cache in `data/dashboard/snapshots/`.

## Verify

```powershell
py vendor/web3-trading/verify_baseline.py
py vendor/web3-trading/verify_frontend_baseline.py
```
