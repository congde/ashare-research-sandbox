"""现货资金快照拐点检测 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseSnapshotComputer


class SpotFundSnapshotComputer(_BaseSnapshotComputer):
    factor_name: ClassVar[str] = "spot_fund_snapshot"
    display_name: ClassVar[str] = "资金快照拐点检测(现货)"
    description: ClassVar[str] = "现货资金快照拐点检测，按粒度逐一对比。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _SNAP_DATA_FIELD: ClassVar[str] = "spot_goods_list"
    _RT_DATA_FIELD: ClassVar[str] = "spot_goods_list"
    _MARKET_LABEL: ClassVar[str] = "现货"
    _SIGN_CHANGE_SCORE: ClassVar[float] = 0.4
    _CLAMP_LOW: ClassVar[float] = -0.6
    _CLAMP_HIGH: ClassVar[float] = 0.6
    _DIRECTION_THRESHOLD: ClassVar[float] = 0.2
    _ACTION_BULLISH: ClassVar[str] = "多粒度资金方向由流入转为流出，态度反转偏多。"
    _ACTION_BEARISH: ClassVar[str] = "多粒度资金方向由流出转为流入，态度反转偏空。"
    _CONCLUSION_TPL: ClassVar[str] = "{label}快照拐点检测: {changes}个粒度出现方向反转。得分={score:+.3f}。"
