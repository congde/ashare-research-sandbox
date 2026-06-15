from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import PROJECT_ROOT

YAML_ENV_MAP = {
    "dexscan_api_base_url": ("DEX_BASE_URL", "DEXSCAN_API_BASE_URL"),
    "vs_open_api_base_url": ("VS_OPEN_API_BASE_URL",),
    "quant_arena_quote": ("QUANT_ARENA_QUOTE",),
}


def web3_trading_root() -> Path | None:
    explicit = os.environ.get("WEB3_TRADING_ROOT", "").strip()
    if explicit:
        root = Path(explicit)
        return root if root.is_dir() else None
    sibling = PROJECT_ROOT.parent / "web3-trading"
    return sibling if sibling.is_dir() else None


@lru_cache(maxsize=1)
def load_default_yaml() -> dict[str, Any]:
    root = web3_trading_root()
    if not root:
        return {}
    path = root / "conf" / "default.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def apply_yaml_defaults() -> None:
    data = load_default_yaml()
    for yaml_key, env_keys in YAML_ENV_MAP.items():
        value = data.get(yaml_key)
        if value in (None, ""):
            continue
        for env_key in env_keys:
            if not os.environ.get(env_key):
                os.environ[env_key] = str(value)


def get_upstream_base_url() -> str | None:
    explicit = os.environ.get("WEB3_TRADING_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    mode = os.environ.get("WEB3_TRADING_UPSTREAM", "never").strip().lower()
    if mode == "never":
        return None

    host = os.environ.get("SERVER_HOST", "").strip()
    port = os.environ.get("SERVER_PORT", "").strip()
    if not port:
        yaml_data = load_default_yaml()
        if yaml_data.get("server_host"):
            host = host or str(yaml_data["server_host"])
        if yaml_data.get("server_port"):
            port = str(yaml_data["server_port"])

    if not host:
        host = "127.0.0.1"
    if host in ("0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    if port:
        return f"http://{host}:{port}"
    return None


def get_dashboard_url() -> str | None:
    base = get_upstream_base_url()
    return f"{base}/dashboard" if base else None


def get_watch_symbols() -> list[str]:
    raw = (
        os.environ.get("VS_SSE_WATCH_SYMBOLS")
        or os.environ.get("QUANT_ARENA_SYMBOLS")
        or load_default_yaml().get("vs_sse_watch_symbols")
        or load_default_yaml().get("quant_arena_symbols")
        or "BTC"
    )
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def primary_market_symbol() -> str:
    symbols = get_watch_symbols()
    token = symbols[0] if symbols else "BTC"
    quote = os.environ.get("QUANT_ARENA_QUOTE") or load_default_yaml().get("quant_arena_quote") or "USDT"
    pair = f"{token}-{quote}".upper()
    return pair if "-" in pair else f"{token}-USDT"


def config_sources() -> dict[str, Any]:
    root = web3_trading_root()
    yaml_path = str(root / "conf" / "default.yaml") if root else None
    env_paths: list[str] = []
    sibling_env = PROJECT_ROOT.parent / "web3-trading" / ".env"
    if sibling_env.is_file():
        env_paths.append(str(sibling_env))
    explicit = os.environ.get("WEB3_TRADING_ENV", "").strip()
    if explicit:
        env_paths.append(explicit)
    local_env = PROJECT_ROOT / ".env"
    if local_env.is_file():
        env_paths.append(str(local_env))
    return {
        "web3_trading_root": str(root) if root else None,
        "default_yaml": yaml_path if yaml_path and Path(yaml_path).is_file() else None,
        "env_files": env_paths,
    }
