from __future__ import annotations

import os
from pathlib import Path

from config.web3_trading import apply_yaml_defaults, config_sources, get_dashboard_url, get_upstream_base_url
from paths import PROJECT_ROOT


def _parse_env_file(path: Path, *, override: bool) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def load_env() -> list[str]:
    """Load web3-trading default.yaml + .env files (local override wins)."""
    apply_yaml_defaults()

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

    use_dotenv = False
    try:
        from dotenv import load_dotenv

        use_dotenv = True
    except ImportError:
        load_dotenv = None  # type: ignore[assignment]

    for index, path in enumerate(candidates):
        if not path.is_file():
            continue
        should_override = path == local or index == len(candidates) - 1
        if use_dotenv and load_dotenv is not None:
            load_dotenv(path, override=should_override)
        else:
            _parse_env_file(path, override=should_override)
        loaded.append(str(path))

    apply_yaml_defaults()
    return loaded


def env_status() -> dict:
    loaded = load_env()
    return {
        "loaded_paths": loaded,
        "valuescan": bool(os.environ.get("VS_OPEN_API_KEY") and os.environ.get("VS_OPEN_SECRET_KEY")),
        "dexscan": bool(os.environ.get("DEX_API_KEY") or os.environ.get("DEXSCAN_API_KEY")),
        "llm": bool(os.environ.get("OPENAI_API_KEY")),
        "llm_model": os.environ.get("OPENAI_MODEL", "deepseek-v4-pro"),
        "web3_exchange_public": True,
        "fear_greed_public": True,
        "upstream_base_url": get_upstream_base_url(),
        "dashboard_url": get_dashboard_url(),
        "config_sources": config_sources(),
    }
