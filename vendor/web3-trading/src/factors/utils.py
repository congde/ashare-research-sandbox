"""因子计算的无状态辅助函数 — 归一化、提取、共识计算。"""

from __future__ import annotations

import math
from typing import Dict, List

from libs.valuescan.models import TradeDataItem

from .enums import DataGranularity, SignalDirection


TIME_PARTICLE_TO_GRANULARITY: Dict[int, DataGranularity] = {
    5: DataGranularity.M5,
    15: DataGranularity.M15,
    30: DataGranularity.M30,
    101: DataGranularity.H1,
    108: DataGranularity.H8,
    124: DataGranularity.H24,
}


def normalize_to_bipolar(value: float, center: float = 0.0, scale: float = 1.0) -> float:
    """通过 tanh sigmoid 将值归一化到 [-1, 1] 区间。

    Args:
        value: 待归一化的原始值。
        center: 映射到 0.0 的值。
        scale: 缩放因子 — 值越大输出越压缩。
    """
    if scale <= 0:
        return 0.0
    shifted = (value - center) / scale
    return float(math.tanh(shifted))


def clamp_score(value: float, low: float = -1.0, high: float = 1.0) -> float:
    """将得分钳制在 [low, high] 范围内。"""
    return max(low, min(high, value))


def extract_inflows(
    records: List[TradeDataItem], granularities: List[DataGranularity]
) -> Dict[DataGranularity, float]:
    """从资金交易记录中按粒度提取 tradeInflow 值。

    每条记录具有 ``time_particle_enum``（int）和 ``trade_inflow``（float）。
    同一粒度的多条记录会被累加。
    """
    result: Dict[DataGranularity, float] = {g: 0.0 for g in granularities}
    if not records:
        return result
    for record in records:
        gran = TIME_PARTICLE_TO_GRANULARITY.get(record.time_particle_enum)
        if gran is not None and gran in result:
            result[gran] += record.trade_inflow
    return result


def compute_change_rate(current: float, previous: float) -> float:
    """百分比变化率，零除安全。

    返回的值大致在 [-1, 1] 区间以便于解读，但极端变化时可能超出
    （如 10x → 9.0）。
    """
    if previous == 0:
        return 0.0 if current == 0 else (1.0 if current > 0 else -1.0)
    return (current - previous) / abs(previous)


def directional_consensus(values: List[float], threshold: float = 0.05) -> float:
    """从方向值列表中计算共识度。

    返回值在 [-1, 1] 区间：
      +1.0 = 所有值一致看涨
      -1.0 = 所有值一致看跌
       0.0 = 均分或全部中性
    """
    if not values:
        return 0.0
    positive = sum(1 for v in values if v > threshold)
    negative = sum(1 for v in values if v < -threshold)
    total_signals = positive + negative
    if total_signals == 0:
        return 0.0
    return (positive - negative) / total_signals


def score_to_direction(score: float) -> SignalDirection:
    """将 [-1, 1] 区间的归一化得分映射为 SignalDirection 枚举。

    使用渐进式阈值，确保弱信号被适当标注。
    """
    if score > 0.5:
        return SignalDirection.STRONG_BULLISH
    if score > 0.15:
        return SignalDirection.BULLISH
    if score > 0.03:
        return SignalDirection.NEUTRAL_BULLISH
    if score >= -0.03:
        return SignalDirection.NEUTRAL
    if score >= -0.15:
        return SignalDirection.NEUTRAL_BEARISH
    if score >= -0.5:
        return SignalDirection.BEARISH
    return SignalDirection.STRONG_BEARISH


def gran_to_tpe(gran: DataGranularity) -> int:
    """DataGranularity → time_particle_enum 映射。"""
    _map: dict[DataGranularity, int] = {
        DataGranularity.M5: 5,
        DataGranularity.M15: 15,
        DataGranularity.M30: 30,
        DataGranularity.H1: 101,
        DataGranularity.H8: 108,
        DataGranularity.H24: 124,
    }
    return _map.get(gran, 0)
