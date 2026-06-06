---
name: repo-readiness
description: Inspect an unfamiliar repository and produce a concise readiness report before editing code.
---

# Repository readiness

Use this skill when the user asks to understand, onboard to, or assess an
unfamiliar repository before making changes.

## Workflow

1. Read the repository-level `AGENTS.md` and `README.md` when present.
2. Inspect the top-level file tree and identify build, test, lint, and CI entry
   points.
3. Run only safe, read-only discovery commands first.
4. Run the documented baseline verification command when dependencies are
   available.
5. Write a readiness report using `assets/report-template.md`.
6. Clearly separate confirmed facts, inferences, and unknowns.
7. Do not modify product code during this workflow.

## Required report content

- Purpose
- Entrypoints
- Verification
- Risks
- Unknowns

Before returning the report, run:

```bash
python skills/repo-readiness/scripts/verify_report.py PATH_TO_REPORT
```

If verification cannot run, say why instead of claiming the report is complete.

