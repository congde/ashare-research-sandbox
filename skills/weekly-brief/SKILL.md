---
name: weekly-brief
description: Turn scattered notes and links into a structured weekly report ready for review or sharing.
---

# Weekly brief

Use this skill when the user asks for a weekly summary, status report, or
recurring personal/work update from notes, chat logs, or attached files.

## Workflow

1. Read the user's Brief and any `@` attachments or linked sources.
2. Separate confirmed facts, inferences, recommendations, and unknowns.
3. Fill `assets/report-template.md` without inventing metrics or events.
4. Mark anything not supported by a source as unknown.
5. Run verification before returning the report.

## Required report content

- This week
- Outcomes
- Blockers
- Next week
- Unknowns

Before returning the report, run:

```bash
python skills/weekly-brief/scripts/verify_report.py PATH_TO_REPORT
```

If verification cannot run, say why instead of claiming the report is complete.
