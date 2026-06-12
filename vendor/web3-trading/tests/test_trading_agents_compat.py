# -*- coding: utf-8 -*-
"""
Lightweight tests that avoid importing `agent` package top-level (redis init).
Run: PYTHONPATH=src python -m pytest tests/test_trading_agents_compat.py
"""

import importlib.util
from pathlib import Path

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None  # type: ignore

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "src" / "agent" / "trading_agents" / "crypto_ta_tools.py"


def _load_crypto_ta_tools():
    spec = importlib.util.spec_from_file_location("ta_crypto_ta_tools", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_normalize_base_from_yahoo():
    m = _load_crypto_ta_tools()
    assert m._normalize_base_symbol("BTC-USD") == "BTC"
    assert m._normalize_base_symbol("eth-usdt") == "ETH"
    assert m._normalize_base_symbol("XRP") == "XRP"


if pytest:

    @pytest.mark.skip(reason="Requires full app init (config, redis); covered in integration")
    def test_resolve_ticker_smoke():
        from agent.trading_agents.compat import resolve_ticker_from_query

        assert resolve_ticker_from_query("如何看 BTC 走势") == "BTC"
        assert resolve_ticker_from_query("") is None
