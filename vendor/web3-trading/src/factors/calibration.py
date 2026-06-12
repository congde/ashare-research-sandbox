# -*- coding: utf-8 -*-
"""置信度实证校准 — 将回测 Hit Rate 转换为经验置信度。

算法：
  1. 从 BacktestReport.per_factor 按 factor_name 取 sample_count 最大的 EvalMetrics
  2. 贝叶斯平滑：calibrated = (hits + α) / (total + α + β)
  3. 下限截断：max(floor, calibrated)
  4. 冷启动：sample_count < min_samples 时不覆盖硬编码值
  5. 写入 Redis (hot path) + 本地 JSONL (audit trail)
"""

from __future__ import annotations

import logging
import time
import uuid
from pydantic import BaseModel, Field

from factors.backtest.models import BacktestReport, EvalMetrics

logger = logging.getLogger(__name__)

# ── 校准记录模型 ────────────────────────────────────────────────────────────────


class PerFactorCalibration(BaseModel):
    """单个因子的校准结果。"""

    factor_name: str = Field(description="因子名称")
    raw_hit_rate: float = Field(description="原始 Hit Rate（回测方向正确率）")
    sample_count: int = Field(description="有效样本数")
    calibrated_confidence: float = Field(description="校准后的置信度 (0-1)")
    cold_start: bool = Field(default=False, description="是否冷启动（样本不足，未覆盖）")
    smoothing_params: dict[str, float] = Field(
        default_factory=lambda: {"alpha": 2.0, "beta": 2.0},
        description="贝叶斯平滑参数",
    )


class CalibrationRecord(BaseModel):
    """单次校准运行的持久化记录 — 追加写入本地 JSONL。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    created_at_ms: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="校准运行时间戳（毫秒）",
    )
    backtest_report_id: str = Field(description="关联的回测报告 ID")
    market_type: str = Field(default="spot", description="市场类型: spot / contract")
    calibrations: list[PerFactorCalibration] = Field(
        default_factory=list, description="每个因子的校准条目",
    )


# ── 校准器 ──────────────────────────────────────────────────────────────────────


class ConfidenceCalibrator:
    """从回测报告提取 Hit Rate，应用贝叶斯平滑后存储到 Redis + 本地文件。"""

    def __init__(
        self,
        alpha: float = 2.0,
        beta: float = 2.0,
        floor: float = 0.30,
        min_samples: int = 100,
        redis_cache=None,
    ) -> None:
        self._alpha = alpha
        self._beta = beta
        self._floor = floor
        self._min_samples = min_samples
        self._redis_cache = redis_cache

    # ── 公共 API ────────────────────────────────────────────────────────────

    async def calibrate_from_report(
        self,
        report: BacktestReport,
        market_type: str = "spot",
    ) -> CalibrationRecord:
        """从回测报告生成校准记录，写入 Redis + 本地文件。

        Returns:
            CalibrationRecord — 包含每个因子的校准结果。
        """
        best = self._select_best_metrics(report.per_factor)
        calibrations: list[PerFactorCalibration] = []

        for factor_name, metrics in best.items():
            should_cal = self.should_calibrate(metrics.sample_count)
            calibrated = self._compute_calibrated(metrics, should_cal)
            calibrations.append(PerFactorCalibration(
                factor_name=factor_name,
                raw_hit_rate=metrics.hit_rate,
                sample_count=metrics.sample_count,
                calibrated_confidence=calibrated,
                cold_start=not should_cal,
                smoothing_params={"alpha": self._alpha, "beta": self._beta},
            ))

        record = CalibrationRecord(
            backtest_report_id=report.id,
            market_type=market_type,
            calibrations=calibrations,
        )

        await self._store_redis(calibrations)
        await self._store_local(record)

        return record

    @staticmethod
    async def load_from_redis(redis_client) -> dict[str, float]:
        """从 Redis 批量加载所有校准置信度。

        用 scan_iter 遍历 confidence:* 前缀的所有 key，
        mget 批量取值后返回 {factor_name: confidence} 字典。
        Redis 不可达时返回空 dict。
        """
        try:
            raw = redis_client
            keys = [k async for k in raw.scan_iter(match="confidence:*")]
            if not keys:
                return {}
            # keys 格式: "confidence:spot_trade_inflow" → factor_name 取后半部分
            values = await raw.mget(keys)
            result: dict[str, float] = {}
            for key, val in zip(keys, values):
                if val is not None:
                    name = key.decode() if isinstance(key, bytes) else key
                    name = name.split(":", 1)[1]
                    result[name] = float(val)
            return result
        except Exception:
            logger.warning("Failed to load confidence from Redis.", exc_info=True)
            return {}

    # ── 静态算法方法 ─────────────────────────────────────────────────────────

    @staticmethod
    def bayesian_smooth(
        hit_rate: float,
        sample_count: int,
        alpha: float = 2.0,
        beta: float = 2.0,
    ) -> float:
        """贝叶斯平滑：Beta-Binomial conjugate prior。

        Returns:
            (hits + α) / (total + α + β)
        """
        hits = hit_rate * sample_count
        return (hits + alpha) / (sample_count + alpha + beta)

    @staticmethod
    def apply_floor(value: float, floor: float = 0.30) -> float:
        """下限截断。"""
        return max(floor, value)

    def should_calibrate(self, sample_count: int) -> bool:
        """冷启动判断：样本数 >= min_samples 时才启用校准值。"""
        return sample_count >= self._min_samples

    @staticmethod
    def _select_best_metrics(per_factor: list[EvalMetrics]) -> dict[str, EvalMetrics]:
        """每个 factor_name 选 sample_count 最大的单条 EvalMetrics（跨 horizon）。"""
        best: dict[str, EvalMetrics] = {}
        for m in per_factor:
            if m.factor_name not in best or m.sample_count > best[m.factor_name].sample_count:
                best[m.factor_name] = m
        return best

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _compute_calibrated(self, metrics: EvalMetrics, should_cal: bool) -> float:
        if not should_cal:
            return metrics.hit_rate  # 冷启动，保留原始值不做覆盖
        smoothed = self.bayesian_smooth(
            metrics.hit_rate, metrics.sample_count,
            self._alpha, self._beta,
        )
        return self.apply_floor(smoothed, self._floor)

    async def _store_redis(self, calibrations: list[PerFactorCalibration]) -> None:
        if self._redis_cache is None:
            return
        try:
            for c in calibrations:
                if not c.cold_start:
                    await self._redis_cache.set(
                        c.factor_name,
                        str(round(c.calibrated_confidence, 6)),
                        expire=2_678_400,  # 31 天
                    )
            logger.info("Stored %d confidence values to Redis.", len(calibrations))
        except Exception:
            logger.warning("Failed to store confidence to Redis.", exc_info=True)

    async def _store_local(self, record: CalibrationRecord) -> None:
        try:
            from factors.local_store import append_confidence_calibration

            await append_confidence_calibration(record.model_dump())
            logger.info("Stored calibration record %s locally.", record.id)
        except Exception:
            logger.error("Failed to store calibration record locally.", exc_info=True)
