# -*- coding: utf-8 -*-
"""
Lark block utilities — text→blocks conversion shared by
:mod:`runtime.collab_deliverable_artifacts` and
:mod:`runtime.protocols.notification_dispatcher` (the legacy adapter
populates documents via plain-text blocks).

Extracted from ``runtime.collab_deliverable_artifacts`` to break the
PR-E6 circular import:
``collab_deliverable_artifacts → notification_dispatcher → collab_deliverable_artifacts``.

This module has **NO** imports from ``runtime.protocols`` or
``collab_deliverable_artifacts`` so it is safe to import from both
sides.  Pure stdlib only.
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["plain_text_to_lark_blocks"]


def plain_text_to_lark_blocks(
    text: str, *, max_chunk: int = 4500
) -> List[Dict[str, Any]]:
    """Split plain text into Feishu docx text blocks (block_type 2).

    Pure-function, no I/O.  ``max_chunk`` defaults to 4500 because the
    Lark docx API limits each text-run ``content`` field to ~5 KiB —
    splitting at 4500 leaves headroom for the JSON envelope.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    blocks: List[Dict[str, Any]] = []
    buf: List[str] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        chunk = "\n".join(buf).strip()
        if chunk:
            for i in range(0, len(chunk), max_chunk):
                piece = chunk[i : i + max_chunk]
                blocks.append(
                    {
                        "block_type": 2,
                        "text": {
                            "elements": [{"text_run": {"content": piece}}],
                            "style": {},
                        },
                    }
                )
        buf = []

    for ln in lines:
        if sum(len(x) + 1 for x in buf) + len(ln) + 10 > max_chunk:
            flush()
        buf.append(ln)
    flush()
    if not blocks:
        blocks.append(
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": ""}}], "style": {}},
            }
        )
    return blocks
