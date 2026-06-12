# -*- coding: utf-8 -*-
"""Bridge module: reuse local project wrapper utilities."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_local_wrapper_module():
	"""Load src/libs/wrapper.py directly when top-level import is shadowed."""
	wrapper_path = Path(__file__).resolve().parents[2] / "libs" / "wrapper.py"
	spec = importlib.util.spec_from_file_location("_vendor_bridge_local_wrapper", wrapper_path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Unable to load wrapper module from {wrapper_path}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


try:
	from libs.wrapper import async_property, usage_time, usage_http_time, async_retry
except Exception:
	_wrapper = _load_local_wrapper_module()
	async_property = _wrapper.async_property
	usage_time = _wrapper.usage_time
	usage_http_time = _wrapper.usage_http_time
	async_retry = _wrapper.async_retry


__all__ = [
	"async_property",
	"usage_time",
	"usage_http_time",
	"async_retry",
]
