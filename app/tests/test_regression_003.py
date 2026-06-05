from todo_app.models import Priority, TodoFilter
from todo_app.service import TodoService


def test_list_done_and_min_priority():
    svc = TodoService()
    svc.add("低未完成", priority=Priority.LOW)
    svc.add("高未完成", priority=Priority.HIGH)
    done = svc.add("高已完成", priority=Priority.HIGH)
    svc.mark_done(done.id)

    result = svc.list(TodoFilter(done=False, min_priority=Priority.HIGH))
    assert len(result) == 1
    assert result[0].title == "高未完成"
