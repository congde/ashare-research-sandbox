# -*- coding: utf-8 -*-
"""Corporate TLS CA bundle materialization for Python / Node / uv subprocesses.

Behind McAfee / Zscaler MITM proxies, ``npx`` and ``uvx`` fail with
``SELF_SIGNED_CERT_IN_CHAIN`` unless the corporate root is in the trust store
this module builds.

Env (see ``.env.example``):

  * ``AIBUDDY_CA_BUNDLE`` — explicit PEM file (highest priority)
  * ``AIBUDDY_CA_CERT_DIR`` — directory of ``.pem`` / ``.crt`` files to merge
  * Default cache: ``~/.aibuddy/ca-bundle.pem``

Subprocess env keys set when a bundle exists:

  ``SSL_CERT_FILE``, ``REQUESTS_CA_BUNDLE``, ``NODE_EXTRA_CA_CERTS``,
  ``NPM_CONFIG_CAFILE``, ``UV_NATIVE_TLS=true`` (uv uses native TLS + above).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Mapping, Optional, Union

logger = logging.getLogger(__name__)

_CERT_SUFFIXES = {".pem", ".crt", ".cer"}


def _default_cache_path() -> Path:
    return Path.home() / ".aibuddy" / "ca-bundle.pem"


def _repo_certificate_dir() -> Optional[Path]:
    """``<repo>/Certificate`` when present (local McAfee root)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "Certificate"
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
        if (parent / ".git").exists() or (parent / "main.py").exists():
            break
    return None


def _collect_pem_paths(cert_dir: Union[str, Path]) -> list[Path]:
    root = Path(cert_dir).expanduser().resolve()
    if not root.is_dir():
        return []
    paths: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in _CERT_SUFFIXES:
            continue
        paths.append(entry)
    return paths


def _read_pem_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("ssl_ca: cannot read %s: %s", path, exc)
        return ""


def materialize_ca_bundle(
    *,
    cert_dir: Optional[str] = None,
    cache_path: Optional[str] = None,
    include_certifi: bool = True,
) -> Optional[str]:
    """Merge PEM files into ``cache_path``; return absolute path or ``None``."""
    explicit = (os.getenv("AIBUDDY_CA_BUNDLE") or "").strip()
    if explicit:
        bundle = Path(explicit).expanduser().resolve()
        if bundle.is_file():
            return str(bundle)
        logger.warning("ssl_ca: AIBUDDY_CA_BUNDLE not found: %s", bundle)

    out_path = Path(cache_path).expanduser() if cache_path else _default_cache_path()
    parts: list[str] = []

    if include_certifi:
        try:
            import certifi

            parts.append(Path(certifi.where()).read_text(encoding="utf-8").strip())
        except Exception as exc:
            logger.debug("ssl_ca: certifi unavailable: %s", exc)

    dir_raw = (cert_dir or os.getenv("AIBUDDY_CA_CERT_DIR") or "").strip()
    if not dir_raw:
        auto = _repo_certificate_dir()
        if auto is not None:
            dir_raw = str(auto)
    if dir_raw:
        for pem_file in _collect_pem_paths(dir_raw):
            chunk = _read_pem_file(pem_file)
            if chunk:
                parts.append(chunk)

    if not parts:
        return None

    merged = "\n".join(parts)
    if merged and not merged.endswith("\n"):
        merged += "\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="ca-bundle-", suffix=".pem", dir=str(out_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(merged)
        os.replace(tmp, out_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return str(out_path.resolve())


def _resolve_bundle_path() -> Optional[str]:
    cached = materialize_ca_bundle()
    if cached:
        return cached
    explicit = (os.getenv("AIBUDDY_CA_BUNDLE") or "").strip()
    if explicit and Path(explicit).expanduser().is_file():
        return str(Path(explicit).expanduser().resolve())
    legacy = (os.getenv("SSL_CERT_FILE") or "").strip()
    if legacy and Path(legacy).expanduser().is_file():
        return str(Path(legacy).expanduser().resolve())
    return None


def _apply_bundle_to_env(env: Dict[str, str], bundle: str) -> None:
    env["SSL_CERT_FILE"] = bundle
    env["REQUESTS_CA_BUNDLE"] = bundle
    env["NODE_EXTRA_CA_CERTS"] = bundle
    env["NPM_CONFIG_CAFILE"] = bundle
    env["UV_NATIVE_TLS"] = "true"


def tls_subprocess_env(
    base: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Return env dict for MCP / npm / uv subprocesses with corporate CA trust."""
    env = dict(base if base is not None else os.environ)
    env["UV_NATIVE_TLS"] = "true"
    bundle = _resolve_bundle_path()
    if bundle:
        _apply_bundle_to_env(env, bundle)
    return env


def apply_tls_bundle_env() -> Optional[str]:
    """Materialize bundle and set process-wide TLS env vars. Returns bundle path."""
    bundle = _resolve_bundle_path()
    if not bundle:
        os.environ["UV_NATIVE_TLS"] = "true"
        logger.debug(
            "ssl_ca: no corporate CA configured "
            "(set AIBUDDY_CA_CERT_DIR=Certificate or AIBUDDY_CA_BUNDLE)"
        )
        return None
    _apply_bundle_to_env(os.environ, bundle)
    logger.info("ssl_ca: TLS bundle active at %s", bundle)
    return bundle
