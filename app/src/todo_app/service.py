from __future__ import annotations

from typing import Iterable

from .models import Priority, Todo, TodoFilter


class TodoService:
    """内存 Todo 服务，供各讲工单练习使用。"""

    def __init__(self) -> None:
        self._todos: dict[int, Todo] = {}
        self._next_id = 1

    def add(
        self,
        title: str,
        *,
        priority: Priority = Priority.MEDIUM,
        tags: Iterable[str] | None = None,
    ) -> Todo:
        todo = Todo(
            id=self._next_id,
            title=title.strip(),
            priority=priority,
            tags=list(tags or []),
        )
        self._todos[todo.id] = todo
        self._next_id += 1
        return todo

    def get(self, todo_id: int) -> Todo | None:
        return self._todos.get(todo_id)

    def list(self, flt: TodoFilter | None = None) -> list[Todo]:
        items = list(self._todos.values())
        if flt is None:
            return items

        if flt.done is not None:
            items = [t for t in items if t.done is flt.done]
        if flt.tag is not None:
            items = [t for t in items if flt.tag in t.tags]
        if flt.min_priority is not None:
            # BUG(#003): 应为 >=，当前 > 导致等于阈值的项被错误过滤
            items = [t for t in items if t.priority > flt.min_priority]
        return items

    def mark_done(self, todo_id: int) -> Todo:
        todo = self._require(todo_id)
        todo.done = True
        return todo

    def sort_by_priority(self, todos: list[Todo]) -> list[Todo]:
        """按优先级降序排列（HIGH → MEDIUM → LOW）。"""
        # BUG(#001): 缺少 reverse=True，当前为升序 —— 讲 3 热修复目标
        return sorted(todos, key=lambda t: t.priority)

    def _require(self, todo_id: int) -> Todo:
        todo = self.get(todo_id)
        if todo is None:
            raise KeyError(f"Todo {todo_id} not found")
        return todo
