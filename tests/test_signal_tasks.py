from __future__ import annotations

import time

from dashboard.signal_tasks import create_task, get_task, poll_task, submit_task


def test_submit_and_poll_task_without_llm(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_run(task_id: str, symbol: str, model: str) -> None:
        from dashboard.signal_tasks import update_task

        update_task(
            task_id,
            status="done",
            result={"ok": True, "signal": "HOLD", "signalLabel": "观望", "engine": "sandbox-rule-based"},
        )

    monkeypatch.setattr("dashboard.signal_tasks._run_task", fake_run)
    payload = submit_task("BTC", "deepseek-v4-pro")
    assert payload.get("ok") is True
    task_id = payload.get("taskId")
    assert task_id

    deadline = time.time() + 3
    result = {"status": "pending"}
    while time.time() < deadline and result.get("status") not in {"done", "failed"}:
        result = poll_task(task_id)
        time.sleep(0.05)
    assert result.get("status") == "done"
    assert result.get("data", {}).get("signal") == "HOLD"


def test_create_task_persists_record() -> None:
    task_id = create_task("ETH", "deepseek-v4-pro")
    task = get_task(task_id)
    assert task is not None
    assert task.get("symbol") == "ETH"
    assert task.get("status") == "pending"
