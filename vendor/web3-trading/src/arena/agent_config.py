# -*- coding: utf-8 -*-
"""Arena Agent runtime configuration."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional


def normalize_agent_id(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _parse_json_object(raw: str) -> Dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_pair_map(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in re.split(r"[,;\n]+", raw or ""):
        if not item.strip():
            continue
        separator = "=" if "=" in item else ":" if ":" in item else ""
        if not separator:
            continue
        key, value = item.split(separator, 1)
        value = value.strip()
        if not value:
            continue
        for agent_name in re.split(r"[|+]", key):
            normalized = normalize_agent_id(agent_name)
            if normalized:
                result[normalized] = value
    return result


def agent_configs() -> Dict[str, Dict[str, Any]]:
    raw = os.getenv("QUANT_ARENA_AGENT_CONFIGS", "")
    data = _parse_json_object(raw)
    configs: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            configs[normalize_agent_id(key)] = value
    return configs


def agent_config(agent_name: str) -> Dict[str, Any]:
    return agent_configs().get(normalize_agent_id(agent_name), {})


def agent_model_map() -> Dict[str, str]:
    raw = os.getenv("QUANT_ARENA_AGENT_MODELS", "")
    data = _parse_json_object(raw)
    if data:
        return {normalize_agent_id(key): str(value).strip() for key, value in data.items() if str(value).strip()}
    return _parse_pair_map(raw)


def model_for_agent(agent_name: str, default: Optional[str] = None) -> Optional[str]:
    normalized = normalize_agent_id(agent_name)
    mapping = agent_model_map()
    mapped = mapping.get(normalized) or mapping.get("default")
    if mapped:
        return mapped
    unified = os.getenv("QUANT_ARENA_DEFAULT_MODEL", "").strip()
    if unified:
        return unified
    config = agent_config(normalized)
    model = str(config.get("model") or "").strip()
    if model:
        return model
    return default


def account_for_agent(agent_name: str, default: Optional[str] = None) -> str:
    normalized = normalize_agent_id(agent_name)
    config = agent_config(normalized)
    account_id = str(config.get("account_id") or config.get("accountId") or "").strip()
    return normalize_agent_id(account_id or default or normalized or "default")