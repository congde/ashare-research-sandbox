"""Unit tests for app.strategy_engine.dsl.validator.

Per [implementation/05-testing-qa.md §5.4 抗幻觉 Eval] and
[ADR-0007 §10.5 抗幻觉 Eval 集 — 故意诱导生成危险代码 → 必拒].
"""

from __future__ import annotations

import textwrap

import pytest

from app.strategy_engine.dsl import validate_strategy_code
from app.strategy_engine.dsl.safelist import MAX_LINES_OF_CODE


# ── Happy path ───────────────────────────────────────────────────────────
def test_valid_grid_strategy_passes() -> None:
    code = textwrap.dedent("""
        from ai_trading.api import fetch_ohlcv, position, order_intent, log
        import pandas as pd

        def on_tick(ctx, candle):
            df = fetch_ohlcv(ctx.symbol, "1h", limit=200)
            sma_20 = df["close"].rolling(20).mean().iloc[-1]
            sma_50 = df["close"].rolling(50).mean().iloc[-1]
            pos = position(ctx.symbol)
            if sma_20 > sma_50 and pos.qty == 0:
                return order_intent(side="buy", qty=0.01, type="market")
            return None
    """)
    result = validate_strategy_code(code)
    assert result.valid, result.errors
    assert result.ast_hash != ""
    assert result.line_count > 0


def test_valid_minimal_on_tick() -> None:
    code = "def on_tick(ctx, candle):\n    return None\n"
    result = validate_strategy_code(code)
    assert result.valid


# ── Missing on_tick ──────────────────────────────────────────────────────
def test_missing_on_tick_function_fails() -> None:
    code = "def helper():\n    return 42\n"
    result = validate_strategy_code(code)
    assert not result.valid
    rules = {e.rule for e in result.errors}
    assert "missing_on_tick" in rules


def test_wrong_on_tick_signature_fails() -> None:
    code = "def on_tick(self, x, y):\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert any(e.rule == "wrong_signature" for e in result.errors)


# ── Denied imports — anti-hallucination Eval ─────────────────────────────
@pytest.mark.parametrize(
    "evil_line",
    [
        "import os",
        "import   os",
        "import sys",
        "import subprocess",
        "import socket",
        "import urllib",
        "import urllib.request",
        "import requests",
        "import threading",
        "import multiprocessing",
        "import ctypes",
        "import importlib",
        "import pickle",
        "import shutil",
    ],
)
def test_blocks_denied_imports(evil_line: str) -> None:
    code = f"{evil_line}\n\ndef on_tick(ctx, candle):\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert any(
        e.rule == "denied_import" for e in result.errors
    ), f"failed to block: {evil_line!r} — errors={result.errors}"


@pytest.mark.parametrize(
    "evil_line",
    [
        "from os import system",
        "from os.path import exists",
        "from urllib.request import urlopen",
        "from subprocess import Popen",
        "from socket import socket",
    ],
)
def test_blocks_denied_from_imports(evil_line: str) -> None:
    code = f"{evil_line}\n\ndef on_tick(ctx, candle):\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert any(e.rule == "denied_import" for e in result.errors)


def test_blocks_unauthorized_import() -> None:
    code = textwrap.dedent("""
        import scipy

        def on_tick(ctx, candle):
            return None
    """)
    result = validate_strategy_code(code)
    assert not result.valid
    assert any(e.rule == "unauthorized_import" for e in result.errors)


# ── Denied builtins ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "evil_call",
    [
        "eval('1+1')",
        "exec('print(1)')",
        "compile('1+1', '', 'eval')",
        "__import__('os')",
        "open('/etc/passwd')",
        "input('hi')",
    ],
)
def test_blocks_denied_builtins_called(evil_call: str) -> None:
    code = f"def on_tick(ctx, candle):\n    {evil_call}\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    rules = {e.rule for e in result.errors}
    assert rules & {"denied_builtin", "denied_call"}


# ── Reflection escape via dunder attrs ───────────────────────────────────
@pytest.mark.parametrize(
    "evil_expr",
    [
        "x = ().__class__",
        "x = ().__class__.__bases__",
        "x = (1).__class__.__mro__",
        "x = object.__subclasses__",
        "x = on_tick.__globals__",
        "x = type.__bases__",
    ],
)
def test_blocks_dunder_attribute_access(evil_expr: str) -> None:
    code = f"def on_tick(ctx, candle):\n    {evil_expr}\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert any(e.rule == "denied_attribute" for e in result.errors)


# ── Denied dangerous attrs (system/popen even from allowed-ish chains) ──
def test_blocks_system_attribute() -> None:
    code = textwrap.dedent("""
        def on_tick(ctx, candle):
            x = ctx.system
            return None
    """)
    result = validate_strategy_code(code)
    assert not result.valid
    denied_attr_errs = [e for e in result.errors if e.rule == "denied_attribute"]
    assert denied_attr_errs, f"expected denied_attribute, got {result.errors}"
    assert any("system" in e.message for e in denied_attr_errs)


# ── Syntax error ─────────────────────────────────────────────────────────
def test_syntax_error_returns_clean_message() -> None:
    code = "def on_tick(ctx, candle:\n    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert result.errors[0].rule == "syntax_error"
    assert "SyntaxError" in result.errors[0].message


# ── Multiple violations reported (not just first) ────────────────────────
def test_reports_multiple_violations() -> None:
    code = textwrap.dedent("""
        import os
        from urllib.request import urlopen

        def on_tick(ctx, candle):
            eval("1+1")
            return None
    """)
    result = validate_strategy_code(code)
    assert not result.valid
    rules = {e.rule for e in result.errors}
    assert "denied_import" in rules
    assert rules & {"denied_builtin", "denied_call"}


# ── Length limit ─────────────────────────────────────────────────────────
def test_too_long_strategy_rejected() -> None:
    body = "    pass\n" * (MAX_LINES_OF_CODE + 5)
    code = f"def on_tick(ctx, candle):\n{body}    return None\n"
    result = validate_strategy_code(code)
    assert not result.valid
    assert result.errors[0].rule == "too_long"


# ── ast_hash determinism ────────────────────────────────────────────────
def test_ast_hash_stable_under_whitespace_changes() -> None:
    code_a = "def on_tick(ctx, candle):\n    return None\n"
    code_b = "def on_tick(ctx, candle):\n\n\n    return None\n\n"
    res_a = validate_strategy_code(code_a)
    res_b = validate_strategy_code(code_b)
    assert res_a.valid and res_b.valid
    assert res_a.ast_hash == res_b.ast_hash


def test_ast_hash_changes_with_logic() -> None:
    code_a = "def on_tick(ctx, candle):\n    return None\n"
    code_b = "def on_tick(ctx, candle):\n    return 1\n"
    res_a = validate_strategy_code(code_a)
    res_b = validate_strategy_code(code_b)
    assert res_a.ast_hash != res_b.ast_hash


# ── to_dict serializable for audit ───────────────────────────────────────
def test_to_dict_serializable() -> None:
    result = validate_strategy_code("import os\n\ndef on_tick(ctx, candle): return None\n")
    payload = result.to_dict()
    assert payload["valid"] is False
    assert isinstance(payload["errors"], list)
    assert all("rule" in e for e in payload["errors"])
