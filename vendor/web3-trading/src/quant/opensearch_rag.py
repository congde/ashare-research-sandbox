# -*- coding: utf-8 -*-
"""OpenSearch RAG 检索封装。

不硬编码连接文档中的敏感信息，统一从环境变量读取。
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _config_value(name: str, default=""):
    env_value = os.getenv(name)
    if env_value not in (None, ""):
        return env_value
    try:
        from web import config as web_config

        cfg = web_config.config
        if cfg is not None:
            return getattr(cfg, name.lower(), default)
    except Exception:
        pass
    return default


def _bool_config(name: str, default: bool) -> bool:
    raw = _config_value(name, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "yes", "y")


def _float_config(name: str, default: float) -> float:
    try:
        return float(_config_value(name, default))
    except (TypeError, ValueError):
        return default


class OpenSearchRAGClient:
    """OpenSearch + Qwen Embedding 混合检索客户端。"""

    def __init__(self):
        host = _config_value("OPENSEARCH_HOST", "")
        port = str(_config_value("OPENSEARCH_PORT", "443"))
        use_ssl = _bool_config("OPENSEARCH_USE_SSL", True)
        scheme = "https" if use_ssl else "http"
        self.base_url = _config_value("OPENSEARCH_URL", "") or (f"{scheme}://{host}:{port}" if host else "")
        self.index = _config_value("OPENSEARCH_INDEX", "market_events")
        self.news_index = _config_value("OPENSEARCH_NEWS_INDEX", "non_market_events")
        self.user = _config_value("OPENSEARCH_USER", "")
        self.password = _config_value("OPENSEARCH_PASSWORD", "")
        self.verify_certs = _bool_config("OPENSEARCH_VERIFY_CERTS", False)
        self.vector_field = _config_value("OPENSEARCH_VECTOR_FIELD", "event_embedding")
        self.event_time_field = _config_value("OPENSEARCH_EVENT_TIME_FIELD", "timestamps.storage_time")
        self.max_event_age_hours = _float_config("OPENSEARCH_MAX_EVENT_AGE_HOURS", 72)
        text_fields = _config_value(
            "OPENSEARCH_TEXT_FIELDS",
            "title,headline,summary,statement,content,event_statement_template,event_question_template",
        )
        self.text_fields = [x.strip() for x in str(text_fields).split(",") if x.strip()]
        self.embedding_model = _config_value("OPENSEARCH_EMBEDDING_MODEL", "") or _config_value("EMBEDDING_MODEL", "Qwen3-Embedding-0.6B")
        self.embedding_api_key = (
            _config_value("OPENSEARCH_EMBEDDING_API_KEY", "")
            or _config_value("EMBEDDING_OPENAI_API_KEY", "")
            or _config_value("OPENAI_API_KEY", "")
        )
        self.embedding_api_base = (
            _config_value("OPENSEARCH_EMBEDDING_BASE_URL", "")
            or _config_value("EMBEDDING_OPENAI_API_BASE", "")
            or _config_value("OPENAI_API_BASE", "")
        )
        self.embedding_dims = int(_config_value("EMBEDDING_DIMS", "1024"))
        self._embedding_client: Optional[AsyncOpenAI] = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.index)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.user and self.password:
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _get_embedding_client(self) -> AsyncOpenAI:
        if self._embedding_client is None:
            self._embedding_client = AsyncOpenAI(
                api_key=self.embedding_api_key,
                base_url=self.embedding_api_base.rstrip("/") if self.embedding_api_base else None,
            )
        return self._embedding_client

    async def embed(self, text: str) -> Optional[list[float]]:
        if not self.embedding_api_key:
            return None
        try:
            response = await self._get_embedding_client().embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            vector = response.data[0].embedding
            return vector[: self.embedding_dims] if vector else None
        except Exception as exc:
            logger.warning("embedding failed: %s", exc)
            return None

    async def search(
        self,
        query: str,
        size: int = 5,
        use_vector: bool = True,
        index: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled or not query:
            return []

        target_index = index or self.index
        if not target_index:
            return []

        vector = await self.embed(query) if use_vector else None
        if vector:
            body = {
                "size": size,
                "_source": {"excludes": [self.vector_field, "embedding", "vector"]},
                "query": {
                    "knn": {
                        self.vector_field: {
                            "vector": vector,
                            "k": size,
                        }
                    }
                },
            }
        else:
            body = {
                "size": size,
                "_source": {"excludes": [self.vector_field, "embedding", "vector"]},
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": self.text_fields,
                        "type": "best_fields",
                    }
                },
            }

        url = f"{self.base_url.rstrip('/')}/{target_index}/_search"
        try:
            async with httpx.AsyncClient(verify=self.verify_certs, timeout=30) as client:
                resp = await client.post(url, json=body, headers=self._headers())
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            logger.warning("OpenSearch search failed: %s", exc)
            return []

        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        return self._format_hits(hits)

    def _freshness_filter(self) -> Optional[Dict[str, Any]]:
        if self.max_event_age_hours <= 0:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_event_age_hours)
        return {"range": {self.event_time_field: {"gte": cutoff.strftime("%Y-%m-%d %H:%M:%S")}}}

    def _format_hits(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "score": item.get("_score"),
                "id": item.get("_id"),
                "index": item.get("_index"),
                "source": item.get("_source") or {},
            }
            for item in hits
        ]

    async def search_events(
        self,
        symbols: List[str],
        size: int = 5,
        index: Optional[str] = None,
        source_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        target_index = index or self.index
        coins = [s.upper().split("-")[0].split("/")[0] for s in symbols if s]
        should_filters: List[Dict[str, Any]] = []
        if coins:
            should_filters.append({"terms": {"coins": coins}})
            should_filters.append({"terms": {"symbol.keyword": [f"{coin}-USDT" for coin in coins]}})

        filters: List[Dict[str, Any]] = []
        freshness = self._freshness_filter()
        if freshness:
            filters.append(freshness)
        if source_types:
            filters.append({"terms": {"source_type": source_types}})

        body: Dict[str, Any] = {
            "size": size,
            "_source": {"excludes": [self.vector_field, "embedding", "vector"]},
            "query": {"bool": {"filter": filters}},
            "sort": [{self.event_time_field: {"order": "desc", "missing": "_last"}}],
        }
        if should_filters:
            body["query"]["bool"]["should"] = should_filters
            body["query"]["bool"]["minimum_should_match"] = 1

        url = f"{self.base_url.rstrip('/')}/{target_index}/_search"
        try:
            async with httpx.AsyncClient(verify=self.verify_certs, timeout=30) as client:
                resp = await client.post(url, json=body, headers=self._headers())
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            logger.warning("OpenSearch event search failed: %s", exc)
            return []

        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        return self._format_hits(hits)


opensearch_rag = OpenSearchRAGClient()
