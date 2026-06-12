# -*- coding: utf-8 -*-

import asyncio
import json

import pytest


@pytest.fixture()
def task_store(tmp_path, monkeypatch):
    root = tmp_path / "llm_signal_tasks"
    monkeypatch.setenv("LLM_SIGNAL_TASK_DIR", str(root))
    import dao.local.signal_task_store as store

    monkeypatch.setattr(store, "_STORE_ROOT", root)
    monkeypatch.setattr(store, "_INDEX_PATH", root / "index.json")
    monkeypatch.setattr(store, "_TASKS_DIR", root / "tasks")
    return store


def test_create_and_poll_task_lifecycle(task_store):
    async def _run():
        task_id = await task_store.create_task("BTC", "deepseek/deepseek-v4-pro")
        pending = await task_store.get_task(task_id)
        assert pending["status"] == "pending"
        assert pending["symbol"] == "BTC"
        assert pending["result"] is None

        await task_store.update_task_running(task_id)
        running = await task_store.get_task(task_id)
        assert running["status"] == "running"

        result = {"ok": True, "signal": "BUY", "score": 42.0}
        await task_store.update_task_done(task_id, result)
        done = await task_store.get_task(task_id)
        assert done["status"] == "done"
        assert done["result"] == result
        assert done["error"] is None

        recent = await task_store.list_recent_tasks(limit=10, symbol="BTC")
        assert len(recent) == 1
        assert recent[0]["taskId"] == task_id
        assert "result" not in recent[0]

        return task_id

    task_id = asyncio.run(_run())
    task_path = task_store._TASKS_DIR / f"{task_id}.json"
    index_path = task_store._INDEX_PATH
    assert task_path.exists()
    assert index_path.exists()
    with task_path.open(encoding="utf-8") as file:
        payload = json.load(file)
    assert payload["taskId"] == task_id
    assert payload["result"]["signal"] == "BUY"


def test_failed_task_persisted(task_store):
    async def _run():
        task_id = await task_store.create_task("ETH", "deepseek/deepseek-v4-pro")
        await task_store.update_task_failed(task_id, "timeout")
        row = await task_store.get_task(task_id)
        assert row["status"] == "failed"
        assert row["error"] == "timeout"

    asyncio.run(_run())
