# -*- coding: utf-8 -*-
"""数据录制器 — 运行因子管线并将快照写入本地 JSONL。"""

import asyncio
import time
import uuid
from typing import Any

import numpy as np
from pydantic import BaseModel

from factors.backtest.models import FactorSnapshot, SourceData
from factors.local_store import append_factor_snapshot, append_source_data
from factors.pipeline import FactorPipeline


def _sanitize_for_mongo(obj: Any) -> Any:
    """递归转换对象中的 numpy array 为 list，确保可存入 MongoDB。"""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, BaseModel):
        return _sanitize_for_mongo(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _sanitize_for_mongo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_mongo(v) for v in obj]
    return obj


class DataRecorder:
    """录制因子快照到本地文件。

    record_snapshot 一次写入两类本地数据，以 factor_snapshots 为关联中心：
      - factor_snapshots: 因子结果 + quality_report_id + source_data_id
      - source_data:      原始 API 数据
      - data_quality_reports: 管线内部自动写入（通过 FactorPipeline）

    查询路径：
      factor_snapshots.quality_report_id → data/data_quality_reports/quality_*.jsonl
      factor_snapshots.source_data_id    → data/factors/source_data/source_*.jsonl

    用法::

        from factors import FactorPipeline, PipelineConfig
        from libs.valuescan import ValueScanClient
        from libs.kucoin_openapi import KuCoinClient
        from factors.backtest.recorder import DataRecorder

        client = ValueScanClient.from_env()
        kucoin = KuCoinClient.from_env()
        pipeline = FactorPipeline(client, PipelineConfig.for_spot(), kucoin=kucoin)
        recorder = DataRecorder(pipeline, kucoin)

        snap = await recorder.record_snapshot("BTC", "4427")
    """

    def __init__(self, pipeline: FactorPipeline, kucoin=None) -> None:
        self._pipeline = pipeline
        self._kucoin = kucoin

    async def record_snapshot(self, symbol: str, vs_token_id: str) -> FactorSnapshot:
        """运行一次完整因子计算管线，存储快照 + 源数据。

        quality_report_id 由管线内部生成（_fetch_context → _persist_quality_report）。
        source_data_id 在本地预生成。
        """
        snap_id = uuid.uuid4().hex
        source_data_id = uuid.uuid4().hex
        bundle = await self._pipeline.compute_all(symbol)
        now_ms = int(time.time() * 1000)

        quality_report_id = bundle.quality_report_id

        snapshot = FactorSnapshot(
            id=snap_id,
            symbol=symbol,
            vs_token_id=vs_token_id,
            market_type=self._pipeline.config.market_type,
            computed_at_ms=now_ms,
            quality_report_id=quality_report_id,
            source_data_id=source_data_id,
            factor_results=[r.model_dump() for r in bundle.all_results],
            cross_factors=[c.model_dump() for c in bundle.cross_factors],
            aggregate_score=bundle.aggregate_score,
            overall_completeness=bundle.overall_completeness,
            errors=bundle.errors,
            pipeline_duration_ms=0,
        )

        raw_context = bundle.context.data if bundle.context else {}
        source_data = SourceData(
            id=source_data_id,
            symbol=symbol,
            vs_token_id=vs_token_id,
            market_type=snapshot.market_type,
            fetched_at_ms=now_ms,
            data=_sanitize_for_mongo(raw_context),
        )

        await asyncio.gather(
            append_factor_snapshot(snapshot.model_dump()),
            append_source_data(source_data.model_dump()),
        )
        return snapshot

    async def record_batch(
        self,
        symbols: list[str],
        vs_token_ids: dict[str, str],
        max_concurrent: int = 5,
    ) -> list[FactorSnapshot]:
        """批量录制多个代币的快照。"""
        sem = asyncio.Semaphore(max_concurrent)

        async def _record_one(sym: str) -> FactorSnapshot:
            async with sem:
                return await self.record_snapshot(sym, vs_token_ids[sym])

        results = await asyncio.gather(
            *[_record_one(s) for s in symbols],
            return_exceptions=True,
        )
        snapshots: list[FactorSnapshot] = []
        for outcome in results:
            if isinstance(outcome, FactorSnapshot):
                snapshots.append(outcome)
        return snapshots
