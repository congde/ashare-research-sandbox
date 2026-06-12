"""因子计算错误层级。"""

from __future__ import annotations

from typing import Optional


class FactorError(Exception):
    """所有因子计算错误的基类。"""

    def __init__(
        self,
        message: str,
        *,
        factor_name: str = "",
        vs_token_id: Optional[str] = None,
        symbol: str = "",
    ) -> None:
        super().__init__(message)
        self.factor_name = factor_name
        self.vs_token_id = vs_token_id
        self.symbol = symbol


class DataUnavailableError(FactorError):
    """必需的数据源返回了 None 或空值。"""


class ComputationError(FactorError):
    """因子计算逻辑执行失败。"""


class TimeoutError(FactorError):
    """因子计算超过超时限制。"""


class InvalidScoreError(FactorError):
    """计算得分超出有效范围 [-1, 1]。"""
