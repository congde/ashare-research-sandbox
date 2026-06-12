# Web3 sandbox playbook

## Use when

You need a reproducible teaching example for research, PRD, planning,
AI-assisted implementation, user testing, or Eval.

## Run

```powershell
py scripts/course.py verify
.\.venv\Scripts\python.exe app.py
```

终端快速查看报告（无需启动网页）：

```powershell
.\.venv\Scripts\python.exe report_cli.py
.\.venv\Scripts\python.exe report_cli.py --short 5 --long 10
```

## Verify

1. Confirm the course task passes.
2. Open <http://127.0.0.1:8765>.
3. Run the default backtest.
4. Check that source cards and safety warnings are visible.
5. Score the run with [eval-rubric.md](eval-rubric.md); all five dimensions must
   reach 2 before expanding automation.

## Handoff checklist

| 接手者需要 | 位置 |
|---|---|
| 产品边界 | [product-brief.md](product-brief.md) |
| 用户与竞品调研 | [research-report.md](research-report.md) |
| 第一版合同 | [prd.md](prd.md) |
| 架构与里程碑 | [plan.md](plan.md) |
| 用户测试任务 | [user-test.md](user-test.md) |
| 代码入口 | `src/research/report.py`, `app.py` |

## Never automate

- brokerage login or order placement;
- publication of a buy or sell recommendation;
- replacement of fixed samples with unreviewed live data;
- removal of assumptions, limitations, or safety warnings.

## 演进方向（需单独评审）

| 方向 | 默认 |
|---|---|
| 接入真实交易所或链上 API | 拒绝，除非有来源、口径、密钥与合规审查 |
| 多标的批量回测 | 试点，先扩展第二份固定 CSV |
| 复制 web3-trading 全栈 | 拒绝作为课程第一版；可参考其报告分层 |
