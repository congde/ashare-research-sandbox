from __future__ import annotations

import importlib.util
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_app_module():
    spec = importlib.util.spec_from_file_location("sandbox_app", ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app_module():
    return _load_app_module()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server(app_module):
    port = _free_port()
    httpd = app_module.SandboxHTTPServer(("127.0.0.1", port), app_module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_spa_route_serves_index_html(server: str) -> None:
    with urllib.request.urlopen(f"{server}/trading") as response:
        body = response.read().decode("utf-8")
    assert response.status == 200
    assert 'id="root"' in body
    assert "<!doctype html>" in body.lower()


def test_dashboard_alias_serves_index_html(server: str) -> None:
    with urllib.request.urlopen(f"{server}/dashboard") as response:
        body = response.read().decode("utf-8")
    assert response.status == 200
    assert 'id="root"' in body


def test_kline_analysis_api(server: str) -> None:
    import json

    with urllib.request.urlopen(f"{server}/api/market/kline-analysis?symbol=BTC-USDT&type=1day&limit=60") as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload.get("ok") is True
    assert payload.get("candles")


def test_signal_analysis_api(server: str) -> None:
    import json

    with urllib.request.urlopen(f"{server}/api/dashboard/signal-analysis?symbol=BTC") as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload.get("ok") is True
    assert payload.get("logicFlow")


def test_llm_signal_submit_returns_task(server: str) -> None:
    import json

    with urllib.request.urlopen(
        f"{server}/api/dashboard/llm-signal-analysis?symbol=BTC&model=deepseek/deepseek-v4-pro"
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload.get("ok") is True
    assert payload.get("taskId") or payload.get("signal")


def test_missing_asset_still_404(server: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server}/assets/missing.js")
    assert exc.value.code == 404
