# Lab 00: assistant brief

This lab teaches the minimum structure of a delegatable Brief. The starter
example is intentionally incomplete. The solution shows one valid Brief for the
course's note-app scenario—use it for comparison **after** your own draft passes.

## Task

1. Read [brief-template.md](brief-template.md) and [starter/brief.md](starter/brief.md).
   Note what is missing **before** opening `solution/brief.md`.
2. Copy `brief-template.md` to `my-brief.md` in this directory.
3. Fill every section for a **non-code** task (research, writing, or planning).
4. Run `verify.py` on `my-brief.md` until it passes.
5. Only then open [solution/brief.md](solution/brief.md) and compare differences.

## Verify the teaching fixture

```bash
python scripts/course.py lab-00
```

Also available via `make lab-00` if you prefer Make.

The script proves the checker itself works:

1. The starter Brief fails structural checks.
2. The solution Brief passes the same checks.

Passing `lab-00` alone does not complete the lab—you still need your own Brief
to pass `verify.py`.

## Verify your own Brief

```bash
python labs/00-assistant-brief/verify.py labs/00-assistant-brief/my-brief.md
```

`my-brief.md` is gitignored so your exercise draft stays local.
