"""FactorPipeline — 编排数据拉取、因子计算和结果组装。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

import numpy as np

from libs.kucoin_openapi import KuCoinClient
from libs.valuescan.client import ValueScanClient
from libs.valuescan.models import CoinTradeCostItem

from .config import PipelineConfig
from .context import FactorContext
from .enums import FactorTier, MarketType
from .fetch.circuit_breaker import CircuitBreaker, CircuitOpenError
from .fetch.health import HealthTracker
from .fetch.retry import RetryConfig, with_retry
from .models import (
    DerivativesSnapshot,
    FactorBundle,
    FactorResult,
    FundingRateData,
    KlineFrame,
    KlineSnapshot,
    OpenInterestData,
)
from .registry import FactorRegistry
from .validation import QualityChecker, store_quality_report

logger = logging.getLogger(__name__)

# KuCoin K-line granularity → factor timeframe key mapping
_KL_KEY_MAP = {
    "15min": "15m", "1hour": "1h", "4hour": "4h", "1day": "1d",
    "15": "15m", "60": "1h", "240": "4h", "1440": "1d",
}


class FactorPipeline:
    """编排代币的因子计算。

    职责：
      1. 一次性并发拉取代币的所有 ValueScan 原始数据。
      2. 从拉取的数据构建 FactorContext。
      3. 将上下文路由到 profiled 因子计算器（并发）。
      4. 将当前 RankingProfile 的 rank/weight/tier 注入结果。
      5. 将校准置信度（confidence_overrides）注入结果。
      6. 对完成的结果执行交叉因子组合。
      7. 组装带层级分区的 FactorBundle。

    用法::

        from libs.valuescan import ValueScanClient
        from factors import FactorPipeline, PipelineConfig

        client = ValueScanClient.from_env()
        pipeline = FactorPipeline(client, PipelineConfig.for_spot())

        bundle = await pipeline.compute_all("BTC")
        print(f"Aggregate: {bundle.aggregate_score:.3f}")
    """

    def __init__(
        self,
        client: ValueScanClient,
        config: Optional[PipelineConfig] = None,
        *,
        kucoin: Optional[KuCoinClient] = None,
        confidence_overrides: Optional[dict[str, float]] = None,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        health_tracker: Optional[HealthTracker] = None,
        quality_checker: Optional[QualityChecker] = None,
    ) -> None:
        self._client = client
        self._config = config or PipelineConfig()
        self._registry = FactorRegistry()
        self._kucoin = kucoin
        self._confidence_overrides = confidence_overrides or {}
        self._retry_config = retry_config or RetryConfig()
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._health = health_tracker or HealthTracker()
        self._quality_checker = quality_checker or QualityChecker()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def compute_all(
        self,
        symbol_or_id: str | int,
        *,
        include_cross_factors: bool = True,
    ) -> FactorBundle:
        """计算代币的所有 profiled 因子。

        Args:
            symbol_or_id: 代币符号（如 "BTC"）或 vs_token_id。
            include_cross_factors: 是否执行交叉因子组合。

        Returns:
            包含层级分区结果的完整 FactorBundle。
        """
        profile = self._config.ranking_profile

        ctx = await self._fetch_context(symbol_or_id)
        if ctx is None:
            return FactorBundle(
                vs_token_id="",
                errors=[f"Failed to resolve token: {symbol_or_id}"],
                context=None,
            )

        # 市场状态自适应权重
        if self._config.adaptive_weighting_enabled and ctx.data.get("kline") is not None:
            profile = self._resolve_adaptive_profile(profile, ctx)

        computers = self._registry.get_computers_by_profile(profile)
        if not computers:
            logger.warning("No computers matched profile %s.", profile.profile_id)

        results: List[FactorResult] = []
        errors: List[str] = []

        # 阶段 1: 并发计算所有因子
        semaphore = asyncio.Semaphore(self._config.max_concurrent_factors)

        async def _compute_one(computer) -> Optional[FactorResult]:
            async with semaphore:
                try:
                    result = await asyncio.wait_for(
                        computer.compute_if_available(ctx),
                        timeout=self._config.single_factor_timeout_s,
                    )
                    return result
                except asyncio.TimeoutError:
                    logger.warning("Factor %s timed out.", computer.factor_name)
                    return None
                except Exception:
                    logger.error(
                        "Factor %s failed.", computer.factor_name, exc_info=True
                    )
                    return None

        raw_results = await asyncio.gather(
            *[_compute_one(c) for c in computers],
            return_exceptions=True,
        )

        for i, outcome in enumerate(raw_results):
            if isinstance(outcome, Exception):
                errors.append(f"{computers[i].factor_name}: {outcome}")
            elif outcome is not None:
                results.append(outcome)

        # 阶段 2: 从 profile 注入 rank/weight/tier 和校准置信度
        results = self._inject_profile_metadata(results, profile, self._confidence_overrides)

        # 阶段 3: 组装 bundle
        bundle = self._assemble_bundle(ctx, results, errors)

        # 阶段 4: 交叉因子组合
        if include_cross_factors and bundle.tier1_results:
            try:
                from .composers import CrossFactorComposer

                composer = CrossFactorComposer()
                cross_results = await composer.compose_all(
                    bundle, market_type=profile.market_type,
                )
                bundle = bundle.model_copy(
                    update={"cross_factors": list(bundle.cross_factors) + cross_results},
                )
            except Exception:
                logger.warning("Cross-factor composition failed.", exc_info=True)

        return bundle

    async def compute_single(
        self,
        symbol_or_id: str | int,
        factor_name: str,
    ) -> Optional[FactorResult]:
        """计算单个命名因子。"""
        computer = self._registry.get_computer(factor_name)
        if computer is None:
            logger.error("Unknown factor: %s", factor_name)
            return None
        ctx = await self._fetch_context(symbol_or_id)
        if ctx is None:
            return None
        result = await computer.compute_if_available(ctx)
        if result is not None:
            result = self._inject_single_metadata(result)
        return result

    async def compute_batch(
        self,
        symbols: List[str],
        *,
        max_concurrency: Optional[int] = None,
    ) -> List[FactorBundle]:
        """并发控制下计算多个代币的因子。"""
        limit = max_concurrency or self._config.max_concurrent_tokens
        semaphore = asyncio.Semaphore(limit)

        async def _bounded(symbol: str) -> FactorBundle:
            async with semaphore:
                return await self.compute_all(symbol)

        return await asyncio.gather(*[_bounded(s) for s in symbols])

    # ------------------------------------------------------------------
    # Profile 元数据注入
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_profile_metadata(
        results: List[FactorResult],
        profile,
        confidence_overrides: Optional[dict[str, float]] = None,
    ) -> List[FactorResult]:
        """将 RankingProfile 中的 rank、weight、tier 和校准后的 confidence 注入结果。"""
        updated: List[FactorResult] = []
        overrides = confidence_overrides or {}
        for r in results:
            entry = profile.get_entry(r.factor_name)
            updates: dict = {}
            if entry is not None:
                updates.update({
                    "factor_index": entry.rank,
                    "factor_tier": entry.tier,
                    "weight": entry.weight,
                })
            if r.factor_name in overrides:
                updates["confidence"] = overrides[r.factor_name]
            if updates:
                r = r.model_copy(update=updates)
            updated.append(r)
        return updated

    def _inject_single_metadata(self, result: FactorResult) -> FactorResult:
        """将 profile 元数据和校准置信度注入单个结果。"""
        profile = self._config.ranking_profile
        entry = profile.get_entry(result.factor_name)
        updates: dict = {}
        if entry is not None:
            updates.update({
                "factor_index": entry.rank,
                "factor_tier": entry.tier,
                "weight": entry.weight,
            })
        if result.factor_name in self._confidence_overrides:
            updates["confidence"] = self._confidence_overrides[result.factor_name]
        if updates:
            return result.model_copy(update=updates)
        return result

    # ------------------------------------------------------------------
    # 自适应权重
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_adaptive_profile(base_profile, ctx) -> "RankingProfile":
        """根据当前市场状态合成自适应权重 profile。"""
        from factors.analysis.adaptive_selector import AdaptiveProfileSelector, ProfileComposer
        from factors.analysis.market_state import MarketStateDetector

        kline = ctx.data.get("kline")
        if kline is None or kline.is_empty:
            return base_profile

        selector = AdaptiveProfileSelector(base_profile)
        state_result = MarketStateDetector.detect(kline)
        state_profiles = selector.get_all_relevant_profiles(state_result)
        return ProfileComposer.compose(base_profile, state_result, state_profiles)

    # ------------------------------------------------------------------
    # 数据拉取
    # ------------------------------------------------------------------

    async def _fetch_context(
        self, symbol_or_id: str | int,
    ) -> Optional[FactorContext]:
        """拉取代币的所有 ValueScan 原始数据并构建 FactorContext。"""""
        if isinstance(symbol_or_id, str) and not symbol_or_id.isdigit():
            try:
                vs_token_id, coin_key = await self._client.resolve_symbol(symbol_or_id)
            except Exception as exc:
                logger.warning(
                    "ValueScan resolve_symbol failed for %s: %s",
                    symbol_or_id,
                    exc,
                )
                return None
            symbol = symbol_or_id.upper()
        else:
            raw_id = int(symbol_or_id) if not isinstance(symbol_or_id, str) else int(symbol_or_id)
            vs_token_id = str(raw_id)
            try:
                coin_key = await self._client.get_coin_key(vs_token_id)
            except Exception as exc:
                logger.warning(
                    "ValueScan get_coin_key failed for %s: %s",
                    vs_token_id,
                    exc,
                )
                coin_key = ""
            try:
                detail = await self._client.get_token_detail(vs_token_id)
            except Exception as exc:
                logger.warning(
                    "ValueScan get_token_detail failed for %s: %s",
                    vs_token_id,
                    exc,
                )
                detail = None
            symbol = detail.symbol if detail else vs_token_id

        if vs_token_id is None:
            return None
        vs_token_id = str(vs_token_id)

        fetched_at_ms = int(time.time() * 1000)
        data: Dict = {}

        async def _fetch(key: str, coro_factory):
            try:
                async def _attempt():
                    return await with_retry(coro_factory, self._retry_config, label=key)

                data[key] = await self._circuit_breaker.call(_attempt, key=key)
                self._health.record(key, success=True)
            except CircuitOpenError:
                logger.warning("Circuit OPEN for '%s' — skipping fetch.", key)
                data[key] = None
            except Exception:
                logger.debug("Failed to fetch %s for %s.", key, symbol, exc_info=True)
                data[key] = None
                self._health.record(key, success=False)

        tasks = [
            ("realtime_fund", lambda: self._client.get_realtime_fund(vs_token_id)),
            ("token_flow", lambda: self._client.get_token_flow(vs_token_id)),
            ("fund_snapshot", lambda: self._client.get_fund_snapshot(
                vs_token_id,
                date_ms=int(time.time() * 1000) - 7 * 86_400_000,
            )),
            ("market_cap_ratio", lambda: self._client.get_fund_market_cap_ratio(vs_token_id)),
            ("whale_cost", lambda: self._client.get_whale_cost(vs_token_id)),
            ("social_sentiment", lambda: self._client.get_social_sentiment(vs_token_id)),
            ("price_indicators", lambda: self._client.get_price_indicators(vs_token_id)),
        ]

        if coin_key:
            tasks.extend([
                ("large_transactions", lambda: self._client.get_large_transactions(vs_token_id)),
                ("holder_list", lambda: self._client.get_holder_list(vs_token_id)),
            ])

        # K-line + 衍生品数据（通过 KuCoin 拉取）
        if self._kucoin is not None:
            market = self._config.ranking_profile.market_type
            tasks.extend([
                ("kline", lambda: self._fetch_kline_data(symbol, market)),
            ])
            if market == MarketType.CONTRACT:
                tasks.append(("derivatives", lambda: self._fetch_derivatives_data(symbol)))
        else:
            logger.info("KuCoin client not configured — K-line and derivatives factors will be skipped for %s.", symbol)

        await asyncio.gather(*[_fetch(key, factory) for key, factory in tasks])

        # 将衍生品快照的字段展开到 data（因子计算器按 requires_data key 查找）
        deriv_raw = data.pop("derivatives", None)
        if isinstance(deriv_raw, DerivativesSnapshot):
            if deriv_raw.funding_rate is not None:
                data["funding_rate"] = deriv_raw.funding_rate
            if deriv_raw.open_interest is not None:
                data["open_interest"] = deriv_raw.open_interest

        # AI 数据（带重试+熔断）
        for ai_key, fetch_fn in [
            ("ai_chance", self._client.get_chance_coin_list),
            ("ai_risk", self._client.get_risk_coin_list),
            ("ai_funds", self._client.get_funds_coin_list),
        ]:
            try:
                async def _ai_fetch():
                    coin_list = await fetch_fn()
                    return next((c for c in coin_list if c.vs_token_id == vs_token_id), None)

                data[ai_key] = await self._circuit_breaker.call(
                    lambda: with_retry(_ai_fetch, self._retry_config, label=ai_key),
                    key=ai_key,
                )
                self._health.record(ai_key, success=True)
            except CircuitOpenError:
                logger.warning("Circuit OPEN for '%s' — skipping AI fetch.", ai_key)
                data[ai_key] = None
            except Exception:
                logger.debug("AI %s fetch failed for %s.", ai_key, symbol, exc_info=True)
                data[ai_key] = None
                self._health.record(ai_key, success=False)

        # ── 板块数据 ─────────────────────────────────────────────
        trade_type = 1 if self._config.ranking_profile.market_type == MarketType.SPOT else 2
        try:
            async def _sector_fetch():
                return await self._client.get_sector_fund_list(trade_type)

            sector_fund_list = await self._circuit_breaker.call(
                lambda: with_retry(_sector_fetch, self._retry_config, label="sector_fund"),
                key="sector_fund",
            )
            data["sector_fund_list"] = sector_fund_list
            self._health.record("sector_fund", success=True)

            tags = [s.tag for s in sector_fund_list if s.tag]
            if tags:
                coin_results = await asyncio.gather(
                    *[self._client.get_sector_coin_trade_list(tag, trade_type) for tag in tags],
                    return_exceptions=True,
                )
                all_coins: list = []
                for result in coin_results:
                    if not isinstance(result, Exception):
                        all_coins.extend(result)
                data["sector_coin_list"] = all_coins
            else:
                data["sector_coin_list"] = []
        except CircuitOpenError:
            logger.warning("Circuit OPEN for sector data — skipping.")
            data["sector_fund_list"] = []
            data["sector_coin_list"] = []
        except Exception:
            logger.debug("Sector fetch failed for %s.", symbol, exc_info=True)
            data["sector_fund_list"] = []
            data["sector_coin_list"] = []
            self._health.record("sector_fund", success=False)

        # ── 数据质量校验 ──────────────────────────────────────────
        quality_report = self._quality_checker.check(data, fetched_at_ms)
        health_snapshot = {
            k: {"status": h.status, "success_rate": h.success_rate}
            for k, h in self._health.snapshot().items()
        }
        quality_report_id = await self._persist_quality_report(
            quality_report,
            symbol=symbol,
            vs_token_id=vs_token_id,
            market_type=self._config.ranking_profile.market_type.value,
            data_health=health_snapshot,
        )

        rt = data.get("realtime_fund")
        has_spot = bool(rt.spot_goods_list) if rt else False
        has_contract = bool(rt.contract_list) if rt else False
        current_price = self._extract_price(data.get("whale_cost"))

        return FactorContext(
            vs_token_id=vs_token_id,
            symbol=symbol,
            coin_key=coin_key,
            fetched_at_ms=fetched_at_ms,
            data=data,
            has_spot=has_spot,
            has_contract=has_contract,
            current_price=current_price,
            market_type=self._config.ranking_profile.market_type,
            data_health=health_snapshot,
            data_quality_report=quality_report,
            quality_report_id=quality_report_id or "",
        )

    @staticmethod
    def _extract_price(whale_costs: Optional[List[CoinTradeCostItem]]) -> float:
        """从鲸鱼成本数据中提取最新价格。"""
        try:
            return float(whale_costs[-1].price)
        except (TypeError, ValueError, IndexError):
            pass
        return 0.0

    @staticmethod
    async def _persist_quality_report(
        quality_report,
        *,
        symbol: str = "",
        vs_token_id: str = "",
        market_type: str = "spot",
        data_health: Optional[dict] = None,
    ) -> Optional[str]:
        """将质量报告异步写入本地 JSONL，返回记录 ID（失败时返回 None）。"""
        try:
            return await store_quality_report(
                quality_report,
                symbol=symbol,
                vs_token_id=vs_token_id,
                market_type=market_type,
                data_health=data_health,
            )
        except Exception:
            logger.debug("Quality report persistence skipped.", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # K-line / derivatives 数据拉取
    # ------------------------------------------------------------------

    @staticmethod
    def _to_futures_symbol(base: str) -> str:
        """将基础币种转为 KuCoin 合约符号（如 BTC→XBTUSDTM, ETH→ETHUSDTM）。"""
        upper = base.upper()
        if upper == "BTC":
            return "XBTUSDTM"
        return f"{upper}USDTM"

    async def _fetch_kline_data(self, symbol: str, market_type: MarketType) -> KlineSnapshot:
        """拉取多周期 K 线并转为结构化快照。"""
        frames: Dict[str, KlineFrame] = {}

        try:
            if market_type == MarketType.SPOT:
                raw = await self._kucoin.get_multi_tf_kline(f"{symbol}-USDT")
            else:
                raw = await self._kucoin.get_futures_multi_tf_kline(self._to_futures_symbol(symbol))
        except Exception:
            logger.debug("Failed to fetch K-line for %s.", symbol, exc_info=True)
            return KlineSnapshot()

        for raw_key, candles in raw.items():
            key = _KL_KEY_MAP.get(raw_key, raw_key)
            if not candles:
                continue
            frames[key] = KlineFrame(
                close=np.array([c.close for c in candles], dtype=np.float64),
                high=np.array([c.high for c in candles], dtype=np.float64),
                low=np.array([c.low for c in candles], dtype=np.float64),
                volume=np.array([c.volume for c in candles], dtype=np.float64),
            )

        return KlineSnapshot(
            tf_15m=frames.get("15m"),
            tf_1h=frames.get("1h"),
            tf_4h=frames.get("4h"),
            tf_1d=frames.get("1d"),
        )

    async def _fetch_derivatives_data(self, symbol: str) -> DerivativesSnapshot:
        """拉取合约衍生品数据（资金费率历史 + 当前持仓量）。"""
        futures_sym = self._to_futures_symbol(symbol)
        fr_data: Optional[FundingRateData] = None
        oi_data: Optional[OpenInterestData] = None

        try:
            now_ms = int(time.time() * 1000)
            items = await self._kucoin.get_funding_rate_history(
                futures_sym,
                start_at=now_ms - 14 * 86_400_000,
                end_at=now_ms,
            )
            values = [item.funding_rate for item in items]
            if values:
                fr_data = FundingRateData(values=values)
        except Exception:
            logger.debug("Failed to fetch funding rate for %s.", symbol, exc_info=True)

        try:
            stats = await self._kucoin.get_open_interest(futures_sym)
            if stats is not None:
                oi_data = OpenInterestData(values=[float(stats.open_interest)])
        except Exception:
            logger.debug("Failed to fetch OI for %s.", symbol, exc_info=True)

        return DerivativesSnapshot(funding_rate=fr_data, open_interest=oi_data)

    @staticmethod
    def _assemble_bundle(
        ctx: FactorContext,
        results: List[FactorResult],
        errors: List[str],
    ) -> FactorBundle:
        """按层级分区结果并组装 bundle。"""
        tier_map: Dict[FactorTier, List[FactorResult]] = {t: [] for t in FactorTier}
        for r in results:
            tier_map[r.factor_tier].append(r)

        total = len(results) + len(errors)
        completeness = len(results) / total if total > 0 else 0.0

        return FactorBundle(
            quality_report_id=ctx.quality_report_id,
            vs_token_id=ctx.vs_token_id,
            symbol=ctx.symbol,
            coin_key=ctx.coin_key,
            computed_at_ms=ctx.fetched_at_ms,
            context=ctx,
            tier1_results=tier_map[FactorTier.TIER_1],
            tier2_results=tier_map[FactorTier.TIER_2],
            tier3_results=tier_map[FactorTier.TIER_3],
            tier4_results=tier_map[FactorTier.TIER_4],
            tier5_results=tier_map[FactorTier.TIER_5],
            overall_completeness=completeness,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # 自省
    # ------------------------------------------------------------------

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def registry(self) -> FactorRegistry:
        return self._registry
