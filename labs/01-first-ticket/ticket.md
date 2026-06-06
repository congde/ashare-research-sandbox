# Ticket HOTFIX-001: priority order is reversed

Customer support reports that the work queue shows low-priority items before
urgent items.

## Goal

Return tasks in descending priority order.

## Constraints

- Keep the public `sort_by_priority(tasks)` function.
- Do not change the test expectation.
- Do not add a dependency or refactor unrelated code.

## Done when

```bash
python -m pytest labs/01-first-ticket/workspace -q
```

passes after the learner applies the fix in `workspace/todo.py`.

