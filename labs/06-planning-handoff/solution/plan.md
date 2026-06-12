# Pilot plan

## Goal and decision

Decide whether evidence supports expanding beyond one representative project
space after two weeks. A human owner makes the expansion decision.

## Scope and non-scope

- In scope: one representative project space and five checks, A01-A05.
- Non-scope: all other project spaces, procurement, and organization rollout.

## Unknowns

- Whether A04 comments can be preserved. Impact: loss would make migration
  unacceptable. Next check: reproduce one missing-comment import.
- Whether A05 role permissions match the source. Impact: incorrect access can
  expose or hide documents. Next check: run owner/editor/viewer probes.

## Evidence gates

| Milestone | Evidence | Entry condition | Pass condition | Stop or return | Owner |
|---|---|---|---|---|---|
| M1 sample | Sample list and rationale | Brief approved | Sample represents the workflow | Return if key document types are absent | Team owner |
| M2 fidelity | A01-A05 records | M1 passed | All checks recorded with no critical loss | Stop on comment or permission loss; preserve source | Codex records, human approves |
| M3 use | Friction and task records | M2 passed | Feedback covers representative work | Return if core workflow is untested | Team members |
| M4 decision | Recommendation linked to evidence | M3 passed | Human decision is recorded | Do not expand when evidence is incomplete | Human owner |

## Dependencies and ownership

- The human owner selects the sample and approves any scope expansion.
- Access and target version must be confirmed before M2.
- Missing permission access blocks A05 and must be recorded as not run.

## Verification boundary

- `python labs/06-planning-handoff/verify.py labs/06-planning-handoff/solution/plan.md labs/06-planning-handoff/solution/handoff.md`
  proves required planning structures are present.
- It does not prove the migration evidence is true or the pilot succeeded.

## Forbidden actions

- Do not migrate every project space.
- Do not call the pilot successful without M4 human approval.
