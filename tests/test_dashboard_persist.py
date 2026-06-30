from __future__ import annotations

import shutil

from dashboard.persist import annotate_cached, is_persistable_source, maybe_persist
from dashboard.snapshot import history_dir, list_snapshot_history, load_offline, load_snapshot, save_snapshot, snapshot_path


def _cleanup_test_dataset(name: str) -> None:
    snapshot_path(name).unlink(missing_ok=True)
    hist = history_dir(name)
    if hist.is_dir():
        shutil.rmtree(hist)


def test_save_snapshot_keeps_history_entries() -> None:
    name = "test_persist_history"
    _cleanup_test_dataset(name)
    sample = {"ok": True, "chance": [{"symbol": "BTC"}], "risk": [], "funds": []}
    first = save_snapshot(name, sample, origin="live")
    second = save_snapshot(name, {**sample, "chance": [{"symbol": "ETH"}]}, origin="live")
    assert first != second
    history = list_snapshot_history(name)
    assert len(history) >= 2
    latest = load_snapshot(name)
    assert latest is not None
    assert latest["chance"][0]["symbol"] == "ETH"
    _cleanup_test_dataset(name)


def test_snapshot_history_skips_corrupt_entries() -> None:
    name = "test_persist_corrupt_history"
    _cleanup_test_dataset(name)
    sample = {"ok": True, "chance": [{"symbol": "BTC"}], "risk": [], "funds": []}
    valid = save_snapshot(name, sample, origin="live")
    broken = history_dir(name) / "9999-empty.json"
    broken.write_text("", encoding="utf-8")

    history = list_snapshot_history(name)
    assert all(row["path"] != str(broken) for row in history)
    assert any(row["path"] == str(valid) for row in history)
    assert load_snapshot(name)["chance"][0]["symbol"] == "BTC"
    _cleanup_test_dataset(name)


def test_maybe_persist_skips_fixture_source() -> None:
    name = "test_persist_skip"
    _cleanup_test_dataset(name)
    maybe_persist(
        "ai_picks",
        {"ok": True, "source": "fixture", "chance": [{"symbol": "BTC"}], "risk": [], "funds": []},
    )
    assert load_snapshot(name) is None
    assert not is_persistable_source({"ok": True, "source": "fixture"})


def test_load_offline_prefers_latest_snapshot_over_fixture() -> None:
    name = "test_persist_priority"
    _cleanup_test_dataset(name)
    sample = {"ok": True, "chance": [{"symbol": "SNAP"}], "risk": [], "funds": []}
    save_snapshot(name, sample, origin="live")
    payload = load_offline(name)
    assert payload["chance"][0]["symbol"] == "SNAP"
    assert payload.get("source") == "snapshot"
    _cleanup_test_dataset(name)


def test_annotate_cached_marks_live_error() -> None:
    cached = annotate_cached(
        {
            "ok": True,
            "source": "snapshot",
            "snapshot": {"saved_at": "2026-06-13T00:00:00+00:00"},
            "chance": [{"symbol": "BTC"}],
        }
    )
    assert cached["live_error"] is True
    assert cached["cached_at"] == "2026-06-13T00:00:00+00:00"
    assert cached["source"] == "snapshot"
