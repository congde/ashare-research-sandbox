# Entry decision: note-app research

## Task dependencies

- Authoritative task: `labs/04-research/ticket.md`
- Intended deliverable: `labs/04-research/my-research-report.md`
- Required verification: `python labs/04-research/verify.py labs/04-research/my-research-report.md`

## Capability matrix

| Capability | Required? | Probe | Result | Evidence | Stop or downgrade action |
|---|---|---|---|---|---|
| Read the authoritative task file | yes | Open `labs/04-research/ticket.md` | passed | The task headings and Done when were read from the file | Stop; do not reconstruct the task from chat |
| Write the intended deliverable | yes | Create the report only after approval | not run | No report should exist during entry preparation | Stop before research until write access is confirmed |
| Run the required verification | yes | Run `py scripts/course.py lab-04` to test the fixture | not run | Command must be recorded when executed | Mark verification not run; never claim the report passed |
| Access official public sources | yes | Open one official pricing page | not run | URL and access result must be recorded during research | Downgrade unsupported claims to Unknowns |

## Chosen entry

Use Codex App with this repository opened because the task needs local file
context, controlled writes, terminal execution, and interactive approval. Use
its browser capability, when available and permitted, for official sources.
The choice remains conditional until the required probes above pass.

## Entry limitations

- Public-page access has not yet been probed, so no pricing fact may be claimed.
- Background execution is unnecessary and should not be enabled.
- The entry may draft a recommendation but cannot make the migration decision.

## Workspace contract

### Read before work

- Read `labs/04-research/ticket.md` before using chat context.
- Treat official product pages as the authority for Facts.

### Allowed writes

- Write only `labs/04-research/my-research-report.md` for the research task.

### Evidence and uncertainty

- Every Fact needs a source URL.
- Put unsupported or unreachable claims in `Unknowns`.

### Verification

- Run `python labs/04-research/verify.py labs/04-research/my-research-report.md`.
- Record the command result; a script pass does not replace source review.

### Forbidden actions

- Do not modify `starter/` or `solution/`.
- Do not claim a probe or verification passed unless it ran.
- Do not treat chat output as the deliverable.

## Human approval gates

- A human verifies at least one pricing fact on an official page.
- A human decides whether to migrate.
- Writing outside the allowed report path requires approval.
