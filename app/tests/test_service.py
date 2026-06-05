from todo_app.models import Priority, TodoFilter
from todo_app.service import TodoService


def test_add_and_get():
    svc = TodoService()
    todo = svc.add("写文档", priority=Priority.HIGH, tags=["docs"])
    assert svc.get(todo.id) is todo
    assert todo.title == "写文档"


def test_filter_by_tag():
    svc = TodoService()
    svc.add("A", tags=["backend"])
    svc.add("B", tags=["frontend"])
    result = svc.list(TodoFilter(tag="backend"))
    assert len(result) == 1
    assert result[0].title == "A"


def test_sort_by_priority_desc():
    svc = TodoService()
    low = svc.add("低", priority=Priority.LOW)
    high = svc.add("高", priority=Priority.HIGH)
    medium = svc.add("中", priority=Priority.MEDIUM)
    ordered = svc.sort_by_priority([low, high, medium])
    assert [t.priority for t in ordered] == [Priority.HIGH, Priority.MEDIUM, Priority.LOW]
