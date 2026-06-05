from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class Priority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Todo:
    id: int
    title: str
    done: bool = False
    priority: Priority = Priority.MEDIUM
    tags: list[str] = field(default_factory=list)


@dataclass
class TodoFilter:
    done: Optional[bool] = None
    tag: Optional[str] = None
    min_priority: Optional[Priority] = None
