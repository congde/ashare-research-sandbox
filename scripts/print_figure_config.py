"""Shared print settings for course figure generators (300 DPI)."""

from __future__ import annotations

PRINT_DPI = 300
BASE_DPI = 200
PRINT_SCALE = PRINT_DPI / BASE_DPI


def scale(value: float) -> int:
    return int(round(value * PRINT_SCALE))


def scale_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(scale(part) for part in box)


def scale_point(point: tuple[int, int]) -> tuple[int, int]:
    return scale(point[0]), scale(point[1])
