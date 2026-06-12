# -*- coding: utf-8 -*-
"""
Thinking Quality - DAG 节点关键性分析与门控

灵感来源: "Think Deep, Not Just Long" (Google, 2026)
核心思想: 不是所有 token 都需要深度计算，关键 token 才需要。
映射到 DAG: 不是所有任务节点都同等重要，关键节点失败时值得重试。

功能:
- TaskCriticalityAnalyzer: 基于 DAG 拓扑和工具类型分析节点关键性
- ThinkingQualityConfig: 通过 Apollo/YAML 热配置，所有功能默认关闭

生产安全:
- 所有功能通过 config 开关控制，默认关闭
- 分析逻辑纯函数，无副作用
- 任何异常静默降级，不影响主流程
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ThinkingQualityConfig:
    """Thinking quality 功能配置，所有开关默认关闭。"""

    enable_criticality_gating: bool = False
    critical_task_max_retries: int = 1
    critical_task_retry_delay_s: float = 0.5

    @classmethod
    def from_config(cls, config_obj) -> "ThinkingQualityConfig":
        """从应用 config 对象安全加载，缺失字段用默认值。"""
        try:
            tq = getattr(config_obj, "thinking_quality", None)
            if tq is None:
                return cls()
            return cls(
                enable_criticality_gating=bool(
                    getattr(tq, "enable_criticality_gating", False)
                ),
                critical_task_max_retries=int(
                    getattr(tq, "critical_task_max_retries", 1)
                ),
                critical_task_retry_delay_s=float(
                    getattr(tq, "critical_task_retry_delay_s", 0.5)
                ),
            )
        except Exception as e:
            logger.warning(f"[ThinkingQuality] Config load failed, using defaults: {e}")
            return cls()


class TaskCriticalityAnalyzer:
    """
    基于 DAG 拓扑结构和工具类型，为每个任务标注关键性等级。

    "critical" — 失败时值得重试（类比 deep-thinking token）
    "normal"   — 标准处理
    "low"      — 辅助任务，失败可容忍

    判定规则:
    1. 叶子节点（无下游依赖）→ critical（直接影响最终输出）
    2. 扇出 >= 2 的节点 → critical（失败会级联阻断多个下游）
    3. 特定高价值工具 → critical
    4. 特定低价值工具 → low
    5. 其余 → normal
    """

    CRITICAL_TOOLS = frozenset({
        "web_search",
        "kb_search",
        "retrieve_fundamental_events",
        "get_crypto_market_data",
        "coin_screener",
        "recommend_financial_product",
        "get_crypto_investment_outlook",
    })

    LOW_TOOLS = frozenset({
        "direct_response",
    })

    @classmethod
    def analyze(cls, plan) -> Dict[str, str]:
        """
        返回 {task_id: "critical" | "normal" | "low"}。

        plan 需要有 .tasks 属性（List of objects with .id, .tool, .depends_on）。
        """
        if not plan or not getattr(plan, "tasks", None):
            return {}

        dependents_count: Dict[str, int] = {t.id: 0 for t in plan.tasks}
        for t in plan.tasks:
            for dep_id in t.depends_on:
                if dep_id in dependents_count:
                    dependents_count[dep_id] += 1

        leaf_ids = {tid for tid, cnt in dependents_count.items() if cnt == 0}

        result = {}
        for task in plan.tasks:
            if task.tool in cls.LOW_TOOLS:
                criticality = "low"
            elif task.tool in cls.CRITICAL_TOOLS:
                criticality = "critical"
            elif task.id in leaf_ids:
                criticality = "critical"
            elif dependents_count.get(task.id, 0) >= 2:
                criticality = "critical"
            else:
                criticality = "normal"

            result[task.id] = criticality

        return result


__all__ = ["ThinkingQualityConfig", "TaskCriticalityAnalyzer"]
