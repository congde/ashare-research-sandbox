# Pilot handoff

## Current state

- M1 passed.
- M2 is stopped: A01-A03 passed, A04 failed, and A05 is not run.

## Evidence

- passed: A01 document body, A02 format, A03 history.
- failed: A04 comments are missing after import.
- not run: A05 owner/editor/viewer permission probes.

## Single next action

- Reproduce and diagnose A04, recording steps and evidence.

## Stop and rollback

- Stop M2 while A04 comments are missing.
- Rollback: do not replace the source space; remove only the affected pilot
  import after preserving the failure record.

## Missing information

- Whether A04 has a supported preservation path.
- Whether access is available to run A05.

## Forbidden actions

- Do not continue to M3.
- Do not migrate every project space or claim success.
