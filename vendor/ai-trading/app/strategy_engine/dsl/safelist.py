"""Strategy DSL safe-list — the source of truth for allowed / denied
imports, builtins and attributes used by the AST validator.

Per ADR-0007: a restricted Python subset is the first of three
defense layers (the others being AST validation + Docker sandbox).
This file MUST be the only place those lists are declared so that
the validator, the LLM prompt template, and the user-facing error
strings remain in sync.
"""

from __future__ import annotations

ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        # Python language essentials (safe with no side-effects)
        "__future__",
        # Data science
        "pandas",
        "numpy",
        "talib",
        "decimal",
        "math",
        "statistics",
        "datetime",
        "typing",
        "dataclasses",
        "json",
        "enum",
        "collections",
        # Platform SDK — only safe surface exposed to user strategies.
        "ai_trading.api",
    }
)

DENIED_IMPORTS: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "urllib",
        "urllib.request",
        "urllib.parse",
        "requests",
        "http",
        "http.client",
        "asyncio.subprocess",
        "ctypes",
        "importlib",
        "_thread",
        "threading",
        "multiprocessing",
        "concurrent",
        "ast",
        "code",
        "codeop",
        "pickle",
        "shelve",
        "dbm",
        "shutil",
        "pathlib",
        "tempfile",
    }
)

DENIED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
        "memoryview",
        "breakpoint",
    }
)

DENIED_ATTRS: frozenset[str] = frozenset(
    {
        # Reflection escape hatches
        "__globals__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__code__",
        "__closure__",
        "__dict__",
        # Dangerous APIs (even from allowed imports)
        "system",
        "popen",
        "execvp",
        "execvpe",
        "spawn",
        "spawnv",
        "fork",
    }
)

REQUIRED_FUNCTION_NAME = "on_tick"
REQUIRED_FUNCTION_ARGS: tuple[str, ...] = ("ctx", "candle")
MAX_LINES_OF_CODE = 500
