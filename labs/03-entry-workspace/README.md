# Lab 03: entry and workspace contract

This lab turns entry selection into an evidence-backed decision. The goal is
not to choose a universally "best" Codex surface. The goal is to prove that
the chosen surface can satisfy the task's minimum capability contract, and to
define an honest fallback for every missing capability.

## Task

1. Read [ticket.md](ticket.md) and [entry-decision-template.md](entry-decision-template.md).
2. Predict why [starter/entry-decision.md](starter/entry-decision.md) should fail.
3. Run the teaching fixture and inspect the reported failures.
4. Copy the template to `my-entry-decision.md`.
5. Perform the probes listed in your capability matrix. Record results as
   `passed`, `failed`, or `not run`; do not claim a probe passed without
   evidence.
6. Run `verify.py` on your own decision file until its structural checks pass.
7. Compare with [solution/entry-decision.md](solution/entry-decision.md), then
   manually review whether your evidence actually supports the chosen entry.

## Verify the teaching fixture

```bash
python scripts/course.py lab-03
```

Windows PowerShell:

```powershell
py scripts/course.py lab-03
```

The fixture proves that the checker rejects an unsupported preference and
accepts a decision that includes probes, fallbacks, workspace rules, and human
approval gates.

## Verify your own decision

```bash
python labs/03-entry-workspace/verify.py labs/03-entry-workspace/my-entry-decision.md
```

Passing the script proves that the decision record has the required structure.
It does not prove that a claimed probe actually ran. Manually compare every
`passed` claim with terminal output, a readable file, or another concrete
artifact.
