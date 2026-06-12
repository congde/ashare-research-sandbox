# -*- coding: utf-8 -*-
"""
Local + remote sinks for collaborative rich-text deliverables.

- **Local**: UTF-8 files under ``collab_deliverable.local_dir``, or when that is empty,
  ``{AI_BUDDY_SHARE_ROOT}/collab-deliverables/`` (shared volume layout in ``conf/default.yaml``),
  else ``data/collab_deliverables``. Env ``COLLAB_DELIVERABLE__LOCAL_DIR`` overrides.
- **S3**: optional ``boto3``; bucket/region/proxy/endpoints from ``collab_deliverable.s3`` in YAML, with legacy ``COLLAB_S3_*`` / ``AWS_*`` env as fallback.
- **Lark**: Feishu docx via ``LarkClient.create_doc`` + ``create_doc_block`` (plain text / HTML stripped).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MANIFEST = "manifest.json"


def _collab_root_cfg() -> Optional[Any]:
    """``config.collab_deliverable`` from ``default.yaml`` (may be missing in tests)."""
    try:
        from web.config import config as _cfg

        if _cfg is None:
            return None
        return getattr(_cfg, "collab_deliverable", None)
    except Exception:
        return None


def _collab_s3_cfg() -> Optional[Any]:
    root = _collab_root_cfg()
    if root is None:
        return None
    return getattr(root, "s3", None)


def _str_cfg(s3: Optional[Any], name: str) -> str:
    if s3 is None:
        return ""
    v = getattr(s3, name, None)
    return (v or "").strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")


def _bool_cfg(node: Optional[Any], name: str, default: bool = False) -> bool:
    if node is None or not hasattr(node, name):
        return default
    v = getattr(node, name)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def s3_bucket_configured() -> bool:
    s3 = _collab_s3_cfg()
    bucket = _str_cfg(s3, "bucket") if s3 is not None else ""
    if not bucket:
        bucket = (os.environ.get("COLLAB_S3_BUCKET") or "").strip()
    return bool(bucket)


def s3_workflow_auto_upload_enabled() -> bool:
    ex = (os.environ.get("COLLAB_S3_AUTO_WORKFLOW") or "").strip().lower()
    if ex in ("0", "false", "no", "off"):
        return False
    if not s3_bucket_configured():
        return False
    s3 = _collab_s3_cfg()
    return _bool_cfg(s3, "auto_upload_workflow_deliverables", True)


def s3_collab_auto_upload_enabled() -> bool:
    ex = (os.environ.get("COLLAB_S3_AUTO_COLLAB") or "").strip().lower()
    if ex in ("0", "false", "no", "off"):
        return False
    if not s3_bucket_configured():
        return False
    s3 = _collab_s3_cfg()
    return _bool_cfg(s3, "auto_upload_collab_artifacts", True)

_MAX_BODY_BYTES = 15 * 1024 * 1024
_SAFE_WS_RE = re.compile(r"^[\w\-:.]{1,128}$")


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _share_root_for_collab() -> str:
    """First non-empty: ``AI_BUDDY_SHARE_ROOT``, ``COLLAB_DELIVERABLE__SHARE_ROOT``, yaml roots."""
    for env_key in ("AI_BUDDY_SHARE_ROOT", "COLLAB_DELIVERABLE__SHARE_ROOT"):
        out = (os.environ.get(env_key) or "").strip()
        if out:
            return out
    try:
        from web.config import config as _cfg

        if _cfg is not None:
            out = (getattr(_cfg, "ai_buddy_share_root", None) or "").strip()
            if out:
                return out
    except Exception:
        pass
    cd = _collab_root_cfg()
    if cd is not None:
        return _str_cfg(cd, "share_root")
    return ""


def _local_root() -> Path:
    cd = _collab_root_cfg()
    raw = _str_cfg(cd, "local_dir") if cd is not None else ""
    if not raw:
        raw = (os.environ.get("COLLAB_DELIVERABLE_LOCAL_DIR") or "").strip()
    if not raw:
        raw = (os.environ.get("COLLAB_DELIVERABLE__LOCAL_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    share = _share_root_for_collab()
    if share:
        return (Path(share).expanduser().resolve() / "collab-deliverables")
    return Path("data/collab_deliverables").expanduser().resolve()


def _assert_safe_segment(seg: str, label: str) -> str:
    s = (seg or "").strip()
    if not s or not _SAFE_WS_RE.match(s):
        raise ValueError(f"invalid {label}")
    return s


def issue_dir(workspace_id: str, issue_id: str) -> Path:
    ws = _assert_safe_segment(workspace_id, "workspace_id")
    iss = _assert_safe_segment(issue_id, "issue_id")
    d = _local_root() / ws / iss
    return d


def _format_to_ext(fmt: str) -> str:
    f = (fmt or "html").strip().lower()
    if f in ("htm", "html"):
        return "html"
    if f in ("md", "markdown"):
        return "md"
    if f == "json":
        return "json"
    if f in ("txt", "text"):
        return "txt"
    raise ValueError("format must be one of: html, md, json, txt")


def _html_to_plain(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# PR-E6: ``plain_text_to_lark_blocks`` moved to
# :mod:`runtime.lark_block_utils` to break the circular import with
# :mod:`runtime.protocols.notification_dispatcher`.  Re-exported here
# for backwards compatibility with existing call sites.
from vendor_runtime_sdk.runtime.lark_block_utils import plain_text_to_lark_blocks  # noqa: E402, F401


def _read_manifest(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"artifacts": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"artifacts": []}


def _write_manifest(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _s3_path_segment(raw: str, fallback: str) -> str:
    s = (raw or "").strip()
    if not s:
        return fallback
    if _SAFE_WS_RE.match(s):
        return s[:128]
    cleaned = re.sub(r"[^\w\-:.]", "_", s)[:128]
    return cleaned or fallback


async def _merge_s3_into_manifest(
    workspace_id: str, issue_id: str, artifact_id: str, meta: Dict[str, Any],
) -> None:
    d = issue_dir(workspace_id, issue_id)
    manifest_path = d / _MANIFEST
    manifest = await asyncio.to_thread(_read_manifest, manifest_path)
    arts = list(manifest.get("artifacts") or [])
    for a in arts:
        if a.get("id") == artifact_id:
            a["s3_bucket"] = meta.get("bucket")
            a["s3_key"] = meta.get("key")
            if meta.get("region"):
                a["s3_region"] = meta.get("region")
            break
    manifest["artifacts"] = arts
    await asyncio.to_thread(_write_manifest, manifest_path, manifest)


def _load_bytes_sync(path: Path) -> bytes:
    return path.read_bytes()


def _save_bytes_sync(path: Path, data: bytes, manifest_path: Path, manifest: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _write_manifest(manifest_path, manifest)


@dataclass
class LocalSaveResult:
    artifact_id: str
    workspace_id: str
    issue_id: str
    format: str
    extension: str
    size_bytes: int
    relative_path: str
    title: str
    s3: Optional[Dict[str, Any]] = None


async def save_local_artifact(
    *,
    workspace_id: str,
    issue_id: str,
    title: str,
    content: str,
    format: str = "html",
) -> LocalSaveResult:
    if not title or not title.strip():
        raise ValueError("title is required")
    ext = _format_to_ext(format)
    data = content.encode("utf-8")
    if len(data) > _MAX_BODY_BYTES:
        raise ValueError(f"content exceeds {_MAX_BODY_BYTES} bytes")

    aid = str(uuid.uuid4())
    d = issue_dir(workspace_id, issue_id)
    file_path = d / f"{aid}.{ext}"
    manifest_path = d / _MANIFEST
    manifest = _read_manifest(manifest_path)
    arts = list(manifest.get("artifacts") or [])
    entry = {
        "id": aid,
        "title": title.strip()[:512],
        "format": ext,
        "size_bytes": len(data),
        "created_at": _utc_iso(),
        "filename": f"{aid}.{ext}",
    }
    arts.append(entry)
    manifest["artifacts"] = arts

    await asyncio.to_thread(_save_bytes_sync, file_path, data, manifest_path, manifest)
    root = _local_root()
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    s3_meta: Optional[Dict[str, Any]] = None
    if s3_collab_auto_upload_enabled():
        try:
            s3_meta = await export_local_artifact_to_s3(
                workspace_id=workspace_id,
                issue_id=issue_id,
                artifact_id=aid,
            )
            await _merge_s3_into_manifest(workspace_id, issue_id, aid, s3_meta)
        except Exception as e:
            logger.warning("collab auto S3 upload failed (artifact %s): %s", aid, e)

    return LocalSaveResult(
        artifact_id=aid,
        workspace_id=workspace_id,
        issue_id=issue_id,
        format=ext,
        extension=ext,
        size_bytes=len(data),
        relative_path=rel,
        title=entry["title"],
        s3=s3_meta,
    )


async def list_local_artifacts(workspace_id: str, issue_id: str) -> List[Dict[str, Any]]:
    d = issue_dir(workspace_id, issue_id)
    manifest_path = d / _MANIFEST
    manifest = await asyncio.to_thread(_read_manifest, manifest_path)
    items = list(manifest.get("artifacts") or [])
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


async def resolve_local_file(
    workspace_id: str, issue_id: str, artifact_id: str,
) -> Tuple[Path, str]:
    """Return (absolute_path, extension) for artifact."""
    _assert_safe_segment(artifact_id, "artifact_id")
    d = issue_dir(workspace_id, issue_id)
    manifest_path = d / _MANIFEST
    manifest = await asyncio.to_thread(_read_manifest, manifest_path)
    ext = None
    for a in manifest.get("artifacts") or []:
        if a.get("id") == artifact_id:
            ext = (a.get("format") or "").strip()
            break
    if ext:
        p = d / f"{artifact_id}.{ext}"
        if p.is_file():
            return p, ext
    for cand in d.glob(f"{artifact_id}.*"):
        if cand.is_file() and cand.name != _MANIFEST:
            return cand, cand.suffix.lstrip(".") or "bin"
    raise FileNotFoundError("artifact not found")


async def read_local_text(workspace_id: str, issue_id: str, artifact_id: str) -> Tuple[str, str]:
    path, ext = await resolve_local_file(workspace_id, issue_id, artifact_id)
    raw = await asyncio.to_thread(_load_bytes_sync, path)
    return raw.decode("utf-8", errors="replace"), ext


def _s3_proxy_config() -> Optional[Dict[str, str]]:
    """
    Corporate egress proxy for boto3/botocore.

    Resolution order:
      ``collab_deliverable.s3.proxy`` (yaml / env-injected)  →
      COLLAB_S3_PROXY / COLLAB_DELIVERABLE__S3__PROXY  →
      HTTPS_PROXY / https_proxy  →  HTTP_PROXY / http_proxy
    Same URL is used for both ``http`` and ``https`` keys (typical forward HTTP proxy).
    """
    s3 = _collab_s3_cfg()
    raw = _str_cfg(s3, "proxy") if s3 is not None else ""
    if not raw:
        raw = (os.environ.get("COLLAB_S3_PROXY") or "").strip()
    if not raw:
        raw = (os.environ.get("COLLAB_DELIVERABLE__S3__PROXY") or "").strip()
    if not raw:
        raw = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        ).strip()
    if not raw:
        return None
    return {"http": raw, "https": raw}


def _s3_tls_verify() -> bool:
    """
    TLS verify for boto3 S3 client. Corporate HTTPS proxies may MITM with an internal CA;
    prefer ``SSL_CERT_FILE`` / ``AWS_CA_BUNDLE``. Emergency local only: ``COLLAB_S3_VERIFY_SSL=0``.
    """
    raw = (os.environ.get("COLLAB_S3_VERIFY_SSL") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


async def push_bytes_to_s3(
    *,
    data: bytes,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> Dict[str, Any]:
    """
    Upload bytes to S3. Requires ``boto3`` and usual AWS env/credentials.

    Config (``conf/default.yaml`` → ``collab_deliverable.s3``), overridden by non-empty env:
      - ``bucket``, ``region``, ``endpoint_url``, ``proxy``
    Legacy env fallbacks: ``COLLAB_S3_BUCKET``, ``AWS_REGION`` / ``AWS_DEFAULT_REGION``,
    ``COLLAB_S3_ENDPOINT_URL``, ``COLLAB_S3_PROXY``, ``HTTPS_PROXY``.
    TLS: ``COLLAB_S3_VERIFY_SSL`` (default true); set to ``0`` only for dev behind SSL-inspecting proxy.
    """
    s3 = _collab_s3_cfg()
    bucket = _str_cfg(s3, "bucket") if s3 is not None else ""
    if not bucket:
        bucket = (os.environ.get("COLLAB_S3_BUCKET") or "").strip()
    if not bucket:
        raise RuntimeError("S3 bucket not set (collab_deliverable.s3.bucket or COLLAB_S3_BUCKET)")
    region = _str_cfg(s3, "region") if s3 is not None else ""
    if not region:
        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        ).strip()
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except ImportError as e:
        raise RuntimeError("boto3 is required for S3 export; pip install boto3") from e

    key = object_key.lstrip("/")
    if not key:
        raise ValueError("object_key is empty")

    endpoint_yaml = _str_cfg(s3, "endpoint_url") if s3 is not None else ""
    endpoint_url = (endpoint_yaml or os.environ.get("COLLAB_S3_ENDPOINT_URL") or "").strip() or None
    proxies = _s3_proxy_config()
    botocore_cfg = Config(proxies=proxies) if proxies else None

    def _upload() -> None:
        client_kw: Dict[str, Any] = {"region_name": region}
        if botocore_cfg is not None:
            client_kw["config"] = botocore_cfg
        if endpoint_url:
            client_kw["endpoint_url"] = endpoint_url
        client_kw["verify"] = _s3_tls_verify()
        client = boto3.client("s3", **client_kw)
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    await asyncio.to_thread(_upload)
    out: Dict[str, Any] = {
        "bucket": bucket,
        "key": key,
        "region": region,
        "bytes": len(data),
    }
    if endpoint_url:
        out["endpoint_url"] = endpoint_url
    if proxies:
        out["proxy_configured"] = True
    if not _s3_tls_verify():
        out["tls_verify"] = False
    return out


def build_default_s3_key(workspace_id: str, issue_id: str, artifact_id: str, ext: str) -> str:
    s3 = _collab_s3_cfg()
    prefix = _str_cfg(s3, "prefix") if s3 is not None else ""
    if not prefix:
        prefix = (os.environ.get("COLLAB_S3_PREFIX") or "").strip()
    if not prefix:
        prefix = "collab-deliverables/"
    prefix = prefix.strip().strip("/")
    pfx = f"{prefix}/" if prefix else ""
    return f"{pfx}{workspace_id}/{issue_id}/{artifact_id}.{ext}"


def build_workflow_deliverable_s3_key(
    workspace_id: str,
    workflow_id: str,
    run_id: str,
    deliverable_id: str,
    ext: str,
) -> str:
    """S3 object key for workflow ``deliverables`` body (under same prefix as collab artifacts)."""
    ws = _assert_safe_segment(workspace_id, "workspace_id")
    did = _assert_safe_segment(deliverable_id, "deliverable_id")
    wf = _s3_path_segment(workflow_id, "unknown-workflow")
    rid = _s3_path_segment(run_id, "unknown-run")
    e = (ext or "txt").strip().lstrip(".")[:16] or "txt"
    s3 = _collab_s3_cfg()
    prefix = _str_cfg(s3, "prefix") if s3 is not None else ""
    if not prefix:
        prefix = (os.environ.get("COLLAB_S3_PREFIX") or "").strip()
    if not prefix:
        prefix = "collab-deliverables/"
    prefix = prefix.strip().strip("/")
    pfx = f"{prefix}/" if prefix else ""
    return f"{pfx}workflow-deliverables/{ws}/{wf}/{rid}/{did}.{e}"


async def create_lark_doc_from_text(
    *,
    title: str,
    body_text: str,
    folder_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a Feishu docx with plain-text blocks. Caller supplies Lark app credentials.
    """
    # PR-E6 (SDK extraction §5 PR-E6): lark.integration_service is now
    # accessed via the NotificationDispatcher Protocol
    # (create_document method).  The legacy lark.* call is still used
    # via the _LegacyLarkNotificationDispatcher fallback so runtime
    # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback
    # when lark/ leaves the engine import surface.
    from vendor_runtime_sdk.runtime.protocols.notification_dispatcher import (
        get_notification_dispatcher,
    )

    dispatcher = get_notification_dispatcher()
    # Capability check before issuing a no-op create_document call.
    # Without this gate, the NoOp fallback returns a synthetic
    # noop://document/... DocumentRef so the caller would silently
    # persist a fake URL.  Review feedback: this was a behavioural
    # regression vs the pre-PR-E6 code path which raised RuntimeError
    # when lark.* was unreachable.
    if not dispatcher.has_notification_channel():
        raise RuntimeError(
            "Lark not configured — configure via PUT /api/admin/lark/config"
        )
    doc_ref = await dispatcher.create_document(
        title=title,
        body_text=body_text,
        folder_token=folder_token,
        integration_id="default",
    )
    if doc_ref is None:
        # Channel was claimed reachable but create_document failed
        # mid-flight (e.g. Lark API rejected the request).  Distinct
        # error message so operators can tell "no channel" from
        # "channel up but create failed".
        raise RuntimeError(
            "Lark create_document failed — channel reachable but no "
            "document_id returned (check Lark API logs)"
        )
    return {
        "document_id": doc_ref.document_id,
        "doc_url": doc_ref.url,
        # Return the caller-supplied title verbatim.  The adapter
        # sanitises the title internally before sending to the Lark
        # API, but engine callers persist the original string (review
        # feedback: silent title truncation/redaction broke export
        # pipelines that re-display the title to the user).
        "title": title,
    }


