# -*- coding: utf-8 -*-
"""
Generator handlers — doc generator, code generator, file writing

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
from typing import Any, Dict, List, Optional

class GeneratorsMixin:
    """Generator handlers — doc generator, code generator, file writing"""

    async def _exec_doc_generator(self, node: Dict) -> Dict[str, Any]:
        """Document generator node — uses DocGenerator to produce structured documents."""
        data = node.get("data") or {}
        doc_type = data.get("doc_type") or data.get("document_type") or "generic"
        task = data.get("task") or data.get("prompt") or ""
        context = data.get("context") or ""
        lang = data.get("lang") or data.get("language") or "zh"
        title = data.get("title") or data.get("deliverable_name") or doc_type

        # ── Inject upstream context ──
        node_id = node.get("id", "")
        upstream_ctx = self._ctx.format_upstream_context(current_node_id=node_id)
        if upstream_ctx:
            context = f"{upstream_ctx}\n\n---\n\n{context}" if context else upstream_ctx

        try:
            from deliverables.doc.generator import DocGenerator
            from vendor_runtime_sdk.llm.base import create_llm
            llm_client, model_name = create_llm()
            gen = DocGenerator(llm_client=llm_client, model_name=model_name)
            result = await gen.generate(
                task=task, doc_type=doc_type, context=context, lang=lang,
            )
            # Check for generation errors
            if hasattr(result, "error") and result.error:
                return {"ok": False, "error": result.error, "doc_type": doc_type, "title": title}
            return {
                "ok": True,
                "content": result.as_markdown() if hasattr(result, "as_markdown") else str(result),
                "doc_type": doc_type,
                "title": title,
                "deliverable_name": data.get("deliverable_name"),
            }
        except ImportError:
            # Fallback: use LLM call directly
            return await self._exec_agent_call(node)
        except Exception as e:
            logger.exception("DocGenerator failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def _exec_code_generator(self, node: Dict) -> Dict[str, Any]:
        """Code generator node — uses CodeGenerator to produce code deliverables.

        Supports ``write_to_disk`` flag in node data. When enabled (default True),
        generated files are written to the project workspace on the local filesystem.
        """
        data = node.get("data") or {}
        task = data.get("task") or data.get("prompt") or ""
        language = data.get("language") or "python"
        prd_content = data.get("prd_content") or ""
        write_to_disk = data.get("write_to_disk", True)
        output_dir = data.get("output_dir") or ""

        # ── Inject upstream context ──
        node_id = node.get("id", "")
        upstream_ctx = self._ctx.format_upstream_context(current_node_id=node_id)
        if upstream_ctx:
            task = f"## Context\n{upstream_ctx}\n\n---\n\n{task}"

        # Resolve PRD from upstream deliverables if not directly provided
        if not prd_content:
            prd_ref = data.get("prd_ref")  # e.g. "${deliverable.prd.content}"
            if prd_ref:
                resolved = self._ctx.resolve(prd_ref)
                if resolved and resolved != prd_ref:
                    prd_content = str(resolved)

        try:
            from deliverables.code.generator import CodeGenerator
            from vendor_runtime_sdk.llm.base import create_llm
            llm_client, model_name = create_llm()
            gen = CodeGenerator(llm_client=llm_client, model_name=model_name)
            result = await gen.generate(
                task=task, repo_analysis={}, language=language, prd_content=prd_content,
            )
            files = []
            written_files = []
            if hasattr(result, "files"):
                files = [{"path": f.path, "content": f.content, "type": f.file_type} for f in result.files]

                # ── Write generated files to local disk ──
                if write_to_disk and files:
                    written_files = await self._write_files_to_disk(
                        files=files,
                        output_dir=output_dir,
                        node_id=node_id,
                    )

            return {
                "ok": True,
                "content": json.dumps(files, ensure_ascii=False, indent=2) if files else str(result),
                "files": files,
                "written_files": written_files,
                "language": language,
                "deliverable_name": data.get("deliverable_name"),
            }
        except ImportError:
            return await self._exec_agent_call(node)
        except Exception as e:
            logger.exception("CodeGenerator failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Write generated files to local disk ──

    async def _write_files_to_disk(
        self,
        files: List[Dict[str, Any]],
        output_dir: str = "",
        node_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Write generated code files to the local project filesystem.

        Args:
            files: List of dicts with ``path``, ``content``, ``type`` keys.
            output_dir: Optional override directory (absolute or relative to project root).
            node_id: Used for logging and default sub-directory.

        Returns:
            List of dicts with ``path``, ``absolute_path``, ``written`` (bool), ``error`` (str|None).
        """
        import os

        # Determine project root: prefer WORKFLOW_CODE_OUTPUT_DIR env, then AGENT_WORKSPACE_ROOT,
        # then fall back to the repo root (parent of src/).
        project_root = (
            os.environ.get("WORKFLOW_CODE_OUTPUT_DIR")
            or os.environ.get("AGENT_WORKSPACE_ROOT")
            or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        )

        if output_dir:
            # If output_dir is absolute, use as-is; otherwise relative to project_root
            base_dir = output_dir if os.path.isabs(output_dir) else os.path.join(project_root, output_dir)
        else:
            base_dir = project_root

        written = []
        for f in files:
            rel_path = f.get("path", "")
            content = f.get("content", "")
            action = f.get("action") or f.get("type", "create")

            if not rel_path:
                continue

            # Safety: reject path traversal
            abs_path = os.path.abspath(os.path.join(base_dir, rel_path))
            if not abs_path.startswith(os.path.abspath(base_dir)):
                logger.warning("Skipping path traversal attempt: %s", rel_path)
                written.append({
                    "path": rel_path,
                    "absolute_path": abs_path,
                    "written": False,
                    "error": "path traversal rejected",
                })
                continue

            try:
                if action == "delete":
                    await asyncio.to_thread(self._delete_file_sync, abs_path)
                    written.append({
                        "path": rel_path,
                        "absolute_path": abs_path,
                        "written": True,
                        "action": "delete",
                        "error": None,
                    })
                    continue

                # Write file in thread pool to avoid blocking the event loop
                await asyncio.to_thread(self._write_file_sync, abs_path, content)

                logger.info("Wrote file: %s (%d bytes)", abs_path, len(content))
                written.append({
                    "path": rel_path,
                    "absolute_path": abs_path,
                    "written": True,
                    "action": action,
                    "error": None,
                })
            except Exception as e:
                logger.error("Failed to write file %s: %s", abs_path, e)
                written.append({
                    "path": rel_path,
                    "absolute_path": abs_path,
                    "written": False,
                    "action": action,
                    "error": str(e),
                })

        return written

    @staticmethod
    def _write_file_sync(abs_path: str, content: str) -> None:
        """Synchronous file write — called via asyncio.to_thread."""
        import os
        parent = os.path.dirname(abs_path)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(content)

    @staticmethod
    def _delete_file_sync(abs_path: str) -> None:
        """Synchronous file delete — called via asyncio.to_thread."""
        import os
        if os.path.exists(abs_path):
            os.remove(abs_path)
            logger.info("Deleted file: %s", abs_path)


logger = logging.getLogger(__name__)
