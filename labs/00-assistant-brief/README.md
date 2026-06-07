# Lab 00: assistant brief

This lab teaches the minimum structure of a delegatable Brief. The starter
example is intentionally incomplete. The solution shows a Brief that Codex (or
another reader) can execute without guessing the goal.

## Task

Read [brief-template.md](brief-template.md), compare `starter/brief.md` with
`solution/brief.md`, then write your own Brief for a **non-code** task such as
research, writing, or planning.

## Verify the teaching fixture

```bash
make lab-00
```

The script proves:

1. The starter Brief fails structural checks.
2. The solution Brief passes the same checks.

## Verify your own Brief

```bash
.venv/bin/python labs/00-assistant-brief/verify.py path/to/your-brief.md
```
