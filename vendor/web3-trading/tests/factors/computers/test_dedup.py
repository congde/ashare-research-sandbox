# -*- coding: utf-8 -*-
"""验证 spot/contract 去重后子类完整性和 Registry 兼容性。"""

from factors.computers._base_flow import (
    _BaseConsistencyComputer,
    _BaseInflowComputer,
    _BaseMarketCapRatioComputer,
    _BaseMaxInflowComputer,
    _BasePersistenceComputer,
    _BaseSnapshotComputer,
)
from factors.computers.contract.consistency import ContractConsistencyComputer
from factors.computers.contract.inflow import ContractTradeInflowComputer
from factors.computers.contract.market_cap_ratio import ContractMarketCapRatioComputer
from factors.computers.contract.max_inflow import ContractMaxInflowComputer
from factors.computers.contract.persistence import ContractPersistenceComputer
from factors.computers.contract.snapshot import ContractFundSnapshotComputer
from factors.computers.spot.consistency import SpotConsistencyComputer
from factors.computers.spot.inflow import SpotTradeInflowComputer
from factors.computers.spot.market_cap_ratio import SpotMarketCapRatioComputer
from factors.computers.spot.max_inflow import SpotMaxInflowComputer
from factors.computers.spot.persistence import SpotPersistenceComputer
from factors.computers.spot.snapshot import SpotFundSnapshotComputer
from factors.registry import FactorRegistry


SPOT_CLASSES = [
    SpotConsistencyComputer, SpotTradeInflowComputer, SpotMarketCapRatioComputer,
    SpotMaxInflowComputer, SpotPersistenceComputer, SpotFundSnapshotComputer,
]
CONTRACT_CLASSES = [
    ContractConsistencyComputer, ContractTradeInflowComputer, ContractMarketCapRatioComputer,
    ContractMaxInflowComputer, ContractPersistenceComputer, ContractFundSnapshotComputer,
]
BASE_CLASSES = [
    _BaseConsistencyComputer, _BaseInflowComputer, _BaseMarketCapRatioComputer,
    _BaseMaxInflowComputer, _BasePersistenceComputer, _BaseSnapshotComputer,
]


class TestSubclassInheritance:
    def test_all_spot_subclasses_inherit_correctly(self) -> None:
        bases = {
            SpotConsistencyComputer: _BaseConsistencyComputer,
            SpotTradeInflowComputer: _BaseInflowComputer,
            SpotMarketCapRatioComputer: _BaseMarketCapRatioComputer,
            SpotMaxInflowComputer: _BaseMaxInflowComputer,
            SpotPersistenceComputer: _BasePersistenceComputer,
            SpotFundSnapshotComputer: _BaseSnapshotComputer,
        }
        for cls, expected_base in bases.items():
            assert issubclass(cls, expected_base), f"{cls.__name__} not subclass of {expected_base.__name__}"

    def test_all_contract_subclasses_inherit_correctly(self) -> None:
        bases = {
            ContractConsistencyComputer: _BaseConsistencyComputer,
            ContractTradeInflowComputer: _BaseInflowComputer,
            ContractMarketCapRatioComputer: _BaseMarketCapRatioComputer,
            ContractMaxInflowComputer: _BaseMaxInflowComputer,
            ContractPersistenceComputer: _BasePersistenceComputer,
            ContractFundSnapshotComputer: _BaseSnapshotComputer,
        }
        for cls, expected_base in bases.items():
            assert issubclass(cls, expected_base), f"{cls.__name__} not subclass of {expected_base.__name__}"


class TestClassVarIsolation:
    """验证 spot/contract 的 ClassVar 互不污染。"""

    def test_data_field_differs(self) -> None:
        assert SpotConsistencyComputer._DATA_FIELD == "spot_goods_list"
        assert ContractConsistencyComputer._DATA_FIELD == "contract_list"
        assert SpotConsistencyComputer._DATA_FIELD != ContractConsistencyComputer._DATA_FIELD

    def test_market_label_differs(self) -> None:
        assert SpotConsistencyComputer._MARKET_LABEL == "现货"
        assert ContractConsistencyComputer._MARKET_LABEL == "合约"
        assert SpotTradeInflowComputer._MARKET_LABEL == "现货"
        assert ContractTradeInflowComputer._MARKET_LABEL == "合约"

    def test_factor_names_are_unique(self) -> None:
        all_names = [c.factor_name for c in SPOT_CLASSES + CONTRACT_CLASSES]
        assert len(all_names) == len(set(all_names))

    def test_supported_markets_are_correct(self) -> None:
        for cls in SPOT_CLASSES:
            # 通过类属性直接访问
            assert "SPOT" in str(cls.supported_markets) or any(
                m.value == "spot" for m in cls.supported_markets
            )
        for cls in CONTRACT_CLASSES:
            assert "CONTRACT" in str(cls.supported_markets) or any(
                m.value == "contract" for m in cls.supported_markets
            )


class TestRegistryCompatibility:
    """验证 FactorRegistry 不注册中间基类，能发现所有 12 个子类。"""

    def test_base_classes_not_in_registry(self) -> None:
        for base_cls in BASE_CLASSES:
            assert not base_cls.factor_name, f"{base_cls.__name__} should have empty factor_name"

    def test_all_12_subclasses_in_registry(self) -> None:
        registry = FactorRegistry()
        expected_names = {c.factor_name for c in SPOT_CLASSES + CONTRACT_CLASSES}
        registered = set(registry.list_factor_names())
        missing = expected_names - registered
        assert not missing, f"Missing from registry: {missing}"

    def test_all_subclasses_instantiatable(self) -> None:
        for cls in SPOT_CLASSES + CONTRACT_CLASSES:
            instance = cls()
            assert instance.factor_name
