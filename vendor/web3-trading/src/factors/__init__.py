# -*- coding: utf-8 -*-
"""Web3 量化交易的因子计算层。

基于 ValueScan SDK 数据，提供约 31 项可排序的交易信号因子。
每个因子输出携带完整推理链（DecisionTrace），使信号可直接被下游
LLM Agent 消费，无需额外 prompt 工程。

用法::

    from factors import FactorPipeline, PipelineConfig, FactorTier
    from libs.valuescan import ValueScanClient

    client = ValueScanClient.from_env()
    pipeline = FactorPipeline(client, PipelineConfig.standard())
    bundle = await pipeline.compute_all("BTC")

    print(f"Aggregate score: {bundle.aggregate_score:.3f}")
    for r in bundle.tier1_results:
        print(f"  {r.display_name}: {r.signal_direction} ({r.normalized_score:+.3f})")
        for link in r.trace.evidence_chain:
            print(f"    → {link.interpretation}")
"""

from .base import BaseFactorComputer
from .config import PipelineConfig
from .context import FactorContext
from .enums import DataGranularity, FactorCategory, FactorTier, MarketType, SignalDirection
from .exceptions import (
    ComputationError,
    DataUnavailableError,
    FactorError,
    InvalidScoreError,
)
from .models import (
    CrossFactorResult,
    DecisionTrace,
    EvidenceLink,
    FactorBundle,
    FactorMeta,
    FactorResult,
    GranularityValue,
)
from .calibration import CalibrationRecord, ConfidenceCalibrator, PerFactorCalibration
from .fetch import CircuitBreaker, CircuitState, DataSourceHealth, HealthStatus, RetryConfig, with_retry
from .pipeline import FactorPipeline
from .ranking import CONTRACT_DEFAULT_PROFILE, SPOT_DEFAULT_PROFILE, FactorEntry, RankingProfile
from .analysis import (
    ABTestReport,
    ABTestWinner,
    CollinearityGroup,
    CollinearitySeverity,
    CorrelationMatrix,
    DedupPlan,
    MarketState,
    MarketStateResult,
    OptimizedWeight,
    OptimizerResult,
    OptimizerType,
    StateProfile,
    StateWeightBias,
)
from .validation import QualityChecker, QualityLevel, QualityReport, QualityReportRecord, store_quality_report

__all__ = [
    # 管线
    "FactorPipeline",
    "PipelineConfig",
    "FactorContext",
    # 基类
    "BaseFactorComputer",
    # 模型
    "FactorResult",
    "FactorBundle",
    "FactorMeta",
    "CrossFactorResult",
    "DecisionTrace",
    "EvidenceLink",
    "GranularityValue",
    # 枚举
    "FactorTier",
    "FactorCategory",
    "SignalDirection",
    "DataGranularity",
    "MarketType",
    # 排序
    "RankingProfile",
    "FactorEntry",
    "SPOT_DEFAULT_PROFILE",
    "CONTRACT_DEFAULT_PROFILE",
    # 异常
    "FactorError",
    "DataUnavailableError",
    "ComputationError",
    "InvalidScoreError",
    # 校准
    "ConfidenceCalibrator",
    "CalibrationRecord",
    "PerFactorCalibration",
    # 容错
    "CircuitBreaker",
    "CircuitState",
    "DataSourceHealth",
    "HealthStatus",
    "RetryConfig",
    "with_retry",
    # 数据质量
    "QualityChecker",
    "QualityLevel",
    "QualityReport",
    "QualityReportRecord",
    "store_quality_report",
    # 分析 (P2)
    "ABTestReport",
    "ABTestWinner",
    "CollinearityGroup",
    "CollinearitySeverity",
    "CorrelationMatrix",
    "DedupPlan",
    "MarketState",
    "MarketStateResult",
    "OptimizedWeight",
    "OptimizerResult",
    "OptimizerType",
    "StateProfile",
    "StateWeightBias",
]
