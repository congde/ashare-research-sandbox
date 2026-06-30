from __future__ import annotations

import threading
from typing import Callable

_locks: dict[str, threading.Lock] = {}


def schedule_background_refresh(key: str, fetcher: Callable[[], None]) -> None:
    """Run a live refresh once per key; skip if a refresh is already in flight."""
    lock = _locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        return

    def run() -> None:
        try:
            fetcher()
        except Exception:
            pass
        finally:
            lock.release()

    threading.Thread(target=run, daemon=True).start()
