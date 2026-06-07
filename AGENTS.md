# codexDemo project instructions

This repository is the companion workspace for a Codex delivery course. Treat
course prose and executable labs as one product: examples in `docs/v2/` must
match the files and commands that actually exist.

## Repository map

- `docs/v2/`: publishable chapter drafts.
- `labs/`: self-contained exercises and their verification scripts.
- `skills/`: reusable Codex skills taught by the course.
- `docs/samples/`: small source artifacts used by non-code exercises.

## Working rules

- Do not recreate deleted legacy directories such as `app/`, `challenges/`, or
  `harness-kit/`.
- Keep each lab self-contained. A lab must explain its task, include its own
  verification command, and avoid depending on another lab's mutable files.
- When prose names a file or command, verify that it exists and works.
- Prefer a small runnable example over a long hypothetical configuration.
- Do not claim a command passed unless it was actually run.

## Verification

Run the narrow lab check while editing:

```bash
make lab-00
make lab-04
make lab-09
make lab-01
make lab-16
```

Before finishing a repository-wide change, run:

```bash
make check
```

