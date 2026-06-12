from __future__ import annotations

import os
from pathlib import Path

from config.web3_trading import apply_yaml_defaults, config_sources, get_dashboard_url, get_upstream_base_url
from paths import PROJECT_ROOT


def load_env() -> list[str]:
    """Load web3-trading default.yaml + .env files (local override wins)."""
    apply_yaml_defaults()

    try:
        from dotenv import load_dotenv
    except ImportError:
        return []

    loaded: list[str] = []
    candidates: list[Path] = []

    sibling = PROJECT_ROOT.parent / "web3-trading" / ".env"
    if sibling.is_file():
        candidates.append(sibling)

    explicit = os.environ.get("WEB3_TRADING_ENV", "").strip()
    if explicit:
        candidates.append(Path(explicit))

    local = PROJECT_ROOT / ".env"
    if local.is_file():
        candidates.append(local)

    for index, path in enumerate(candidates):
        if not path.is_file():
            continue
        load_dotenv(path, override=path == local or index == len(candidates) - 1)
        loaded.append(str(path))

    apply_yaml_defaults()
    return loaded


def env_status() -> dict:
    loaded = load_env()
    return {
        "loaded_paths": loaded,
        "valuescan": bool(os.environ.get("VS_OPEN_API_KEY") and os.environ.get("VS_OPEN_SECRET_KEY")),
        "dexscan": bool(os.environ.get("DEX_API_KEY") or os.environ.get("DEXSCAN_API_KEY")),
        "kucoin_public": True,
        "fear_greed_public": True,
        "upstream_base_url": get_upstream_base_url(),
        "dashboard_url": get_dashboard_url(),
        "config_sources": config_sources(),
    }
