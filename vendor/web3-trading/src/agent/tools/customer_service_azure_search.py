# -*- coding: utf-8 -*-
"""
Azure AI Search 兜底检索客户端

使用 Hybrid 模式（BM25 关键词 + kNN 向量），Azure 内部自动做 RRF 融合排序。
作为灵库向量检索的兜底路径，当灵库未命中时降级到此。
"""

import logging
from typing import List, Dict, Any, Optional

import httpx

from web.config import config

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  数据结构
# --------------------------------------------------------------------------- #

class AzureSearchResult:
    """单条检索结果"""
    __slots__ = ("doc_id", "score", "content", "text", "source", "category", "tags")

    def __init__(self, raw: Dict[str, Any]):
        self.doc_id = raw.get("id", "")
        self.score = raw.get("@search.score", 0.0)
        self.content = raw.get("content", "")
        self.text = raw.get("text", "")
        self.source = raw.get("source", "")
        self.category = raw.get("category", "")
        self.tags = raw.get("tags", "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "score": self.score,
            "content": self.content,
            "text": self.text,
            "source": self.source,
            "category": self.category,
        }


# --------------------------------------------------------------------------- #
#  客户端
# --------------------------------------------------------------------------- #

class AzureSearchClient:
    """
    Azure AI Search 异步客户端

    支持三种检索模式：
    - keyword:  纯 BM25 关键词
    - vector:   纯 kNN 向量
    - hybrid:   BM25 + kNN（默认，推荐）
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        index_name: Optional[str] = None,
        api_version: str = "2024-05-01-Preview",
        vector_field: str = "embedding",
        vector_dimensions: int = 1536,
        timeout: float = 10.0,
    ):
        self.endpoint = (endpoint or getattr(config, "azure_search_endpoint", None) or "").rstrip("/")
        self.api_key = api_key or getattr(config, "azure_search_api_key", None) or ""
        self.index_name = index_name or getattr(config, "azure_search_index_name", None) or ""
        self.api_version = api_version
        self.vector_field = vector_field
        self.vector_dimensions = vector_dimensions
        self.timeout = timeout

    @property
    def _search_url(self) -> str:
        return f"{self.endpoint}/indexes/{self.index_name}/docs/search?api-version={self.api_version}"

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

    # ----- public API ------------------------------------------------------ #

    async def search(
        self,
        query: str,
        vector: Optional[List[float]] = None,
        top_k: int = 5,
        mode: str = "hybrid",
        select: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
        score_threshold: float = 0.0,
    ) -> List[AzureSearchResult]:
        """
        执行检索

        Args:
            query: 用户查询文本（BM25 部分）
            vector: 查询向量（kNN 部分），hybrid/vector 模式必须传
            top_k: 返回条数
            mode: keyword / vector / hybrid
            select: 返回字段列表
            filter_expr: OData 过滤表达式
            score_threshold: 最低分数阈值，低于此分数的结果会被过滤

        Returns:
            按分数降序排列的结果列表
        """
        if not self.endpoint or not self.api_key or not self.index_name:
            logger.warning("[AzureSearch] 缺少 endpoint/api_key/index_name 配置，跳过检索")
            return []

        payload: Dict[str, Any] = {"top": top_k}

        if select:
            payload["select"] = ",".join(select)
        if filter_expr:
            payload["filter"] = filter_expr

        # BM25
        if mode in ("keyword", "hybrid"):
            payload["search"] = query

        # kNN
        if mode in ("vector", "hybrid") and vector is not None:
            payload["vectorQueries"] = [{
                "kind": "vector",
                "vector": vector,
                "fields": self.vector_field,
                "k": top_k,
            }]

        # vector-only 需要 search=*
        if mode == "vector":
            payload["search"] = "*"

        try:
            async with httpx.AsyncClient(verify=False, timeout=self.timeout) as client:
                resp = await client.post(self._search_url, headers=self._headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"[AzureSearch] 请求超时 ({self.timeout}s)", exc_info=False)
            return []
        except Exception:
            logger.error("[AzureSearch] 请求异常", exc_info=True)
            return []

        raw_results = data.get("value", [])
        results = [AzureSearchResult(r) for r in raw_results if r.get("@search.score", 0) >= score_threshold]
        results.sort(key=lambda r: r.score, reverse=True)

        logger.info(f"[AzureSearch] query='{query[:60]}' mode={mode} top_k={top_k} → {len(results)} 条（原始 {len(raw_results)} 条）")
        return results


# --------------------------------------------------------------------------- #
#  模块级单例
# --------------------------------------------------------------------------- #

azure_search_client = AzureSearchClient()
