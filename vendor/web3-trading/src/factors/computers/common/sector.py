"""板块因子 — 公共因子。

- 板块内代币资金排名：代币在所属板块中的资金排名，识别板块龙头
- 板块资金净流入排名：跨板块资金轮动趋势
- 板块资金轮动速度：资金在板块间的轮动快慢，判断市场阶段
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


def _sum_inflow(records) -> float:
    """汇总 categories_trade_data_list 中所有时间粒度的 trade_inflow。"""
    if not records:
        return 0.0
    return sum(
        float(getattr(r, "trade_inflow", 0) or 0)
        for r in records
    )


def _primary_inflow(records) -> float:
    """取 H24 粒度的 trade_inflow，若无则取总和。"""
    if not records:
        return 0.0
    for r in records:
        tpe = getattr(r, "time_particle_enum", 0) or 0
        if tpe == 124:
            return float(getattr(r, "trade_inflow", 0) or 0)
    return _sum_inflow(records)


class CoinSectorRankComputer(BaseFactorComputer):
    """板块内代币资金排名 — 识别板块龙头。"""

    factor_name: ClassVar[str] = "coin_sector_rank"
    category: ClassVar[FactorCategory] = FactorCategory.SECTOR
    display_name: ClassVar[str] = "板块内代币资金排名"
    description: ClassVar[str] = "代币在所属板块内的资金流向排名。"
    requires_data: ClassVar[List[str]] = []

    def check_prerequisites(self, ctx: FactorContext) -> bool:
        return "sector_coin_list" in ctx.data and bool(ctx.data.get("sector_coin_list"))

    async def compute(self, ctx: FactorContext) -> FactorResult:
        coin_list = ctx.data.get("sector_coin_list") or []

        if not coin_list:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "无板块代币排名数据。"),
            )

        sorted_coins = sorted(
            coin_list,
            key=lambda c: _primary_inflow(
                getattr(c, "categories_trade_data_list", []) or []
            ),
            reverse=True,
        )

        token_rank = None
        token_inflow = 0.0
        for i, coin in enumerate(sorted_coins):
            cid = str(getattr(coin, "vs_token_id", ""))
            if cid == ctx.vs_token_id:
                token_rank = i + 1
                token_inflow = _primary_inflow(
                    getattr(coin, "categories_trade_data_list", []) or []
                )
                break

        if token_rank is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.3,
                data_completeness=0.5, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "该代币未出现在板块排名中。"),
            )

        total_coins = len(sorted_coins)
        rank_pct = token_rank / max(1, total_coins)

        rank_desc = "龙头地位" if token_rank == 1 else ("中游水平" if rank_pct < 0.5 else "尾部")
        evidence = [self._evidence(
            data_point=f"板块内排名: #{token_rank}/{total_coins}，净流入: {token_inflow:,.0f} USD",
            interpretation=f"板块内资金排名第{token_rank}，{rank_desc}",
            implication="板块龙头，资金共识最强，板块行情中首选配置" if token_rank == 1
            else ("资金关注度高" if rank_pct < 0.3 else "资金关注度偏低"),
            confidence=0.75 if token_rank <= 3 else 0.50,
        )]

        if token_rank == 1:
            clamped = 0.6
            direction = SignalDirection.BULLISH
            action = "板块龙头，优先配置。"
        elif rank_pct < 0.3:
            clamped = 0.3
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "板块内资金前排，可关注。"
        elif rank_pct > 0.7:
            clamped = -0.3
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "板块内资金落后，谨慎配置。"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(token_rank),
            confidence=0.70 if token_rank <= 3 else 0.45,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"rank": token_rank, "total": total_coins, "inflow": token_inflow},
                evidence,
                f"板块内排名: {token_rank}/{total_coins} ({rank_pct:.0%})。",
                action,
                limitations=["仅比较同板块代币，跨板块不可比"],
            ),
        )


class SectorRankComputer(BaseFactorComputer):
    """板块资金净流入排名 — 跨板块资金轮动。"""

    factor_name: ClassVar[str] = "sector_rank"
    category: ClassVar[FactorCategory] = FactorCategory.SECTOR
    display_name: ClassVar[str] = "板块资金净流入排名"
    description: ClassVar[str] = "跨板块类别的资金流向排名。"
    requires_data: ClassVar[List[str]] = []

    def check_prerequisites(self, ctx: FactorContext) -> bool:
        return "sector_fund_list" in ctx.data and bool(ctx.data.get("sector_fund_list"))

    async def compute(self, ctx: FactorContext) -> FactorResult:
        sector_list = ctx.data.get("sector_fund_list") or []

        if not sector_list:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "无板块资金数据。"),
            )

        sorted_sectors = sorted(
            sector_list,
            key=lambda s: _sum_inflow(
                getattr(s, "categories_trade_data_list", []) or []
            ),
            reverse=True,
        )

        evidence = []
        for i, sector in enumerate(sorted_sectors[:3]):
            name = getattr(sector, "tags_simplified", "") or getattr(sector, "tag", f"板块{i + 1}")
            inflow = _sum_inflow(getattr(sector, "categories_trade_data_list", []) or [])
            evidence.append(self._evidence(
                data_point=f"#{i + 1} {name}: {inflow:,.0f} USD",
                interpretation=f"板块资金排名第{i + 1}",
                implication="资金主线板块" if i == 0 else "资金关注板块",
                confidence=0.70,
            ))

        total_inflow = sum(
            _sum_inflow(getattr(s, "categories_trade_data_list", []) or [])
            for s in sector_list
        )

        # 板块排名越靠前，信号越偏多
        top_inflow = _sum_inflow(
            getattr(sorted_sectors[0], "categories_trade_data_list", []) or []
        ) if sorted_sectors else 0.0
        dominance = top_inflow / (abs(total_inflow) + 1) if top_inflow > 0 else 0.0

        if total_inflow > 0 and dominance > 0.5:
            clamped = 0.20
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "头部板块资金高度集中，龙头效应强。"
        elif total_inflow > 0:
            clamped = 0.10
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "整体板块资金偏多。"
        elif total_inflow < 0:
            clamped = -0.10
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "整体板块资金偏空。"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=total_inflow,
            confidence=0.60 if sector_list else 0.0,
            data_freshness_ms=0,
            data_completeness=1.0 if sector_list else 0.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"sector_count": len(sector_list), "total_inflow": total_inflow,
                 "dominance": dominance},
                evidence,
                f"板块资金排名: 共{len(sector_list)}个板块，总净流入{total_inflow:,.0f} USD。",
                action,
                limitations=["板块分类可能不精确", "排名为快照，可能变化快"],
            ),
        )


class RotationSpeedComputer(BaseFactorComputer):
    """板块资金轮动速度 — 判断市场阶段。"""

    factor_name: ClassVar[str] = "rotation_speed"
    category: ClassVar[FactorCategory] = FactorCategory.SECTOR
    display_name: ClassVar[str] = "板块资金轮动速度"
    description: ClassVar[str] = "板块间资金轮动速度。"
    requires_data: ClassVar[List[str]] = []

    def check_prerequisites(self, ctx: FactorContext) -> bool:
        return "sector_fund_list" in ctx.data and bool(ctx.data.get("sector_fund_list"))

    async def compute(self, ctx: FactorContext) -> FactorResult:
        sector_list = ctx.data.get("sector_fund_list") or []

        if not sector_list:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无板块轮动数据。"),
            )

        inflows = [
            _sum_inflow(getattr(s, "categories_trade_data_list", []) or [])
            for s in sector_list
        ]
        if not inflows:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "板块资金数据为空。"),
            )

        mean_inflow = sum(inflows) / len(inflows)
        variance = sum((v - mean_inflow) ** 2 for v in inflows) / len(inflows)
        std = variance ** 0.5
        cv = std / (abs(mean_inflow) + 1) if mean_inflow != 0 else std

        evidence = [self._evidence(
            data_point=f"板块资金离散度: CV={cv:.3f}, std={std:,.0f}",
            interpretation="资金集中在少数板块，轮动慢" if cv > 2.0
            else ("资金分布较均匀，轮动快" if cv < 0.5 else "资金轮动适中"),
            implication="资金有沉淀，趋势可持续→延长持仓" if cv > 2.0
            else ("资金无沉淀，短期博弈为主→缩短持仓周期" if cv < 0.5 else ""),
            confidence=0.55,
        )]

        clamped = max(-0.3, min(0.3, (cv - 1.0) * 0.15))

        if clamped > 0.1:
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "资金沉淀，可延长持仓。"
        elif clamped < -0.1:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "资金快进快出，缩短持仓。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=std,
            confidence=0.45,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"sector_count": len(sector_list), "inflow_std": std, "cv": cv},
                evidence,
                f"板块轮动速度: CV={cv:.3f}。",
                action,
                limitations=["轮动速度需要多时间点对比才能精确计算"],
            ),
        )
