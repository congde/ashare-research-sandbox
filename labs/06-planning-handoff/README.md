# Lab 06: evidence-gated planning and handoff

This lab teaches a planning discipline for Codex: turn a recommendation into
an executable hypothesis, require evidence before advancing, and leave a
handoff that another reader can continue without chat history.

## Task

1. Read [ticket.md](ticket.md) and predict why the starter files should fail.
2. Run the teaching fixture and inspect the reported failures.
3. Use [plan-template.md](plan-template.md) and
   [handoff-template.md](handoff-template.md) to create `my-plan.md` and
   `my-handoff.md`.
4. Run the verifier on your files until the structural checks pass.
5. Use [review-rubric.md](review-rubric.md) with another reader who can inspect
   only `my-handoff.md`.

## Verify the teaching fixture

```bash
python scripts/course.py lab-06
```

Windows PowerShell:

```powershell
py scripts/course.py lab-06
```

The fixture proves that the checker rejects a busy task list and accepts a
plan with evidence gates, dependencies, stop/rollback rules, and a resumable
handoff.

## Verify your own plan and handoff

```bash
.venv/bin/python labs/06-planning-handoff/verify.py \
  labs/06-planning-handoff/my-plan.md \
  labs/06-planning-handoff/my-handoff.md
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe labs/06-planning-handoff/verify.py labs/06-planning-handoff/my-plan.md labs/06-planning-handoff/my-handoff.md
```

Passing proves that the required control points are present. It does not prove
that the plan is wise, that evidence claims are true, or that a human approved
the next milestone. Complete the handoff test before considering the lab done.
