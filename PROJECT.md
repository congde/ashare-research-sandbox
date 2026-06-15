# Web3 research and strategy sandbox

Formal product at repository root. Runnable code lives in `src/`; upstream
baselines in `vendor/`; fixed samples in `data/`.

This is a Codex delivery and acceptance course asset, not a Web3 trading
tutorial. Every asset and account context is fictional. The sandbox reads only
fixed offline samples and must never connect to a real exchange account,
wallet, or order execution path.

## Project layout

```text
ashare-research-sandbox/
├── src/
│   ├── backtest/
│   ├── research/
│   ├── risk/
│   ├── strategy_engine/
│   └── web/static/
├── data/
├── vendor/
├── tests/
├── app.py
├── report_cli.py
└── verify.py
```

## Run

```powershell
py scripts/course.py verify
py app.py
```

See [README.md](README.md) for the full repository map.

## Artifacts

- [product-brief.md](product-brief.md)
- [research-brief.md](research-brief.md)
- [research-acceptance.md](research-acceptance.md)
- [context-pack.md](context-pack.md)
- [research-report.md](research-report.md)
- [prd.md](prd.md)
- [plan.md](plan.md)
- [user-test.md](user-test.md)
- [eval-rubric.md](eval-rubric.md)
- [playbook.md](playbook.md)
- [vendor/FUSION.md](vendor/FUSION.md)
- [vendor/AI_TRADING_MIGRATION.md](vendor/AI_TRADING_MIGRATION.md)
