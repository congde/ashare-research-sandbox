# Ticket: plan a two-week document migration pilot

## Upstream recommendation

Run a two-week pilot on one representative project space before deciding
whether to expand migration. During the pilot, record document body, format,
history, comments, permissions, and team friction.

## Boundaries

- Do not migrate every project space.
- Do not claim the pilot succeeded without evidence and human approval.
- Stop if critical comments or permissions are lost.
- Preserve the source space and record a rollback action.

## Assumed current state for the handoff

- M1 sample selection is complete.
- A01 document body, A02 format, and A03 history checks passed.
- A04 comments failed because comments are missing after import.
- A05 permissions has not run.
- The unique next action is to reproduce and diagnose A04.

## Human review questions

After structural verification, ask:

1. Does each milestone produce evidence that changes the next decision?
2. Are stop conditions observable and paired with rollback actions?
3. Can a new reader continue from the handoff without chat history?
