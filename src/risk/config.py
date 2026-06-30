from __future__ import annotations

from decimal import Decimal

from risk.manager import (
    AbnormalCandleRule,
    KillSwitch,
    MaxDrawdownRule,
    MaxPositionRule,
    MaxSlippageRule,
    RiskManager,
)


def default_risk_manager(*, initial_capital: Decimal) -> RiskManager:
    """Five MVP rules from ai-trading, ordered kill-switch first."""
    return RiskManager(
        rules=[
            KillSwitch(),
            MaxPositionRule(max_notional_usd=initial_capital),
            MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")),
            MaxSlippageRule(max_spread_pct=Decimal("0.02")),
            AbnormalCandleRule(max_price_jump_pct=Decimal("0.10")),
        ]
    )


DEFAULT_RULE_IDS = (
    "EMERGENCY_HALT",
    "MAX_POSITION_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MAX_SLIPPAGE_PCT",
    "ABNORMAL_ORDERBOOK",
)
