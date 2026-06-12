from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RiskFinding:
    rule_id: str
    severity: str
    message: str
    source: str


def evaluate_backtest_risk(
    backtest: dict,
    *,
    max_drawdown_pct: float = 15.0,
) -> list[dict]:
    """Post-backtest simulation gates adapted from ai-trading risk rules."""
    metrics = backtest["metrics"]
    findings: list[RiskFinding] = []
    drawdown = metrics["maximum_drawdown_pct"]

    if drawdown < 0 and abs(drawdown) >= max_drawdown_pct:
        findings.append(
            RiskFinding(
                rule_id="MAX_DAILY_LOSS_PCT",
                severity="warning",
                message=(
                    f"最大回撤 {drawdown}% 超过模拟阈值 {max_drawdown_pct}% 。"
                    "若接入实时引擎，MaxDrawdownRule 会阻止继续开新仓。"
                ),
                source="ai-trading",
            )
        )

    if metrics["strategy_return_pct"] < metrics["buy_hold_return_pct"]:
        findings.append(
            RiskFinding(
                rule_id="STRATEGY_UNDERPERFORM",
                severity="info",
                message="策略收益低于买入持有，说明参数或规则可能不适合该样本区间。",
                source="ai-trading",
            )
        )

    sample_days = len(backtest["curve"])
    if metrics["trade_count"] > sample_days // 2:
        findings.append(
            RiskFinding(
                rule_id="EXCESSIVE_TURNOVER",
                severity="warning",
                message=(
                    f"交易动作 {metrics['trade_count']} 次，接近样本长度 "
                    f"{sample_days} 天，可能存在过度换手。"
                ),
                source="ai-trading",
            )
        )

    return [asdict(item) for item in findings]
