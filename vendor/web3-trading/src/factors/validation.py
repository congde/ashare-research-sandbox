"""数据质量校验 — Schema、值域、新鲜度、完整性校验。

在管线数据拉取完成后运行，生成 QualityReport 注入 FactorContext。
因子计算器在 check_prerequisites 和 compute 中读取报告决定是否降级。

持久化：每次校验结果追加写入本地 data/data_quality_reports/quality_YYYYMMDD.jsonl，
保留完整审计历史，支持按 symbol、时间范围、质量等级查询。
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 质量等级
# ---------------------------------------------------------------------------


class QualityLevel(StrEnum):
    PASS = "pass"          # 全部通过
    WARN = "warn"          # 存在轻微问题，可继续
    FAIL = "fail"          # 严重问题，应降级或跳过


# ---------------------------------------------------------------------------
# 校验结果模型
# ---------------------------------------------------------------------------


class FieldIssue(BaseModel):
    """单个字段的校验问题。"""
    field: str = Field(description="问题字段名")
    issue: str = Field(description="问题描述")
    level: QualityLevel = Field(default=QualityLevel.WARN, description="严重程度")


class DataKeyReport(BaseModel):
    """单个 data key 的质量报告。"""
    key: str = Field(description="ctx.data 中的 key")
    status: QualityLevel = Field(description="最严重的问题等级")
    issues: List[FieldIssue] = Field(default_factory=list, description="所有校验问题")
    checked_at_ms: int = Field(default=0, description="校验时间戳")


class QualityReport(BaseModel):
    """一次数据拉取的完整质量报告。"""
    overall: QualityLevel = Field(default=QualityLevel.PASS, description="综合质量等级")
    per_key: Dict[str, DataKeyReport] = Field(default_factory=dict, description="按 data key 分组的报告")
    summary: str = Field(default="", description="人类可读的汇总")


# ---------------------------------------------------------------------------
# 数据新鲜度阈值（秒）
# ---------------------------------------------------------------------------

DEFAULT_FRESHNESS_S: dict[str, float] = {
    "realtime_fund": 60,
    "token_flow": 60,
    "fund_snapshot": 120,
    "market_cap_ratio": 120,
    "whale_cost": 120,
    "social_sentiment": 120,
    "price_indicators": 300,
    "large_transactions": 600,
    "holder_list": 600,
    "kline": 300,
    "funding_rate": 300,
    "open_interest": 300,
    "ai_chance": 120,
    "ai_risk": 120,
    "ai_funds": 120,
    "sector_fund_list": 600,
    "sector_coin_list": 600,
}


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------


class FreshnessValidator:
    """校验数据时间戳是否在允许窗口内。"""

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self._thresholds = thresholds or DEFAULT_FRESHNESS_S

    def check(self, key: str, data: Any, fetched_at_ms: int) -> List[FieldIssue]:
        threshold = self._thresholds.get(key)
        if threshold is None:
            return []
        issues: List[FieldIssue] = []
        now_ms = int(time.time() * 1000)
        age_s = (now_ms - fetched_at_ms) / 1000.0
        if age_s > threshold * 3:
            issues.append(FieldIssue(
                field=key,
                issue=f"数据已过期 {age_s:.0f}s，阈值 {threshold}s",
                level=QualityLevel.FAIL,
            ))
        elif age_s > threshold:
            issues.append(FieldIssue(
                field=key,
                issue=f"数据接近过期 {age_s:.0f}s，阈值 {threshold}s",
                level=QualityLevel.WARN,
            ))
        return issues


class CompletenessValidator:
    """校验必需数据 key 不为 None，容器不为空。"""

    def check(self, key: str, data: Any) -> List[FieldIssue]:
        issues: List[FieldIssue] = []
        if data is None:
            issues.append(FieldIssue(
                field=key,
                issue="数据缺失 (None)",
                level=QualityLevel.FAIL,
            ))
        elif isinstance(data, (list, dict)) and len(data) == 0:
            issues.append(FieldIssue(
                field=key,
                issue=f"数据为空 ({type(data).__name__})",
                level=QualityLevel.WARN,
            ))
        return issues


class RangeValidator:
    """校验数值字段在合理范围内。

    只报告明显异常的值（如价格为负数、流入量超出常规）。
    """

    # 按 data key 配置的范围规则
    _RULES: dict[str, list[tuple[str, tuple[float, float]]]] = {
        "whale_cost": [("price", (0.0, 1_000_000.0))],
        "realtime_fund": [
            ("spot_goods_list.[].inflow", (-1e8, 1e8)),
            ("contract_list.[].inflow", (-1e8, 1e8)),
        ],
        "funding_rate": [("values.[]", (-0.05, 0.05))],
    }

    def check(self, key: str, data: Any) -> List[FieldIssue]:
        rules = self._RULES.get(key, [])
        if not rules:
            return []
        issues: List[FieldIssue] = []
        for field_path, (low, high) in rules:
            try:
                value = self._resolve(data, field_path)
                if value is not None and (value < low or value > high):
                    issues.append(FieldIssue(
                        field=f"{key}.{field_path}",
                        issue=f"值 {value} 超出合理范围 [{low}, {high}]",
                        level=QualityLevel.WARN,
                    ))
            except (TypeError, KeyError, IndexError, AttributeError):
                pass
        return issues

    @staticmethod
    def _resolve(obj: Any, path: str) -> Any:
        """解析点分隔+[]索引的路径，如 'spot_goods_list.[].inflow'。"""
        parts = path.replace(".[]", "").split(".")
        for part in parts:
            if obj is None:
                return None
            if isinstance(obj, list):
                try:
                    obj = obj[0]
                except IndexError:
                    return None
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        return obj


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


class QualityChecker:
    """编排所有校验器，生成 QualityReport。"""

    def __init__(
        self,
        freshness: FreshnessValidator | None = None,
        completeness: CompletenessValidator | None = None,
        range_validator: RangeValidator | None = None,
    ) -> None:
        self._freshness = freshness or FreshnessValidator()
        self._completeness = completeness or CompletenessValidator()
        self._range = range_validator or RangeValidator()

    def check(self, data: dict[str, Any], fetched_at_ms: int) -> QualityReport:
        """对所有 data key 运行校验，生成质量报告。"""
        per_key: dict[str, DataKeyReport] = {}
        overall = QualityLevel.PASS

        for key, value in data.items():
            issues: List[FieldIssue] = []
            issues.extend(self._completeness.check(key, value))
            issues.extend(self._freshness.check(key, value, fetched_at_ms))
            issues.extend(self._range.check(key, value))

            key_status = QualityLevel.PASS
            for issue in issues:
                if issue.level == QualityLevel.FAIL:
                    key_status = QualityLevel.FAIL
                elif issue.level == QualityLevel.WARN and key_status != QualityLevel.FAIL:
                    key_status = QualityLevel.WARN

            if key_status == QualityLevel.FAIL:
                overall = QualityLevel.WARN
            elif key_status == QualityLevel.WARN and overall == QualityLevel.PASS:
                overall = QualityLevel.WARN

            summary_parts: list[str] = []
            fail_count = sum(1 for i in issues if i.level == QualityLevel.FAIL)
            warn_count = sum(1 for i in issues if i.level == QualityLevel.WARN)
            if fail_count:
                summary_parts.append(f"{fail_count} FAIL")
            if warn_count:
                summary_parts.append(f"{warn_count} WARN")

            per_key[key] = DataKeyReport(
                key=key,
                status=key_status,
                issues=issues,
                checked_at_ms=int(time.time() * 1000),
            )

        fails = sum(1 for r in per_key.values() if r.status == QualityLevel.FAIL)
        warns = sum(1 for r in per_key.values() if r.status == QualityLevel.WARN)
        if fails > 0:
            overall = QualityLevel.FAIL if fails > len(per_key) * 0.3 else QualityLevel.WARN

        summary = f"{len(per_key)} keys checked"
        if fails:
            summary += f", {fails} failed"
        if warns:
            summary += f", {warns} warnings"

        return QualityReport(overall=overall, per_key=per_key, summary=summary)


# ---------------------------------------------------------------------------
# 本地持久化
# ---------------------------------------------------------------------------


class QualityReportRecord(BaseModel):
    """单次数据质量校验的持久化记录 — 追加写入本地 JSONL。

    由 factor_snapshots.quality_report_id 关联，
    查询入口为 factor_snapshots 表或本地 quality_*.jsonl 文件。
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    created_at_ms: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="校验运行时间戳（毫秒）",
    )
    symbol: str = Field(description="代币符号，如 BTC、ETH")
    vs_token_id: str = Field(default="", description="ValueScan 代币 ID")
    market_type: str = Field(default="spot", description="市场类型: spot / contract")
    overall: str = Field(description="综合质量等级: pass / warn / fail")
    summary: str = Field(default="", description="人类可读的汇总")
    per_key: Dict[str, Any] = Field(default_factory=dict, description="按 data key 分组的校验详情")
    data_health: Dict[str, Any] = Field(default_factory=dict, description="数据源健康状态快照")


async def store_quality_report(
    report: QualityReport,
    *,
    symbol: str = "",
    vs_token_id: str = "",
    market_type: str = "spot",
    data_health: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """将质量报告追加写入本地 JSONL。

    Args:
        report: QualityChecker.check() 的输出。
        symbol: 代币符号。
        vs_token_id: ValueScan 代币 ID。
        market_type: 市场类型。
        data_health: HealthTracker.snapshot() 的输出。

    Returns:
        记录的 ID，失败时返回 None。
    """
    record = QualityReportRecord(
        symbol=symbol,
        vs_token_id=vs_token_id,
        market_type=market_type,
        overall=report.overall.value,
        summary=report.summary,
        per_key={k: v.model_dump() for k, v in report.per_key.items()},
        data_health=data_health or {},
    )
    try:
        from factors.local_store import append_quality_report

        await append_quality_report(record.model_dump())
        logger.info(
            "Stored quality report %s locally (symbol=%s, overall=%s).",
            record.id,
            symbol,
            report.overall.value,
        )
        return record.id
    except Exception:
        logger.warning("Failed to store quality report locally.", exc_info=True)
        return None
