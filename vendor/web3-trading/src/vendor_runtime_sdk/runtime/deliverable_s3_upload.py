# -*- coding: utf-8 -*-
"""Auto-upload workflow deliverable bodies to S3 using ``collab_deliverable.s3`` settings."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _deliverable_type_to_ext(d_type: str) -> str:
    t = (d_type or "document").strip().lower()
    if t == "code":
        return "txt"
    if t in ("schema", "data"):
        return "json"
    if t == "document":
        return "md"
    return "txt"


def _content_type_for_ext(ext: str) -> str:
    return {
        "html": "text/html; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }.get(ext, "text/plain; charset=utf-8")


async def maybe_upload_workflow_deliverable_after_mysql(
    *,
    workspace_id: str,
    workflow_id: str,
    run_id: str,
    deliverable_id: str,
    deliverable_type: str,
    body: str,
) -> Optional[str]:
    """
    If auto-upload is enabled and bucket is configured, upload ``body`` to S3.

    Returns ``s3://bucket/key`` on success; ``None`` if skipped or on recoverable error
    (caller keeps full ``content`` in MySQL).
    """
    from vendor_runtime_sdk.runtime.collab_deliverable_artifacts import (
        build_workflow_deliverable_s3_key,
        push_bytes_to_s3,
        s3_workflow_auto_upload_enabled,
    )

    if not s3_workflow_auto_upload_enabled():
        return None
    if not (body or "").strip():
        return None
    ext = _deliverable_type_to_ext(deliverable_type)
    try:
        key = build_workflow_deliverable_s3_key(
            workspace_id, workflow_id, run_id, deliverable_id, ext,
        )
        meta = await push_bytes_to_s3(
            data=body.encode("utf-8"),
            object_key=key,
            content_type=_content_type_for_ext(ext),
        )
        b = meta.get("bucket", "")
        k = meta.get("key", "")
        if b and k:
            return f"s3://{b}/{k}"
    except Exception as e:
        logger.warning(
            "workflow deliverable S3 upload failed (id=%s): %s", deliverable_id, e,
        )
    return None
