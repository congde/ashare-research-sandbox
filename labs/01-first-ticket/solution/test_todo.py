from todo import Task, sort_by_priority


def test_sort_by_priority_puts_urgent_work_first() -> None:
    tasks = [
        Task("update docs", 1),
        Task("restore checkout", 3),
        Task("reply to support", 2),
    ]

    result = sort_by_priority(tasks)

    assert [task.title for task in result] == [
        "restore checkout",
        "reply to support",
        "update docs",
    ]

