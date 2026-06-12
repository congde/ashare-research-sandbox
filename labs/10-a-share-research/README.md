# Lab 10: A-share research and strategy sandbox

This self-contained course project turns a product idea into a runnable first
version. It uses fixed historical samples, so every learner sees the same
result without a brokerage account, API key, or network connection.

The project can:

- show a source-backed company research summary;
- run a simple moving-average crossover backtest;
- report return, drawdown, trade count, and assumptions;
- serve a small web interface for user testing.

It cannot:

- connect to a brokerage account;
- place orders or recommend a specific trade;
- prove that a strategy will work in the future.

## Run the verification

macOS / Linux:

```bash
make lab-10
```

Windows PowerShell:

```powershell
py scripts/course.py lab-10
```

## Run the web app

```powershell
.\.venv\Scripts\python.exe labs/10-a-share-research/app.py
```

Then open <http://127.0.0.1:8765>.

## Project artifacts

- [product-brief.md](product-brief.md): the original idea and safety boundary.
- [research-report.md](research-report.md): user and competitor research (Go decision).
- [prd.md](prd.md): the first-version product contract.
- [plan.md](plan.md): architecture and evidence-gated implementation plan.
- [user-test.md](user-test.md): the real-use validation task.
- [eval-rubric.md](eval-rubric.md): the repeatability rubric.
- [playbook.md](playbook.md): the handoff and reuse guide.

