# ashare-research-sandbox 项目说明

This repository is the companion workspace for a Codex delivery course. Treat
course prose and the runnable Web3 research sandbox as one product: examples in
`docs/v2/` must match the files and commands that actually exist.

## Repository map

- `docs/v2/`: publishable chapter drafts.
- `src/`: runnable product code (backtest, research, strategy engine, web UI).
- `vendor/`: read-only upstream baselines (`web3-trading`, `ai-trading`).
- `data/`: fixed offline teaching samples.
- `skills/`: reusable Codex skills taught by the course.
- `docs/samples/`: small source artifacts used by non-code exercises.

## Working rules

- Do not recreate deleted legacy directories such as `app/`, `challenges/`,
  `harness-kit/`, or `labs/`.
- Product code belongs under `src/`, aligned with the web3-trading layout.
- `vendor/` is for comparison and reuse audit only; do not import it from `src/`.
- When prose names a file or command, verify that it exists and works.
- Prefer a small runnable example over a long hypothetical configuration.
- Do not claim a command passed unless it was actually run.

## Verification

Run the project check while editing:

```bash
make verify
```

On Windows PowerShell:

```powershell
py scripts/course.py verify
```

Before finishing a repository-wide change, run:

```bash
make check
```

On Windows PowerShell:

```powershell
py scripts/course.py check
```
