"""FactorContext — 将单一代币的所有原始数据打包，供计算时使用。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field

from libs.valuescan.models import VSBaseModel

from .enums import MarketType


class FactorContext(VSBaseModel):
    """打包单个代币的全部 ValueScan 原始数据。

    这是传递给每个因子计算器的唯一参数。
    管线一次性拉取所有数据；所有计算器从这一共享上下文中读取。

    ``data`` 字典以短名称存储原始 API 响应。
    计算器通过 ``ctx.data[key]`` 访问所需子集。
    """

    vs_token_id: str
    symbol: str = ""
    coin_key: str = ""
    fetched_at_ms: int = 0

    # 以短名称为键的原始数据。键与计算器上的 ``requires_data`` 相对应。
    data: Dict[str, Any] = Field(default_factory=dict)

    # 上下文构建过程中派生的元数据
    has_spot: bool = False
    has_contract: bool = False
    current_price: float = 0.0
    market_cap: float = 0.0

    # 本次计算的目标市场
    market_type: MarketType = MarketType.SPOT

    # 数据源健康状态（fetch 阶段注入）
    data_health: Dict[str, Any] = Field(default_factory=dict, description="各数据源健康状态快照")

    # 数据质量报告及其 MongoDB 记录 ID（管线注入）
    data_quality_report: Optional[Any] = Field(default=None, description="QualityReport 或 None")
    quality_report_id: str = Field(default="", description="本地质量报告 ID，供 DataRecorder 写入 factor_snapshots")

    model_config = ConfigDict(frozen=False, extra="allow")
