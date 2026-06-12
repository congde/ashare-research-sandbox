# -*- coding: utf-8 -*-
"""
Review — auto review, deliverable archiving

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional

class ReviewMixin:
    """Review — auto review, deliverable archiving"""

    async def _auto_review(
        self, result: Dict[str, Any], node_data: Dict[str, Any],
    ) -> tuple:
        """LLM-based auto-review against acceptance criteria.

        Returns (score: float 0-10, passed: bool).
        """
        from vendor_runtime_sdk.llm.base import create_llm

        criteria = node_data.get("acceptance_criteria", "")
        threshold = float(node_data.get("acceptance_threshold", 7.0))
        content = result.get("content", "") or result.get("text", "") or ""

        if not criteria or not content:
            return (None, None)

        review_prompt = (
            "You are a quality reviewer. Score the following content against the criteria.\n\n"
            f"## Acceptance Criteria\n{criteria}\n\n"
            f"## Content to Review\n{content[:4000]}\n\n"
            "Score from 0 to 10. Reply with ONLY a JSON: {\"score\": <number>, \"passed\": <bool>, \"reason\": \"<brief>\"}"
        )

        llm, model = create_llm()
        resp = await llm.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": review_prompt}],
            temperature=0.1,
        )
        text = resp.choices[0].message.content.strip() if resp.choices else ""
        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', text)
            if json_match:
                review = json.loads(json_match.group())
                score = float(review.get("score", 0))
                passed = review.get("passed", score >= threshold)
                return (score, bool(passed))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Auto-review parse failed: %s", e)

        return (None, None)

    # ── Deliverable archival ──

    async def _archive_deliverable(self, deliverable) -> None:
        """Archive a deliverable to the deliverables table."""
        try:
            from dao.mysql.deliverable import get_deliverable_dao
            from vendor_runtime_sdk.runtime.deliverable_s3_upload import (
                maybe_upload_workflow_deliverable_after_mysql,
            )

            dao = get_deliverable_dao()
            d = deliverable.to_dict()
            d["workspace_id"] = self._workspace_id or self._ctx.workspace_id
            d["workflow_id"] = self._workflow.get("id", "") or self._ctx.workflow_id
            d["run_id"] = self._run_id or d.get("run_id") or d.get("produced_by_task", "")
            content = str(d.get("content") or "")

            await dao.create(d)

            uri = await maybe_upload_workflow_deliverable_after_mysql(
                workspace_id=d["workspace_id"],
                workflow_id=d["workflow_id"],
                run_id=d["run_id"],
                deliverable_id=d["id"],
                deliverable_type=str(d.get("type") or "document"),
                body=content,
            )
            if uri:
                await dao.update_content(d["id"], "", uri)
        except ImportError:
            # DAO not yet created, store in workflow_context only
            logger.debug("Deliverable DAO not available, skipping archival")
        except Exception as e:
            logger.warning("Deliverable archive error: %s", e)

    # ── Doc / Code generator node handlers ──


logger = logging.getLogger(__name__)
