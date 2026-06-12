# -*- coding: utf-8 -*-
"""
Rug Pull Detector — Phase 2.3

Multi-dimensional rug-pull early warning system.
Detects potential rug-pull risk by combining:
1. Liquidity drain speed (rapid TVL removal)
2. Holder concentration spike (top-10 address % surge)
3. Social silence (project stops communication)
4. Contract risk flags (from security APIs)

Each dimension produces a 0~1 risk score; composite score triggers alerts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk level thresholds
# ---------------------------------------------------------------------------
RISK_HIGH = 0.75
RISK_MEDIUM = 0.45
RISK_LOW = 0.25


@dataclass
class RugRiskSignal:
    """Individual risk dimension signal."""
    dimension: str           # liquidity | holders | social | contract
    score: float             # 0 ~ 1 (higher = more risky)
    severity: str            # low | medium | high | critical
    evidence: str            # human-readable evidence
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RugPullAssessment:
    """Composite rug-pull risk assessment for a token."""
    symbol: str
    chain: str
    contract_address: str
    composite_score: float          # 0 ~ 1
    risk_level: str                 # safe | low | medium | high | critical
    signals: List[RugRiskSignal] = field(default_factory=list)
    recommendation: str = ""        # human-readable recommendation
    timestamp: float = 0.0
    should_block_signal: bool = False  # True if risk is too high for signals

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ---------------------------------------------------------------------------
# Dimension analyzers
# ---------------------------------------------------------------------------
def analyze_liquidity_risk(
    current_tvl: float,
    tvl_24h_ago: float,
    tvl_7d_ago: float,
    liquidity_changes: Optional[List[Dict]] = None,
) -> RugRiskSignal:
    """
    Detect rapid liquidity drain.

    High risk indicators:
    - TVL dropped > 50% in 24h
    - TVL dropped > 70% in 7d
    - Multiple large LP removal events
    """
    score = 0.0
    evidences = []

    if tvl_24h_ago > 0:
        change_24h = (current_tvl - tvl_24h_ago) / tvl_24h_ago
        if change_24h < -0.5:
            score = max(score, 0.9)
            evidences.append(f"TVL下降{abs(change_24h)*100:.0f}%(24h)")
        elif change_24h < -0.3:
            score = max(score, 0.6)
            evidences.append(f"TVL下降{abs(change_24h)*100:.0f}%(24h)")
        elif change_24h < -0.15:
            score = max(score, 0.35)
            evidences.append(f"TVL下降{abs(change_24h)*100:.0f}%(24h)")

    if tvl_7d_ago > 0:
        change_7d = (current_tvl - tvl_7d_ago) / tvl_7d_ago
        if change_7d < -0.7:
            score = max(score, 0.85)
            evidences.append(f"TVL下降{abs(change_7d)*100:.0f}%(7d)")
        elif change_7d < -0.5:
            score = max(score, 0.55)
            evidences.append(f"TVL下降{abs(change_7d)*100:.0f}%(7d)")

    # Check for large LP removal events
    if liquidity_changes:
        large_removals = [
            lc for lc in liquidity_changes
            if lc.get("type") == "remove"
            and float(lc.get("amountUsd", 0)) > 50000
        ]
        if len(large_removals) >= 3:
            score = max(score, 0.7)
            evidences.append(f"{len(large_removals)}笔大额LP撤出")
        elif len(large_removals) >= 1:
            score = max(score, 0.4)
            evidences.append(f"{len(large_removals)}笔大额LP撤出")

    return RugRiskSignal(
        dimension="liquidity",
        score=min(score, 1.0),
        severity=_score_to_severity(score),
        evidence="; ".join(evidences) if evidences else "流动性正常",
        raw_data={
            "current_tvl": current_tvl,
            "tvl_24h_ago": tvl_24h_ago,
            "tvl_7d_ago": tvl_7d_ago,
        },
    )


def analyze_holder_concentration(
    top10_pct: float,
    top10_pct_24h_ago: float,
    total_holders: int,
    holder_changes: Optional[List[Dict]] = None,
) -> RugRiskSignal:
    """
    Detect holder concentration anomalies.

    High risk:
    - Top-10 holders > 80% of supply
    - Top-10 concentration increased > 15% in 24h
    - Total holders declining rapidly
    """
    score = 0.0
    evidences = []

    # Absolute concentration
    if top10_pct > 90:
        score = max(score, 0.85)
        evidences.append(f"Top10持有{top10_pct:.1f}%供应量")
    elif top10_pct > 80:
        score = max(score, 0.6)
        evidences.append(f"Top10持有{top10_pct:.1f}%供应量")
    elif top10_pct > 60:
        score = max(score, 0.3)
        evidences.append(f"Top10持有{top10_pct:.1f}%供应量")

    # Concentration change
    if top10_pct_24h_ago > 0:
        conc_change = top10_pct - top10_pct_24h_ago
        if conc_change > 15:
            score = max(score, 0.8)
            evidences.append(f"Top10集中度24h上升{conc_change:.1f}%")
        elif conc_change > 8:
            score = max(score, 0.5)
            evidences.append(f"Top10集中度24h上升{conc_change:.1f}%")

    # Low holder count
    if total_holders < 50:
        score = max(score, 0.7)
        evidences.append(f"持有者仅{total_holders}人")
    elif total_holders < 200:
        score = max(score, 0.35)
        evidences.append(f"持有者{total_holders}人(偏少)")

    return RugRiskSignal(
        dimension="holders",
        score=min(score, 1.0),
        severity=_score_to_severity(score),
        evidence="; ".join(evidences) if evidences else "持有者分布正常",
        raw_data={
            "top10_pct": top10_pct,
            "total_holders": total_holders,
        },
    )


def analyze_social_risk(
    heat_score: float,
    heat_24h_ago: float,
    last_project_update_hours: Optional[float] = None,
) -> RugRiskSignal:
    """
    Detect social silence / abandonment signals.

    High risk:
    - Social heat dropped > 80% in 24h (abnormal silence)
    - No project updates in > 30 days
    """
    score = 0.0
    evidences = []

    if heat_24h_ago > 0:
        heat_change = (heat_score - heat_24h_ago) / heat_24h_ago
        if heat_change < -0.8:
            score = max(score, 0.65)
            evidences.append(f"社交热度骤降{abs(heat_change)*100:.0f}%")
        elif heat_change < -0.5:
            score = max(score, 0.35)
            evidences.append(f"社交热度下降{abs(heat_change)*100:.0f}%")

    if last_project_update_hours is not None:
        if last_project_update_hours > 720:  # 30 days
            score = max(score, 0.7)
            evidences.append(
                f"项目{last_project_update_hours/24:.0f}天未更新"
            )
        elif last_project_update_hours > 336:  # 14 days
            score = max(score, 0.4)
            evidences.append(
                f"项目{last_project_update_hours/24:.0f}天未更新"
            )

    return RugRiskSignal(
        dimension="social",
        score=min(score, 1.0),
        severity=_score_to_severity(score),
        evidence="; ".join(evidences) if evidences else "社交活跃度正常",
    )


def analyze_contract_risk(
    is_open_source: bool = True,
    has_audit: bool = False,
    has_mint_authority: bool = False,
    has_pause_function: bool = False,
    has_blacklist: bool = False,
    is_honeypot: bool = False,
    risk_labels: Optional[List[str]] = None,
) -> RugRiskSignal:
    """
    Assess contract-level risk.

    High risk:
    - Honeypot detected
    - Mint authority retained
    - Not open-source and no audit
    """
    score = 0.0
    evidences = []

    if is_honeypot:
        score = 1.0
        evidences.append("蜜罐合约检测命中")

    if has_mint_authority:
        score = max(score, 0.7)
        evidences.append("项目方保留铸币权限")

    if has_blacklist:
        score = max(score, 0.5)
        evidences.append("合约含黑名单功能")

    if has_pause_function:
        score = max(score, 0.4)
        evidences.append("合约含暂停交易功能")

    if not is_open_source:
        score = max(score, 0.5)
        evidences.append("合约未开源")

    if not has_audit and not is_open_source:
        score = max(score, 0.6)
        evidences.append("未审计且未开源")

    if risk_labels:
        for label in risk_labels:
            if "rug" in label.lower() or "scam" in label.lower():
                score = max(score, 0.9)
                evidences.append(f"风险标签: {label}")

    return RugRiskSignal(
        dimension="contract",
        score=min(score, 1.0),
        severity=_score_to_severity(score),
        evidence="; ".join(evidences) if evidences else "合约风险正常",
        raw_data={
            "is_open_source": is_open_source,
            "has_audit": has_audit,
            "has_mint_authority": has_mint_authority,
        },
    )


# ---------------------------------------------------------------------------
# Composite assessment
# ---------------------------------------------------------------------------
# Dimension weights for composite score
_DIMENSION_WEIGHTS = {
    "liquidity": 0.35,
    "holders": 0.25,
    "contract": 0.25,
    "social": 0.15,
}


def assess_rug_pull_risk(
    symbol: str,
    chain: str,
    contract_address: str,
    signals: List[RugRiskSignal],
) -> RugPullAssessment:
    """
    Compute composite rug-pull risk from dimension signals.

    Args:
        symbol: Token symbol
        chain: Blockchain name
        contract_address: Token contract address
        signals: List of dimension risk signals

    Returns:
        RugPullAssessment with composite score and recommendation.
    """
    if not signals:
        return RugPullAssessment(
            symbol=symbol,
            chain=chain,
            contract_address=contract_address,
            composite_score=0,
            risk_level="safe",
            recommendation="无风险数据可用",
        )

    # Weighted composite
    weighted_sum = 0.0
    total_weight = 0.0
    for sig in signals:
        w = _DIMENSION_WEIGHTS.get(sig.dimension, 0.1)
        weighted_sum += sig.score * w
        total_weight += w

    composite = weighted_sum / total_weight if total_weight > 0 else 0

    # Check for any critical signal (override)
    has_critical = any(s.score >= 0.9 for s in signals)
    if has_critical:
        composite = max(composite, 0.85)

    # Determine risk level
    if composite >= 0.8:
        risk_level = "critical"
    elif composite >= RISK_HIGH:
        risk_level = "high"
    elif composite >= RISK_MEDIUM:
        risk_level = "medium"
    elif composite >= RISK_LOW:
        risk_level = "low"
    else:
        risk_level = "safe"

    # Build recommendation
    recommendation = _build_recommendation(risk_level, signals)

    # Should we block signal generation?
    should_block = risk_level in ("critical", "high")

    return RugPullAssessment(
        symbol=symbol,
        chain=chain,
        contract_address=contract_address,
        composite_score=round(composite, 4),
        risk_level=risk_level,
        signals=signals,
        recommendation=recommendation,
        should_block_signal=should_block,
    )


def _score_to_severity(score: float) -> str:
    if score >= 0.8:
        return "critical"
    if score >= RISK_HIGH:
        return "high"
    if score >= RISK_MEDIUM:
        return "medium"
    return "low"


def _build_recommendation(
    risk_level: str,
    signals: List[RugRiskSignal],
) -> str:
    if risk_level == "critical":
        return "⚠️ 极高rug pull风险！强烈建议避开此token。已自动暂停信号生成。"
    if risk_level == "high":
        return "🔴 高风险警告：多维度数据异常，不建议交易。已自动暂停信号生成。"
    if risk_level == "medium":
        top_risks = sorted(signals, key=lambda s: s.score, reverse=True)[:2]
        details = "; ".join(s.evidence for s in top_risks if s.evidence)
        return f"🟡 中等风险：{details}。建议谨慎操作，降低仓位。"
    if risk_level == "low":
        return "🟢 低风险：存在轻微风险信号，建议保持关注。"
    return "✅ 风险评估正常。"