# -*- coding: utf-8 -*-
"""Integration test: local task store matches dashboard_api task lifecycle."""

import asyncio
import json

import pytest


@pytest.fixture()
def task_dao(tmp_path, monkeypatch):
    root = tmp_path / "llm_signal_tasks"
    monkeypatch.setenv("LLM_SIGNAL_TASK_DIR", str(root))
    import dao.local.signal_task_store as store

    monkeypatch.setattr(store, "_STORE_ROOT", root)
    monkeypatch.setattr(store, "_INDEX_PATH", root / "index.json")
    monkeypatch.setattr(store, "_TASKS_DIR", root / "tasks")

    import importlib
    import dao.local.signal_task_store as dao

    importlib.reload(dao)
    return dao, store


def test_dashboard_task_lifecycle_writes_local_files(task_dao):
    dao, store = task_dao

    async def _run():
        task_id = await dao.create_task("BTC", "deepseek/deepseek-v4-pro")
        await dao.update_task_running(task_id)

        result = {
            "ok": True,
            "signal": "WEAK_BUY",
            "signalLabel": "偏多观望",
            "engine": "llm",
            "score": 15.0,
            "confidence": 62.0,
        }
        await dao.update_task_done(task_id, result)

        polled = await dao.get_task(task_id)
        assert polled["status"] == "done"
        assert polled["result"]["signal"] == "WEAK_BUY"

        recent = await dao.list_recent_tasks(symbol="BTC")
        assert recent[0]["taskId"] == task_id
        assert "result" not in recent[0]

        task_path = store._TASKS_DIR / f"{task_id}.json"
        index_path = store._INDEX_PATH
        assert task_path.exists()
        assert index_path.exists()

        with task_path.open(encoding="utf-8") as file:
            on_disk = json.load(file)
        assert on_disk["symbol"] == "BTC"
        assert on_disk["model"] == "deepseek/deepseek-v4-pro"
        assert on_disk["result"]["engine"] == "llm"

        with index_path.open(encoding="utf-8") as file:
            index = json.load(file)
        assert task_id in index["tasks"]
        assert index["tasks"][task_id]["status"] == "done"

    asyncio.run(_run())
