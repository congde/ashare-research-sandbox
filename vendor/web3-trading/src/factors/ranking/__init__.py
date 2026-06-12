"""因子排序与权重系统。

RankingProfile 由外层动态传入，决定：
- 因子排序位置（rank → factor_index）
- 聚合权重（weight）
- 因子层级（tier）

支持不同市场类型、不同代币使用不同的排序配置。
"""

from .presets import CONTRACT_DEFAULT_PROFILE, SPOT_DEFAULT_PROFILE
from .profile import FactorEntry, RankingProfile

__all__ = [
    "FactorEntry",
    "RankingProfile",
    "SPOT_DEFAULT_PROFILE",
    "CONTRACT_DEFAULT_PROFILE",
]
