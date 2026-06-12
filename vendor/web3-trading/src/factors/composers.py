"""CrossFactorComposer — 从因子组合计算高阶信号。

实现 7 个交叉因子，覆盖技术面、资金面、情绪面、合约衍生品四维交叉：
  1. cost_fund_confluence: deviation × sign(tradeInflow)
  2. ai_sentiment_resonance: score × bullishRatio
  3. alpha_fomo_risk: alpha AND fomo
  4. divergence_magnitude: |spot - contract| 当方向不一致时
  5. tech_fund_confluence: trend_strength × deviation (技术-资金共振)
  6. tech_sentiment_divergence: macd_divergence/rsi × sentiment (技术-情绪背离)
  7. crowding_alert: funding_rate_zscore × volume_price_divergence (拥挤度预警)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional


from .enums import MarketType, SignalDirection
from .models import CrossFactorResult, DecisionTrace, EvidenceLink, FactorBundle, FactorResult

logger = logging.getLogger(__name__)


class CrossFactorComposer:
    """从已完成的 FactorBundle 计算结果计算交叉因子信号。

    每个交叉因子将 2+ 个父因子组合成一个高阶信号，
    捕获单个因子中不可见的交互效应。
    """

    async def compose_all(
        self,
        bundle: FactorBundle,
        market_type: Optional[MarketType] = None,
    ) -> List[CrossFactorResult]:
        """对已完成的 bundle 运行所有交叉因子组合器。

        Args:
            bundle: 包含层级分区结果的已完成因子包。
            market_type: 如果设置为单一市场，则跳过需要双市场数据的
                         交叉因子（如 divergence）。
        """
        results_map: Dict[str, FactorResult] = {
            r.factor_name: r for r in bundle.all_results
        }
        cross_results: List[CrossFactorResult] = []

        tasks = [
            self._cost_fund_confluence(results_map),
            self._ai_sentiment_resonance(results_map),
            self._alpha_fomo_risk(results_map),
            self._tech_fund_confluence(results_map),
            self._tech_sentiment_divergence(results_map),
        ]
        # Divergence 需要现货和合约双市场数据 — 仅全市场模式
        if market_type is None:
            tasks.append(self._divergence_magnitude(results_map))
        # Crowding alert 仅合约（依赖 funding_rate_zscore）
        if market_type == MarketType.CONTRACT:
            tasks.append(self._crowding_alert(results_map))

        for task in tasks:
            result = await task
            if result is not None:
                cross_results.append(result)

        return cross_results

    # ------------------------------------------------------------------
    # 交叉因子 #1: deviation × tradeInflow
    # ------------------------------------------------------------------

    async def _cost_fund_confluence(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """deviation × sign(tradeInflow)。

        负偏离（价格 < 成本，看涨）+ 净流出（看涨）= 最强多头。
        """
        dev = results.get("deviation")
        inf = results.get("trade_inflow_change")

        if dev is None or inf is None:
            return None

        dev_score = dev.normalized_score
        inf_score = inf.normalized_score

        strength = abs(dev_score) * abs(inf_score)

        if dev_score > 0.15 and inf_score > 0.15:
            direction = SignalDirection.STRONG_BULLISH
            multiplier = 1.5
            interp = "主力亏损且持续囤币，双重看涨信号——成本-资金合力最强多头确认"
        elif dev_score < -0.15 and inf_score < -0.15:
            direction = SignalDirection.STRONG_BEARISH
            multiplier = 1.5
            interp = "主力盈利且资金流入交易所，双重看跌信号——成本-资金合力最强空头确认"
        elif dev_score > 0 or inf_score > 0:
            direction = SignalDirection.NEUTRAL_BULLISH
            multiplier = 0.5
            interp = "主力成本与资金流向部分看涨"
        elif dev_score < 0 or inf_score < 0:
            direction = SignalDirection.NEUTRAL_BEARISH
            multiplier = 0.5
            interp = "主力成本与资金流向部分看跌"
        else:
            direction = SignalDirection.NEUTRAL
            multiplier = 0.0
            interp = "信号矛盾"

        score = max(-1.0, min(1.0, strength * multiplier))

        return CrossFactorResult(
            cross_name="deviation_x_trade_inflow",
            parent_factors=["deviation", "trade_inflow_change"],
            formula="|deviation_score| × |inflow_score| × 合力系数",
            signal_direction=direction,
            normalized_score=score,
            confidence=0.85 if multiplier == 1.5 else 0.55,
            trace=DecisionTrace(
                factor_name="deviation_x_trade_inflow",
                raw_inputs={"deviation": dev_score, "inflow": inf_score},
                evidence_chain=[EvidenceLink(
                    data_point=f"deviation={dev_score:.3f}, inflow={inf_score:.3f}",
                    interpretation=interp,
                    implication="成本-资金合力是最强策略确认信号之一",
                    confidence=0.85 if multiplier == 1.5 else 0.55,
                )],
                conclusion=f"成本-资金合力: {direction.value}, 强度={score:.3f}",
                suggested_action=(
                    "强烈做多，可重仓介入" if direction == SignalDirection.STRONG_BULLISH
                    else "强烈做空，清仓" if direction == SignalDirection.STRONG_BEARISH
                    else "观望等待方向一致"
                ),
                counter_argument="主力低位补仓可能是降低均价而非看好后市，需结合大盘走势判断",
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #2: score × bullishRatio (AI-情绪共振)
    # ------------------------------------------------------------------

    async def _ai_sentiment_resonance(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """AI 综合评分 × 情绪比例。

        高评分 + 高看涨比例 = 多维度共振（可信赖）。
        高评分 + 低看涨比例 = 背离（可疑）。
        """
        score_r = results.get("score_and_change")
        sent_r = results.get("sentiment_ratio")

        if score_r is None or sent_r is None:
            return None

        s = score_r.normalized_score
        t = sent_r.raw_value  # 净看涨比例

        # 共振: 两者一致 = 放大。不一致 = 衰减。
        if s > 0.1 and t > 0.05:
            resonance = min(1.0, abs(s) + abs(t) * 0.5)
            direction = SignalDirection.BULLISH
            interp = "AI评分与市场情绪共振看涨，信号可靠性高"
        elif s < -0.1 and t < -0.05:
            resonance = -min(1.0, abs(s) + abs(t) * 0.5)
            direction = SignalDirection.BEARISH
            interp = "AI评分与市场情绪共振看跌，信号可靠性高"
        elif s > 0.1 and t < -0.05:
            resonance = abs(s) * 0.3
            direction = SignalDirection.NEUTRAL
            interp = "AI看涨但市场悲观，信号矛盾——谨慎"
        elif s < -0.1 and t > 0.05:
            resonance = -abs(s) * 0.3
            direction = SignalDirection.NEUTRAL
            interp = "AI看跌但市场乐观，信号矛盾——谨慎"
        else:
            resonance = 0.0
            direction = SignalDirection.NEUTRAL
            interp = "信号中性"

        return CrossFactorResult(
            cross_name="score_x_sentiment",
            parent_factors=["score_and_change", "sentiment_ratio"],
            formula="AI评分加权 ± 情绪偏差",
            signal_direction=direction,
            normalized_score=max(-1.0, min(1.0, resonance)),
            confidence=0.70 if abs(resonance) > 0.3 else 0.45,
            trace=DecisionTrace(
                factor_name="score_x_sentiment",
                raw_inputs={"ai_score": s, "net_sentiment": t},
                evidence_chain=[EvidenceLink(
                    data_point=f"AI评分={s:.3f}, 市场情绪={t:.3f}",
                    interpretation=interp,
                    implication=(
                        "多维度共振信号比单维度信号更可靠"
                        if abs(resonance) > 0.3
                        else "信号矛盾时建议降低仓位"
                    ),
                    confidence=0.65,
                )],
                conclusion=f"AI-情绪共振: {direction.value}, 得分={resonance:.3f}",
                suggested_action=(
                    "多维度看涨共振，可积极做多" if direction == SignalDirection.BULLISH
                    else "多维度看跌共振，可做空" if direction == SignalDirection.BEARISH
                    else "观望"
                ),
                counter_argument="AI评分和社媒情绪可能同时受到同一信息源影响而产生虚假共振",
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #3: alpha AND fomo
    # ------------------------------------------------------------------

    async def _alpha_fomo_risk(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """Alpha 信号 + FOMO 指标。

        Alpha=true + FOMO=true = 高波动预警（潜在拉高出货）。
        """
        alpha_r = results.get("alpha")
        fomo_r = results.get("fomo")

        if alpha_r is None or fomo_r is None:
            return None

        alpha_triggered = alpha_r.raw_value > 0.5
        fomo_triggered = fomo_r.raw_value > 0.5

        if alpha_triggered and fomo_triggered:
            score = -0.5
            direction = SignalDirection.BEARISH
            interp = "Alpha异常 + FOMO过热 = 高波动预警，可能为拉高出货"
            action = "强烈建议减仓或设紧止损。"
        elif alpha_triggered and not fomo_triggered:
            score = 0.35
            direction = SignalDirection.NEUTRAL_BULLISH
            interp = "Alpha异常但市场未过热，机会尚在早期"
            action = "可关注，但等待确认信号。"
        elif not alpha_triggered and fomo_triggered:
            score = -0.25
            direction = SignalDirection.NEUTRAL_BEARISH
            interp = "无Alpha但FOMO过热，纯情绪驱动，回调风险"
            action = "注意回调风险。"
        else:
            score = 0.0
            direction = SignalDirection.NEUTRAL
            interp = "无Alpha-FOMO风险信号"
            action = ""

        return CrossFactorResult(
            cross_name="alpha_x_fomo",
            parent_factors=["alpha", "fomo"],
            formula="alpha AND fomo → 波动预警",
            signal_direction=direction,
            normalized_score=score,
            confidence=0.75 if (alpha_triggered and fomo_triggered) else 0.50,
            trace=DecisionTrace(
                factor_name="alpha_x_fomo",
                raw_inputs={"alpha": alpha_triggered, "fomo": fomo_triggered},
                evidence_chain=[EvidenceLink(
                    data_point=f"Alpha={alpha_triggered}, FOMO={fomo_triggered}",
                    interpretation=interp,
                    implication="Alpha+FOMO同时触发是典型的顶部预警组合",
                    confidence=0.75 if (alpha_triggered and fomo_triggered) else 0.45,
                )],
                conclusion=f"Alpha-FOMO风险: {direction.value}",
                suggested_action=action,
                counter_argument="牛市中FOMO可能持续较长时间，过早离场可能错失收益",
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #5: trend_strength × deviation (技术-资金共振)
    # ------------------------------------------------------------------

    async def _tech_fund_confluence(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """趋势强度 × 主力成本偏离。

        技术面趋势与资金面主力成本是两个完全正交的数据源。
        两者共振/背离时提供单个因子无法捕获的增量信息。

        四种象限：
          - 上涨趋势 + 主力盈利 → 趋势健康，顺势做多
          - 上涨趋势 + 主力亏损 → 主力近成本线有抛压，警惕反转
          - 下跌趋势 + 主力盈利 → 主力派发中，下跌加速
          - 下跌趋势 + 主力亏损 → 主力被套可能护盘，关注反转
        """
        trend = results.get("trend_strength")
        dev = results.get("deviation")

        if trend is None or dev is None:
            return None

        t_score = trend.normalized_score   # >0.3 强多头趋势, <-0.3 强空头趋势
        d_score = dev.normalized_score     # >0 whales underwater (bullish), <0 whales profiting (bearish)

        if t_score > 0.3 and d_score < -0.2:
            # 上涨趋势 + 主力盈利 → 趋势有主力资金支撑，最健康的多头组合
            strength = min(1.0, abs(t_score) + abs(d_score) * 0.5)
            direction = SignalDirection.STRONG_BULLISH
            interp = "上涨趋势确认，主力已盈利但未出货，资金面支撑趋势延续"
            action = "顺势做多，设移动止盈跟踪趋势。"
            counter = "主力可能在拉高过程中逐步出货，需监控OI变化确认"

        elif t_score > 0.3 and d_score > 0.2:
            # 上涨趋势 + 主力亏损 → 主力接近成本线，解套抛压
            strength = -0.45
            direction = SignalDirection.BEARISH
            interp = "上涨趋势中但主力仍亏损，价格接近主力成本线易遇抛压"
            action = "多单注意止盈，主力解套时可能出现抛售潮。"
            counter = "若主力看好后市可能加仓而非抛售"

        elif t_score < -0.3 and d_score < -0.2:
            # 下跌趋势 + 主力盈利 → 主力正在派发，最危险的空头组合
            strength = -min(1.0, abs(t_score) + abs(d_score) * 0.5)
            direction = SignalDirection.STRONG_BEARISH
            interp = "下跌趋势确认，主力已获利且可能正在派发，下跌动能充足"
            action = "空仓或做空，不宜抄底。"
            counter = "若主力已完成派发，下跌空间可能有限"

        elif t_score < -0.3 and d_score > 0.2:
            # 下跌趋势 + 主力亏损 → 主力被套，可能护盘/补仓
            strength = 0.45
            direction = SignalDirection.BULLISH
            interp = "下跌趋势中主力被套，主力有护盘或补仓动机，关注反转"
            action = "关注底部信号，若出现放量阳线可轻仓试多。"
            counter = "主力可能已止损离场而非护盘，需结合链上余额数据确认"

        else:
            # 趋势不明确或偏离度中性 — 减小幅度保持方向，不做符号反转
            if abs(t_score) > abs(d_score):
                strength = t_score * 0.3
            else:
                strength = d_score * 0.15  # 保持 deviation 原方向，仅降低权重
            if abs(strength) < 0.1:
                direction = SignalDirection.NEUTRAL
            elif strength > 0:
                direction = SignalDirection.NEUTRAL_BULLISH
            else:
                direction = SignalDirection.NEUTRAL_BEARISH
            interp = "技术趋势与资金面信号较弱，无明确共振"
            action = "观望等待明确信号。"
            counter = ""

        score = max(-1.0, min(1.0, strength))
        conf = 0.80 if abs(score) > 0.4 else 0.55 if abs(score) > 0.2 else 0.35

        return CrossFactorResult(
            cross_name="tech_fund_confluence",
            parent_factors=["trend_strength", "deviation"],
            formula="trend_strength_score ⊗ deviation_score → 四象限共振/背离判定",
            signal_direction=direction,
            normalized_score=score,
            confidence=conf,
            trace=DecisionTrace(
                factor_name="tech_fund_confluence",
                raw_inputs={"trend_strength": t_score, "deviation": d_score},
                evidence_chain=[EvidenceLink(
                    data_point=f"趋势={t_score:+.3f}, 主力成本偏离={d_score:+.3f}",
                    interpretation=interp,
                    implication="技术面与资金面共振是最可靠的方向确认信号之一",
                    confidence=conf,
                )],
                conclusion=f"技术-资金共振: {direction.value}, 得分={score:.3f}",
                suggested_action=action,
                counter_argument=counter,
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #6: macd/rsi × sentiment (技术-情绪背离)
    # ------------------------------------------------------------------

    async def _tech_sentiment_divergence(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """技术反转信号 × 市场情绪。

        核心逻辑：当技术指标发出反转信号但市场情绪仍在另一边时，
        是典型的大众犯错时刻——"别人恐惧我贪婪，别人贪婪我恐惧"。

        优先使用 MACD 背离（信号最强），RSI 极端值作为备选。
        """
        macd = results.get("macd_divergence")
        rsi = results.get("rsi_extreme")
        sent = results.get("sentiment_ratio")

        if sent is None:
            return None
        if macd is None and rsi is None:
            return None

        # 技术方向: >0 bullish reversal, <0 bearish reversal, 0 neutral
        tech_bullish = False
        tech_bearish = False
        tech_strength = 0.0

        if macd is not None and macd.raw_value != 0:
            if macd.raw_value > 0:
                tech_bullish = True
                tech_strength = 0.85
            else:
                tech_bearish = True
                tech_strength = -0.85
        elif rsi is not None and abs(rsi.normalized_score) > 0.2:
            if rsi.normalized_score > 0:
                tech_bullish = True
                tech_strength = rsi.normalized_score * 0.8
            else:
                tech_bearish = True
                tech_strength = rsi.normalized_score * 0.8

        if not tech_bullish and not tech_bearish:
            return None

        # sentiment.raw_value = net_bullish: >0 市场乐观, <0 市场悲观
        crowd_bullish = sent.raw_value > 0.1   # 大众看涨
        crowd_bearish = sent.raw_value < -0.1  # 大众看跌

        if tech_bullish and crowd_bearish:
            # 技术看涨 + 大众恐慌 → 经典抄底信号
            strength = min(1.0, abs(tech_strength) * 1.2 + abs(sent.raw_value) * 0.5)
            direction = SignalDirection.STRONG_BULLISH
            interp = "技术反转看涨信号 + 市场恐慌情绪 = 经典底部特征，别人恐惧我贪婪"
            action = "积极做多，设置宽止损以防趋势延续。"
            conf = 0.82
        elif tech_bearish and crowd_bullish:
            # 技术看跌 + 大众贪婪 → 经典逃顶信号
            strength = -min(1.0, abs(tech_strength) * 1.2 + abs(sent.raw_value) * 0.5)
            direction = SignalDirection.STRONG_BEARISH
            interp = "技术反转看跌信号 + 市场狂热情绪 = 经典顶部特征，别人贪婪我恐惧"
            action = "减仓或做空，大众情绪极端时反转往往剧烈。"
            conf = 0.82
        elif tech_bullish and crowd_bullish:
            # 技术看涨 + 大众也在看涨 → 信号已被定价，强度衰减
            strength = abs(tech_strength) * 0.25
            direction = SignalDirection.NEUTRAL_BULLISH
            interp = "技术看涨但市场已普遍乐观，缺乏情绪面增量，上涨空间可能有限"
            action = "谨慎做多，降低仓位。"
            conf = 0.40
        elif tech_bearish and crowd_bearish:
            # 技术看跌 + 大众也在看跌 → 恐慌可能已过度
            strength = -abs(tech_strength) * 0.25
            direction = SignalDirection.NEUTRAL_BEARISH
            interp = "技术看跌但市场已普遍恐慌，可能已接近底部"
            action = "已持空单可继续持有但设止盈，不宜追空。"
            conf = 0.40
        else:
            # 大众情绪中性
            strength = tech_strength * 0.5
            if strength > 0.1:
                direction = SignalDirection.BULLISH
            elif strength < -0.1:
                direction = SignalDirection.BEARISH
            else:
                direction = SignalDirection.NEUTRAL
            interp = "技术信号存在但市场情绪中性，信号可靠性一般"
            action = "可轻仓跟随技术方向。"
            conf = 0.50

        score = max(-1.0, min(1.0, strength))

        return CrossFactorResult(
            cross_name="tech_sentiment_divergence",
            parent_factors=["macd_divergence", "rsi_extreme", "sentiment_ratio"],
            formula="技术反转方向 ⊗ 大众情绪方向 → 背离=强化, 一致=衰减",
            signal_direction=direction,
            normalized_score=score,
            confidence=conf,
            trace=DecisionTrace(
                factor_name="tech_sentiment_divergence",
                raw_inputs={
                    "macd_div": macd.raw_value if macd else 0,
                    "rsi": rsi.normalized_score if rsi else 0,
                    "sentiment_net": sent.raw_value,
                },
                evidence_chain=[EvidenceLink(
                    data_point=f"技术={'看涨' if tech_bullish else '看跌'}, "
                               f"大众={'乐观' if crowd_bullish else '悲观' if crowd_bearish else '中性'}",
                    interpretation=interp,
                    implication=(
                        "技术信号与大众情绪背离时是最佳入场时机"
                        if (tech_bullish and crowd_bearish) or (tech_bearish and crowd_bullish)
                        else "技术信号与大众情绪一致时缺乏反向安全边际"
                    ),
                    confidence=conf,
                )],
                conclusion=f"技术-情绪背离: {direction.value}, 得分={score:.3f}",
                suggested_action=action,
                counter_argument="极端情绪可能持续更久，反转信号需要价格确认后再入场",
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #7: funding_rate × volume_price (拥挤度预警, 仅合约)
    # ------------------------------------------------------------------

    async def _crowding_alert(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """资金费率极端值 × 量价关系 → 拥挤度预警。

        资金费率极端 = 单边头寸过度拥挤。
        量价背离 = 趋势动能衰竭。

        两者同时触发时，反转概率显著升高：
          - 极高资金费率（多头拥挤）+ 量价背离（量能不跟）= 多头踩踏风险
          - 极低资金费率（空头拥挤）+ 量价背离 = 逼空风险
        """
        fr = results.get("funding_rate_zscore")
        vp = results.get("volume_price_divergence")

        if fr is None or vp is None:
            return None

        fr_z = fr.raw_value          # zscore: >2.5 extreme long crowding, <-2.5 extreme short crowding
        vp_corr = vp.raw_value       # price-volume correlation: >0 confirming, <0 diverging

        fr_extreme_long = fr_z > 2.0    # 多头过度拥挤 → 回调风险
        fr_extreme_short = fr_z < -2.0  # 空头过度拥挤 → 逼空风险
        vp_diverging = vp_corr < -0.3   # 量价显著背离

        if fr_extreme_long and vp_diverging:
            # 多头拥挤 + 量能背离 → 强做空信号
            strength = -min(1.0, abs(fr_z) / 4.0 + abs(vp_corr) * 0.8)
            direction = SignalDirection.STRONG_BEARISH
            interp = (
                f"资金费率极端正偏离(Z={fr_z:+.1f}) + 量价背离(corr={vp_corr:+.2f}) = "
                "多头极度拥挤且动能衰竭，踩踏风险极高"
            )
            action = "强烈建议做空或多单全平，拥挤头寸解除时下跌迅猛。"
            conf = 0.80
        elif fr_extreme_long and not vp_diverging:
            # 多头拥挤但量能确认 → 趋势可能继续但有回调压力
            strength = -0.35
            direction = SignalDirection.BEARISH
            interp = f"资金费率偏高(Z={fr_z:+.1f})但量价尚未背离，多头拥挤有回调压力但趋势未破"
            action = "多单设紧止损，不宜加仓。"
            conf = 0.55
        elif fr_extreme_short and vp_diverging:
            # 空头拥挤 + 量能背离 → 强做多信号
            strength = min(1.0, abs(fr_z) / 4.0 + abs(vp_corr) * 0.8)
            direction = SignalDirection.STRONG_BULLISH
            interp = (
                f"资金费率极端负偏离(Z={fr_z:+.1f}) + 量价背离(corr={vp_corr:+.2f}) = "
                "空头极度拥挤且动能衰竭，逼空风险极高"
            )
            action = "强烈建议做多或空单全平，逼空行情上涨迅猛。"
            conf = 0.80
        elif fr_extreme_short and not vp_diverging:
            # 空头拥挤但量能确认 → 继续偏空但有逼空风险
            strength = 0.35
            direction = SignalDirection.BULLISH
            interp = f"资金费率偏低(Z={fr_z:+.1f})但量价尚未背离，空头拥挤有逼空风险但趋势未破"
            action = "空单设紧止损，不宜加仓。"
            conf = 0.55
        elif abs(fr_z) > 1.5:
            # 资金费率偏极端但量价无明显背离 → 弱信号
            strength = -0.2 if fr_z > 0 else 0.2  # fr_z>0 → bearish, fr_z<0 → bullish
            direction = SignalDirection.NEUTRAL_BEARISH if fr_z > 0 else SignalDirection.NEUTRAL_BULLISH
            interp = f"资金费率{('偏高' if fr_z > 0 else '偏低')}(Z={fr_z:+.1f})，但量价无背离，轻度预警"
            action = "关注但不急于操作。"
            conf = 0.40
        else:
            return None  # 无拥挤信号

        score = max(-1.0, min(1.0, strength))

        return CrossFactorResult(
            cross_name="crowding_alert",
            parent_factors=["funding_rate_zscore", "volume_price_divergence"],
            formula="funding_extreme × volume_divergence → 拥挤踩踏/逼空预警",
            signal_direction=direction,
            normalized_score=score,
            confidence=conf,
            trace=DecisionTrace(
                factor_name="crowding_alert",
                raw_inputs={"funding_zscore": fr_z, "vp_correlation": vp_corr},
                evidence_chain=[EvidenceLink(
                    data_point=f"资金费率Z={fr_z:+.2f}, 量价相关={vp_corr:+.2f}",
                    interpretation=interp,
                    implication="资金费率极端+量价背离是最高胜率的反转信号组合之一",
                    confidence=conf,
                )],
                conclusion=f"拥挤度预警: {direction.value}, 得分={score:.3f}",
                suggested_action=action,
                counter_argument="趋势市中资金费率可能长期处于极端值，仅依赖此信号可能过早离场",
            ),
        )

    # ------------------------------------------------------------------
    # 交叉因子 #4: 现货-合约背离强度
    # ------------------------------------------------------------------

    async def _divergence_magnitude(
        self, results: Dict[str, FactorResult]
    ) -> Optional[CrossFactorResult]:
        """从 spot_contract_div 因子获取背离强度。

        该因子已计算背离值；此处对其进行放大以用于聚合评分。
        """
        div_r = results.get("spot_contract_divergence")
        if div_r is None or abs(div_r.normalized_score) < 0.1:
            return None

        # 放大强背离信号
        amplified = div_r.normalized_score * 1.3
        clamped = max(-1.0, min(1.0, amplified))

        return CrossFactorResult(
            cross_name="spot_contract_divergence_amplified",
            parent_factors=["spot_contract_divergence"],
            formula="divergence_score × 1.3 放大",
            signal_direction=div_r.signal_direction,
            normalized_score=clamped,
            confidence=div_r.confidence,
            trace=DecisionTrace(
                factor_name="spot_contract_divergence_amplified",
                raw_inputs={"original_score": div_r.normalized_score},
                evidence_chain=[EvidenceLink(
                    data_point=f"背离度原始得分: {div_r.normalized_score:.3f}",
                    interpretation="现货合约背离信号经放大",
                    implication="背离信号通常领先价格1-3天",
                    confidence=div_r.confidence,
                )],
                conclusion=f"背离信号放大: {div_r.signal_direction.value}, 得分={clamped:.3f}",
                suggested_action="背离加剧时降低仓位观望",
                counter_argument="背离可能是暂时性套利行为",
            ),
        )
