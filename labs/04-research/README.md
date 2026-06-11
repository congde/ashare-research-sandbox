# Lab 04: research report

This lab demonstrates a research deliverable with a traceable claim chain. The
starter report reads well but fails verification because its claims cannot be
traced. The solution links Facts to sources, Inferences to Facts,
Recommendations to Inferences, and Unknowns to explicit next checks.

## Ticket

1. Read [ticket.md](ticket.md) and
   [research-package-template.md](research-package-template.md).
2. Compare `starter/research-report.md` with `solution/research-report.md` and
   `solution/research-package.md`.
3. Copy the template to `my-research-package.md`.
4. Build the question map and claim ledger before drafting the report.
5. Verify your report, then manually complete the source review log.

## Verify the teaching fixture

```bash
make lab-04
```

Windows PowerShell:

```powershell
py scripts/course.py lab-04
```

## Verify your own report

```bash
.venv/bin/python labs/04-research/verify.py \
  path/to/your-report.md path/to/your-research-package.md
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe labs/04-research/verify.py path/to/your-report.md path/to/your-research-package.md
```

Passing the script does not prove that a source supports a claim. Complete the
manual source review log in your research package before considering the lab
finished.
