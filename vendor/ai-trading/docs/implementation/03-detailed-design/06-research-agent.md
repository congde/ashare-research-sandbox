# 03/06 · Research Agent — 市场研究助手 [v1.5]

> 把 [ADD §03 三层 Agent](../../architecture/03-multi-agent-collaboration.md) 的 Research Agent 设计标记为 v1.5 实现，v1.0 留 placeholder。

---

## 1. 概述

Research Agent（角色 = market_researcher）整合宏观 / 链上 / 资金流 / 新闻 / 情绪数据，为 Strategy Agent 提供"市场假设是否成立"的证据，对外暴露查询接口。

> **状态：v1.5 启用**。v1.0 仅占位（domain seed + skill 框架），不真实调用。

## 2. 目标

- 为 Strategy Agent 的"市场假设"提供数据支撑
- 输出结构化 market_thesis（含引证）
- 多数据源 RAG（历史研究报告库 + 实时 API）
- 用户可单独调（"分析 BTC 当前市场状态"）

## 3. 范围

✅ v1.5：Glassnode / Dune / CryptoPanic / X(Twitter) / FRED 5 大数据源 + RAG
❌ v1.0：不真实调用（仅 stub） / v2.0：替代数据 / 链上深度

## 4. 关联 ADR / US

- [ADR-0004 LiteLLM](../../architecture/adrs/0004-litellm-as-llm-abstraction.md)
- US-AT-017（v1.5）

## 5. 设计要点

### Agent 注册（v1.5）

```python
{
    "id": "ai-trading.market_researcher",
    "role": "market_researcher",
    "primary_skill": "market_research_skill",
    "model_route": "market-researcher",
    "tools": [
        "query_glassnode", "query_dune", "query_cryptopanic",
        "query_x_trending", "query_macro_fred",
        "rag_search_research_reports",
    ],
    "max_loop_iterations": 6,
    "budget_per_run_usd": 0.20,
    "feature_flag": "feature.research_agent_enabled",
}
```

### v1.0 Stub

```python
async def query_research(symbol: str, query: str) -> MarketThesis:
    if not feature_flags.is_enabled("feature.research_agent_enabled"):
        return MarketThesis(
            thesis="（Research Agent v1.5 启用后提供）",
            evidence=[],
            confidence=0.0,
        )
    # v1.5 真实实现
    return await _real_query(symbol, query)
```

## 6. 接口与数据模型

```python
class MarketThesis(BaseModel):
    summary: str
    valid_period: tuple[datetime, datetime]
    evidence: list[Evidence]
    confidence: float  # 0.0 ~ 1.0
    contradicting_signals: list[str]
    recommended_strategy_types: list[str]  # ["grid", "trend", "dca"]

class Evidence(BaseModel):
    source: Literal["glassnode", "dune", "cryptopanic", "x_trending", "fred"]
    metric: str
    value: float | str
    timestamp: datetime
    citation_url: str
```

## 7. 关键 Prompt 模板（v1.5）

```
You are Market Researcher. Given a symbol and a question, gather evidence
from on-chain / macro / sentiment / news data sources and synthesize
into a structured MarketThesis.

# Rules
1. ALWAYS cite sources with URLs.
2. NEVER recommend "buy" or "sell" — only describe market state.
3. If evidence is conflicting, list both sides with confidence.
4. Use RAG to retrieve historical similar regimes (cosine similarity > 0.85).
```

## 8. RAG 设计（v1.5）

```sql
CREATE TABLE memory.research_reports_embeddings (
    id          uuid PRIMARY KEY,
    user_id     uuid NULL,   -- NULL = 平台共享
    title       text NOT NULL,
    content     text NOT NULL,
    embedding   vector(1024) NOT NULL,
    source      text,
    cited_url   text,
    created_at  timestamptz DEFAULT now()
);
CREATE INDEX idx_research_emb_hnsw ON memory.research_reports_embeddings
  USING hnsw (embedding vector_cosine_ops);
```

## 9. 配置与环境变量

```bash
RESEARCH_AGENT_ENABLED=false   # v1.0 默认关
GLASSNODE_API_KEY=...
DUNE_API_KEY=...
CRYPTOPANIC_API_KEY=...
X_API_BEARER_TOKEN=...
FRED_API_KEY=...
RESEARCH_AGENT_BUDGET_USD=0.20
```

## 10. 异常路径与降级

| 故障 | 处理 |
|---|---|
| 单源失败 | 跳过该源 + 标"evidence partial" |
| 全源失败 | thesis = empty + confidence = 0 |
| RAG 不可达 | 仅用实时 API |
| 预算超 | 缓存最近 24h 同 symbol 结果 |

## 11. 测试清单（v1.5）

| 类型 | 用例 |
|---|---|
| **单元** | 各 source adapter 序列化 / 错误处理 |
| **集成** | 端到端 query_research(BTC) → MarketThesis |
| **Eval** | 30 个历史时点 → "假设是否合理" 人工标注 |

## 12. 监控埋点

- `research_agent_runs_total{status}` Counter
- `research_data_source_latency_ms{source}` Histogram
- `research_data_source_fail_total{source}` Counter
- `research_rag_hit_rate` Gauge

## 13. 安全与合规

- API key 用 KMS 加密
- 用户问询不进 Embedding Index（除非明确同意）
- 数据源 ToS 遵守（如 X API 速率）

## 14. Open Questions

- 是否引入 OpenSea / Etherscan 链上深度？（v2）
- 是否做"研究报告共享市集"？（v1.5 评估）

## 15. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| v1.0 | 2026-05-08 | 初版（v1.0 仅 stub） | AI 工程 |
