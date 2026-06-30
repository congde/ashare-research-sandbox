from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RiskFinding:
    rule_id: str
    severity: str
    message: str
    source: str
    phase: str = "post_backtest"
    count: int = 1


def _severity_for_rule(rule_id: str) -> str:
    if rule_id == "EMERGENCY_HALT":
        return "critical"
    if rule_id in {"MAX_DAILY_LOSS_PCT", "MAX_POSITION_PCT", "MAX_SLIPPAGE_PCT", "ABNORMAL_ORDERBOOK"}:
        return "warning"
    return "info"


def _runtime_findings(rejections: list[dict]) -> list[RiskFinding]:
    if not rejections:
        return []

    counts = Counter(item["rule_id"] for item in rejections)
    sample_by_rule: dict[str, dict] = {}
    for item in rejections:
        sample_by_rule.setdefault(item["rule_id"], item)

    findings: list[RiskFinding] = []
    for rule_id, count in sorted(counts.items()):
        sample = sample_by_rule[rule_id]
        suffix = f"（共拦截 {count} 笔）" if count > 1 else ""
        findings.append(
            RiskFinding(
                rule_id=rule_id,
                severity=_severity_for_rule(rule_id),
                message=f"{sample['reason']}{suffix}",
                source="ai-trading/runtime",
                phase="pre_trade",
                count=count,
            )
        )
    return findings


def evaluate_backtest_risk(
    backtest: dict,
    *,
    max_drawdown_pct: float = 15.0,
) -> list[dict]:
    """Merge runtime RiskManager blocks with post-backtest review gates."""
    findings: list[RiskFinding] = []
    findings.extend(_runtime_findings(backtest.get("risk_rejections") or []))

    metrics = backtest["metrics"]
    drawdown = metrics["maximum_drawdown_pct"]
    runtime_rule_ids = {item.rule_id for item in findings}

    if (
        drawdown < 0
        and abs(drawdown) >= max_drawdown_pct
        and "MAX_DAILY_LOSS_PCT" not in runtime_rule_ids
    ):
        findings.append(
            RiskFinding(
                rule_id="MAX_DAILY_LOSS_PCT",
                severity="warning",
                message=(
                    f"最大回撤 {drawdown}% 超过模拟阈值 {max_drawdown_pct}% 。"
                    "若接入实时引擎，MaxDrawdownRule 会阻止继续开新仓。"
                ),
                source="ai-trading/post_backtest",
                phase="post_backtest",
            )
        )

    if metrics["strategy_return_pct"] < metrics["buy_hold_return_pct"]:
        findings.append(
            RiskFinding(
                rule_id="STRATEGY_UNDERPERFORM",
                severity="info",
                message="策略收益低于买入持有，说明参数或规则可能不适合该样本区间。",
                source="ai-trading/post_backtest",
                phase="post_backtest",
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
                source="ai-trading/post_backtest",
                phase="post_backtest",
            )
        )

    return [asdict(item) for item in findings]
