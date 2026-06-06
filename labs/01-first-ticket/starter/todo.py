from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    title: str
    priority: int


def sort_by_priority(tasks: list[Task]) -> list[Task]:
    """Return tasks with the most urgent task first."""
    return sorted(tasks, key=lambda task: task.priority)

