"""tests for factors/exceptions.py"""

import pytest

from factors.exceptions import (
    ComputationError,
    DataUnavailableError,
    FactorError,
    InvalidScoreError,
    TimeoutError,
)


class TestFactorError:
    def test_base_message(self) -> None:
        err = FactorError("something went wrong")
        assert str(err) == "something went wrong"

    def test_with_context(self) -> None:
        err = FactorError(
            "failed", factor_name="deviation", vs_token_id="btc_001", symbol="BTC"
        )
        assert err.factor_name == "deviation"
        assert err.vs_token_id == "btc_001"
        assert err.symbol == "BTC"

    def test_default_context(self) -> None:
        err = FactorError("bare")
        assert err.factor_name == ""
        assert err.vs_token_id is None
        assert err.symbol == ""


class TestDataUnavailableError:
    def test_is_factor_error(self) -> None:
        err = DataUnavailableError("missing data")
        assert isinstance(err, FactorError)

    def test_with_factor_name(self) -> None:
        err = DataUnavailableError("whale_cost is None", factor_name="deviation")
        assert err.factor_name == "deviation"


class TestComputationError:
    def test_is_factor_error(self) -> None:
        err = ComputationError("math error")
        assert isinstance(err, FactorError)

    def test_can_wrap_cause(self) -> None:
        try:
            raise ValueError("original")
        except ValueError as exc:
            wrapped = ComputationError("computation failed")
            wrapped.__cause__ = exc
            assert wrapped.__cause__ is exc


class TestTimeoutError:
    def test_is_factor_error(self) -> None:
        err = TimeoutError("timed out after 10s")
        assert isinstance(err, FactorError)


class TestInvalidScoreError:
    def test_is_factor_error(self) -> None:
        err = InvalidScoreError("score 5.0 out of range")
        assert isinstance(err, FactorError)


class TestErrorHierarchy:
    """验证错误层级：捕获 FactorError 应捕获所有子类。"""

    @pytest.mark.parametrize("exc_class", [
        DataUnavailableError,
        ComputationError,
        TimeoutError,
        InvalidScoreError,
    ])
    def test_caught_by_parent(self, exc_class) -> None:
        try:
            raise exc_class("test")
        except FactorError:
            pass  # expected
        else:
            pytest.fail(f"{exc_class.__name__} should be caught by FactorError")
