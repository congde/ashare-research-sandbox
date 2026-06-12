"""FactorRegistry — 自动发现并索引所有 BaseFactorComputer 子类。

添加新因子只需：(1) 在 common/、spot/ 或 contract/ 下创建文件，
(2) 定义一个带 ClassVar 元数据的类，(3) 实现 ``compute()`` 方法。
无需手动注册 — 注册中心会自动发现。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

from .base import BaseFactorComputer
from .enums import FactorCategory, MarketType

if TYPE_CHECKING:
    from .ranking import RankingProfile

logger = logging.getLogger(__name__)

_SUB_DIRS = ("common", "spot", "contract")


class FactorRegistry:
    """发现并索引所有因子计算器。

    遍历 ``computers/common/``、``computers/spot/``、``computers/contract/``
    目录，实例化所有继承自 ``BaseFactorComputer`` 的类。结果会被缓存。

    用法::

        registry = FactorRegistry()
        computers = registry.get_computers(market_type=MarketType.SPOT)
        print(registry.summary())
    """

    _computers: Dict[str, BaseFactorComputer] = {}
    _loaded: bool = False

    def __init__(self) -> None:
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # 发现
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_loaded(cls) -> None:
        """遍历 common/、spot/、contract/ 目录并实例化所有计算器类。"""
        if cls._loaded:
            return

        from . import computers as _pkg

        cls._computers = {}
        pkg_path = str(Path(_pkg.__file__).parent) if _pkg.__file__ else ""
        pkg_name = _pkg.__package__ or _pkg.__name__

        for sub_dir in _SUB_DIRS:
            dir_path = str(Path(pkg_path) / sub_dir)
            dir_pkg = f"{pkg_name}.{sub_dir}"
            try:
                modules = list(pkgutil.iter_modules([dir_path]))
            except Exception:
                logger.debug("Directory not found: %s", dir_path)
                continue

            for _, sub_name, _ in modules:
                try:
                    sub_mod = importlib.import_module(f".{sub_name}", package=dir_pkg)
                    cls._register_from_module(sub_mod)
                except Exception:
                    logger.debug(
                        "Skipping %s.%s (import failed)", sub_dir, sub_name, exc_info=True
                    )

        cls._loaded = True
        logger.info("FactorRegistry: loaded %d computers.", len(cls._computers))

    @classmethod
    def _register_from_module(cls, module) -> None:
        """扫描模块中 BaseFactorComputer 的子类并实例化。"""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseFactorComputer)
                and attr is not BaseFactorComputer
                and attr.factor_name
            ):
                if attr.factor_name in cls._computers:
                    logger.warning(
                        "Duplicate factor name: %s (from %s), overwriting.",
                        attr.factor_name,
                        module.__name__,
                    )
                cls._computers[attr.factor_name] = attr()

    # ------------------------------------------------------------------
    # 公开访问器
    # ------------------------------------------------------------------

    def get_computer(self, factor_name: str) -> Optional[BaseFactorComputer]:
        """按名称获取单个计算器。"""
        return self._computers.get(factor_name)

    def get_computers(
        self,
        categories: Optional[Set[FactorCategory]] = None,
        market_type: Optional[MarketType] = None,
    ) -> List[BaseFactorComputer]:
        """按分类和/或市场类型筛选计算器。"""
        result = list(self._computers.values())
        if categories:
            result = [c for c in result if c.category in categories]
        if market_type is not None:
            result = [c for c in result if market_type in c.supported_markets]
        return result

    def get_computers_by_profile(self, profile: RankingProfile) -> List[BaseFactorComputer]:
        """按 RankingProfile 排序返回计算器。

        仅返回 profile 中列出的因子，按 rank 升序排列。
        包含 common + 市场专属计算器。
        """
        result: List[BaseFactorComputer] = []
        for entry in profile.factors:
            if entry.weight <= 0:
                continue
            comp = self._computers.get(entry.factor_name)
            if comp is None:
                continue
            if profile.market_type in comp.supported_markets:
                result.append(comp)
        return result

    def list_factor_names(self) -> List[str]:
        """返回所有已注册的因子名称。"""
        return sorted(self._computers.keys())

    def summary(self) -> str:
        """按来源目录分组显示已注册因子的人类可读摘要。"""
        lines = [f"FactorRegistry: {len(self._computers)} computers loaded"]
        for sub_dir in _SUB_DIRS:
            comps = [c for c in self._computers.values()
                     if c.__class__.__module__.startswith(f"factors.computers.{sub_dir}")]
            if comps:
                lines.append(f"  {sub_dir}/ ({len(comps)}):")
                for c in sorted(comps, key=lambda x: x.factor_name):
                    lines.append(f"    {c.factor_name}  [{c.category.value}]")
        return "\n".join(lines)