async def export_local_artifact_to_s3(
    *,
    workspace_id: str,
    issue_id: str,
    artifact_id: str,
    object_key: Optional[str] = None,
) -> Dict[str, Any]:
    path, ext = await resolve_local_file(workspace_id, issue_id, artifact_id)
    data = await asyncio.to_thread(_load_bytes_sync, path)
    ct = {
        "html": "text/html; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }.get(ext, "application/octet-stream")
    key = object_key or build_default_s3_key(workspace_id, issue_id, artifact_id, ext)
    meta = await push_bytes_to_s3(data=data, object_key=key, content_type=ct)
    meta["artifact_id"] = artifact_id
    return meta


async def export_local_artifact_to_lark(
    *,
    workspace_id: str,
    issue_id: str,
    artifact_id: str,
    title: Optional[str] = None,
    folder_token: Optional[str] = None,
    strip_html: bool = True,
) -> Dict[str, Any]:
    text, ext = await read_local_text(workspace_id, issue_id, artifact_id)
    if strip_html and ext == "html":
        text = _html_to_plain(text)
    doc_title = (title or f"Deliverable {artifact_id[:8]}").strip()
    out = await create_lark_doc_from_text(title=doc_title, body_text=text, folder_token=folder_token)
    out["artifact_id"] = artifact_id
    out["source_format"] = ext
    return out
