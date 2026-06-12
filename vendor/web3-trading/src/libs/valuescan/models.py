# -*- coding: utf-8 -*-
"""ValueScan Pydantic request/response models.

All finite-string fields use StrEnum members; all models inherit
from pydantic.BaseModel with explicit ConfigDict.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from .enums import PriceMarketType


# ---------------------------------------------------------------------------
# Base / shared value objects (frozen)
# ---------------------------------------------------------------------------
class VSBaseModel(BaseModel):
    """Base for immutable value objects.

    Provides automatic camelCase alias generation and coercion of
    empty-string / string-numeric values at the boundary.
    """

    model_config = ConfigDict(
        frozen=True, extra="ignore", populate_by_name=True,
        alias_generator=to_camel,
    )

    @model_validator(mode='before')
    @classmethod
    def _coerce_boundary_values(cls, data: Any) -> Any:
        """Normalise API values at the boundary.

        * ``''`` → ``None`` for Optional[...] fields
        * ``''`` → ``0`` / ``0.0`` for int / float fields
        * non-empty str → int / float for numeric fields
        """
        if not isinstance(data, dict):
            return data
        hints = get_type_hints(cls)
        for field_name, field_type in hints.items():
            keys = {field_name}
            field_info = cls.model_fields.get(field_name)
            if field_info and field_info.alias:
                keys.add(field_info.alias)
            for key in keys:
                raw = data.get(key)
                if raw is None:
                    continue
                if raw == '':
                    if cls._is_optional(field_type):
                        data[key] = None
                    elif field_type is float:
                        data[key] = 0.0
                    elif field_type is int:
                        data[key] = 0
                    # str / bool / other — leave as-is
                    continue
                if isinstance(raw, str) and field_type in (float, int):
                    try:
                        data[field_name] = field_type(raw)
                    except (ValueError, TypeError):
                        pass
        return data

    @staticmethod
    def _is_optional(tp: Any) -> bool:
        """Return True if *tp* is Optional[X] (i.e. Union[X, None])."""
        return get_origin(tp) is Union and type(None) in get_args(tp)


class CoinInfo(VSBaseModel):
    """代币信息（大额交易嵌套对象）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/large
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    coin_key: str = Field(default="", description="币标识（链+合约地址组合）")
    coin_name: str = Field(default="", description="币名")
    symbol: str = Field(default="", description="币标识")
    protocol: str = Field(default="", description="协议")
    contract_address: str = Field(default="", description="合约地址")
    chain_name: str = Field(default="", description="链名")
    icon: str = Field(default="", description="图标 URL")
    price: float = Field(default=0.0, description="价格 (USD)")


class LabelInfo(VSBaseModel):
    """地址/交易所标签信息（大额交易、持仓地址等接口的嵌套对象）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/large, POST /open/v1/chain/trade/token/holdPage
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    label_name: str = Field(default="", description="标签名称")
    icon_url: str = Field(default="", description="图标 URL")
    is_contract: bool = Field(default=False, description="是否为合约地址")
    exchange_symbol: str = Field(default="", description="交易所符号")
    label_type: str = Field(default="", description="标签类型")
    reliability: str = Field(default="", description="可靠性")


class AddressInfo(VSBaseModel):
    """地址信息（大额交易嵌套对象）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/large
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    address: str = Field(default="", description="地址")
    label: Optional[LabelInfo] = Field(default=None, description="地址标签")
    balance: float = Field(default=0.0, description="余额")
    profit: float = Field(default=0.0, description="收益")


class ExchangeInfo(VSBaseModel):
    """交易所信息（大额交易嵌套对象）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/large
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    address: str = Field(default="", description="交易所地址")
    name: str = Field(default="", description="交易所名称")
    icon: str = Field(default="", description="交易所图标")
    label: Optional[LabelInfo] = Field(default=None, description="交易所标签")
    addresses: List[str] = Field(default_factory=list, description="关联地址列表")
    amount: float = Field(default=0.0, description="交易金额")


class ChainAddress(VSBaseModel):
    """链地址信息（代币详情接口嵌套对象）。

    数据来源：
    - 接口路径：POST /open/v1/vs-token/detail
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    chain_name: str = Field(default="", description="链名")
    contract_address: str = Field(default="", description="合约地址")
    coin_key: str = Field(default="", description="代币键（链+合约地址标识）")


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
class TokenSearchRequest(BaseModel):
    """代币搜索请求。

    数据来源：
    - 接口路径：POST /open/v1/vs-token/list
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    search: str = Field(default="", description="搜索关键字（支持模糊匹配，大小写不敏感）")


class TokenInfo(VSBaseModel):
    """代币列表项。

    数据来源：
    - 接口路径：POST /open/v1/vs-token/list
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    id: str = Field(alias="vsTokenId", description="代币 ID（vsTokenId），用于其他接口调用")
    symbol: str = Field(default="", description="代币符号（如 BTC, ETH）")
    name: str = Field(default="", description="代币名称（如 Bitcoin, Ethereum）")


class TokenDetail(VSBaseModel):
    """代币详情。

    数据来源：
    - 接口路径：POST /open/v1/vs-token/detail
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    id: str = Field(alias="vsTokenId", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    chain_addresses: List[ChainAddress] = Field(default_factory=list, description="各链合约地址列表")


# ---------------------------------------------------------------------------
# Coin trade flow (代币流向) — /trade/getCoinTradeFlow
# ---------------------------------------------------------------------------
class CoinTradeFlowItem(VSBaseModel):
    """代币流向数据项（coinTradeFlowDataV1Vos 数组内元素）。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTradeFlow
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    time_range: str = Field(default="", description="时间范围（H1/H2/H4/H24 等）")
    time_particle_enum: int = Field(default=0, description="统计时间粒度枚举值（101/102/104 等）")
    trade_in: float = Field(default=0.0, description="交易流入金额 (USD)")
    trade_out: float = Field(default=0.0, description="交易流出金额 (USD)")
    trade_in_number: float = Field(default=0.0, description="交易流入数量")
    trade_out_number: float = Field(default=0.0, description="交易流出数量")
    trade_inflow: float = Field(default=0.0, description="交易净流入金额 (USD)，正值=流入交易所(利空)，负值=流出交易所(利好)")
    trade_amount: float = Field(default=0.0, description="交易量 (USD)")
    trade_inflow_change: float = Field(default=0.0, description="交易净流入变化率，正值加速流入，负值加速流出")


class CoinTradeFlowData(VSBaseModel):
    """代币流向（链上持仓地址与 CEX 之间的资金流入/流出数据）。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTradeFlow
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    items: List[CoinTradeFlowItem] = Field(
        default_factory=list, alias="coinTradeFlowDataV1Vos",
        description="交易所资金流向数据列表",
    )


# ---------------------------------------------------------------------------
# Fund data — realtime (getCoinTrade) & snapshot (getCoinTradeSnapshot)
# ---------------------------------------------------------------------------
class TradeDataItem(VSBaseModel):
    """实时资金交易数据项（spotGoodsList / contractList 内元素）。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTrade, POST /open/v1/trade/getCoinTradeSnapshot
    - 接口文档：docs/特征分析/资金数据/接口信息/实时资金积累.md, docs/特征分析/资金数据/接口信息/资金快照.md
    """

    time_range: str = Field(default="", description="时间范围")
    time_particle_enum: int = Field(default=0, description="统计时间粒度枚举值")
    trade_inflow: float = Field(default=0.0, description="交易净流入金额 (USD)")
    trade_amount: float = Field(default=0.0, description="交易量 (USD)")
    trade_inflow_change: float = Field(default=0.0, description="交易净流入变化率，当前周期与上个周期的资金对比")
    trade_out: float = Field(default=0.0, description="交易流出金额 (USD)")
    trade_in: float = Field(default=0.0, description="交易流入金额 (USD)")


class FundData(VSBaseModel):
    """实时资金积累 / 资金快照数据。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTrade（实时资金积累）
    - 接口文档：docs/特征分析/资金数据/接口信息/实时资金积累.md
    - 接口路径：POST /open/v1/trade/getCoinTradeSnapshot（资金快照）
    - 接口文档：docs/特征分析/资金数据/接口信息/资金快照.md
    """

    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    has_spot_goods: bool = Field(default=False, description="是否存在现货数据")
    spot_max_inflow: float = Field(default=0.0, description="现货主力资金积累 (USD)，90天内各时间窗口净流入最大值")
    spot_goods_list: List[TradeDataItem] = Field(default_factory=list, description="现货各时间窗口交易数据列表")
    has_contract: bool = Field(default=False, description="是否存在合约数据")
    contract_max_inflow: float = Field(default=0.0, description="合约主力资金积累 (USD)，90天内各时间窗口净流入最大值")
    contract_list: List[TradeDataItem] = Field(default_factory=list, description="合约各时间窗口交易数据列表")


# ---------------------------------------------------------------------------
# Fund market-cap ratio (getCoinTradeInflowMarketCapRatio)
# ---------------------------------------------------------------------------
class FundMarketCapRatioData(VSBaseModel):
    """资金市值比数据（主力资金与市值的比值）。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTradeInflowMarketCapRatio
    - 接口文档：docs/特征分析/资金数据/接口信息/资金市值比.md
    """

    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    market_cap: float = Field(default=0.0, description="市值 (USD)")
    spot_trade_inflow: float = Field(default=0.0, description="现货交易净流入金额 (USD)")
    spot_market_cap_ratio: float = Field(default=0.0, description="现货资金市值比率，反映现货资金流入强度")
    contract_trade_inflow: float = Field(default=0.0, description="合约交易净流入金额 (USD)")
    contract_market_cap_ratio: float = Field(default=0.0, description="合约资金市值比率，反映合约市场资金流入强度")
    total_trade_inflow: float = Field(default=0.0, description="现货+合约交易净流入金额合计 (USD)")
    total_market_cap_ratio: float = Field(default=0.0, description="综合资金市值比（现货+合约），判断整体资金关注度的核心指标")


# ---------------------------------------------------------------------------
# Categories trade data (板块资金) — /trade/categories/getTradeList, CoinTradeList
# ---------------------------------------------------------------------------
class CategoriesTradeDataItem(VSBaseModel):
    """板块资金交易数据项（categoriesTradeDataList 数组内元素）。

    数据来源：
    - 接口路径：POST /open/v1/trade/categories/getTradeList, POST /open/v1/trade/categories/CoinTradeList
    - 接口文档：docs/因子分析/资金数据/接口信息/板块资金列表.md
    """

    time_range: str = Field(default="", description="时间范围（如 m5, m15, H6, D90）")
    time_particle_enum: int = Field(default=0, description="统计时间粒度枚举值")
    trade_inflow: float = Field(default=0.0, description="交易净流入金额 (USD)")


class SectorFundItem(VSBaseModel):
    """板块资金积累数据项（各板块在不同时间窗口下的资金净流入）。

    数据来源：
    - 接口路径：POST /open/v1/trade/categories/getTradeList
    - 接口文档：docs/因子分析/资金数据/接口信息/板块资金列表.md
    """

    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    trade_type: int = Field(default=0, description="交易类型（1=现货, 2=合约）")
    tag: str = Field(default="", description="板块英文标识")
    tags_simplified: str = Field(default="", description="板块中文名称")
    categories_trade_data_list: List[CategoriesTradeDataItem] = Field(
        default_factory=list, description="板块资金数据列表",
    )


class SectorCoinTradeItem(VSBaseModel):
    """板块内代币资金积累数据项（同一板块下各代币的资金净流入排名）。

    数据来源：
    - 接口路径：POST /open/v1/trade/categories/CoinTradeList
    - 接口文档：docs/因子分析/资金数据/接口信息/板块代币资金.md
    """

    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    tag: str = Field(default="", description="板块标签")
    trade_type: int = Field(default=0, description="交易类型（1=现货, 2=合约）")
    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    categories_trade_data_list: List[CategoriesTradeDataItem] = Field(
        default_factory=list, description="板块资金数据列表",
    )


# ---------------------------------------------------------------------------
# Balance trend (余额趋势) — /chain/trade/token/balanceTrend
# ---------------------------------------------------------------------------
class BalanceTrendItem(VSBaseModel):
    """地址持仓余额趋势数据项。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/token/balanceTrend
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    date: int = Field(default=0, description="时间（毫秒时间戳）")
    balance: float = Field(default=0.0, description="地址持仓余额，持续增加表示在积累筹码")
    price: float = Field(default=0.0, description="币价 (USD)")


# ---------------------------------------------------------------------------
# Profit/loss trend (盈亏趋势) — /chain/trade/token/profitLossTrend
# ---------------------------------------------------------------------------
class ProfitLossTrendItem(VSBaseModel):
    """地址盈亏趋势数据项。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/token/profitLossTrend
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    date: int = Field(default=0, description="时间（毫秒时间戳）")
    total: float = Field(default=0.0, description="累计盈亏 (USD)，自持仓以来的总盈亏金额")
    day: float = Field(default=0.0, description="每日盈亏 (USD)，正值盈利负值亏损")
    price: float = Field(default=0.0, description="币价 (USD)")


# ---------------------------------------------------------------------------
# Trade count trend (交易行为趋势) — /chain/trade/token/tradeCountTrend
# ---------------------------------------------------------------------------
class TradeCountTrendItem(VSBaseModel):
    """地址交易行为趋势数据项。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/token/tradeCountTrend
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    date: int = Field(default=0, description="时间（毫秒时间戳）")
    from_count: int = Field(default=0, description="转出次数")
    to_count: int = Field(default=0, description="转入次数")
    from_amount: float = Field(default=0.0, description="转出金额 (USD)")
    to_amount: float = Field(default=0.0, description="转入金额 (USD)")
    price: float = Field(default=0.0, description="币价 (USD)")


# ---------------------------------------------------------------------------
# Large transactions (大额交易) — /chain/trade/large
# ---------------------------------------------------------------------------
class LargeTransactionItem(VSBaseModel):
    """大额交易数据项（20+ 主流公链上的大额转账监控）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/large
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    block_number: int = Field(default=0, description="区块高度")
    trans_hash: str = Field(default="", description="交易 hash")
    from_address: str = Field(default="", description="发出方地址")
    from_exchange_name: str = Field(default="", description="发出方标签")
    to_address: str = Field(default="", description="接收方地址")
    to_exchange_name: str = Field(default="", description="接收方标签")
    amount: float = Field(default=0.0, description="交易金额")
    block_time: int = Field(default=0, description="区块时间（毫秒时间戳）")
    coin_info: Optional[CoinInfo] = Field(default=None, description="代币信息")
    address_info: Optional[AddressInfo] = Field(default=None, description="地址信息")
    exchange_info: Optional[ExchangeInfo] = Field(default=None, description="交易所信息")


# ---------------------------------------------------------------------------
# Hold page (持仓地址) — /chain/trade/token/holdPage
# ---------------------------------------------------------------------------
class HoldPageItem(VSBaseModel):
    """持仓地址数据项（链上持仓地址列表及地址基础信息）。

    数据来源：
    - 接口路径：POST /open/v1/chain/trade/token/holdPage
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    coin_key: str = Field(default="", description="代币键（链+合约地址标识）")
    address: str = Field(default="", description="持仓地址")
    label: Optional[LabelInfo] = Field(default=None, description="地址标签")
    balance: float = Field(default=0.0, description="持仓余额")
    price: float = Field(default=0.0, description="代币价格 (USD)")
    profit: float = Field(default=0.0, description="盈利 (USD)")
    cost: float = Field(default=0.0, description="持仓成本 (USD)")
    pre_cost: float = Field(default=0.0, description="前一次持仓成本 (USD)")
    chain_name: str = Field(default="", description="链名")


# ---------------------------------------------------------------------------
# Price market list (主力行为指标) — /indicator/getPriceMarketList
# ---------------------------------------------------------------------------
class PriceMarketItem(VSBaseModel):
    """主力行为指标数据项（因主力动作可能影响价格趋势的特色指标，仅支持 BTC/ETH）。

    数据来源：
    - 接口路径：POST /open/v1/indicator/getPriceMarketList
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md, docs/特征分析/AI追踪/接口信息/主力行为指标.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    date: int = Field(default=0, description="时间（毫秒时间戳）")
    price_market_type: PriceMarketType = Field(
        default=PriceMarketType.DOWN,
        description="主力行为价格趋势（1=上涨, 2=下跌）",
    )

    @field_validator('price_market_type', mode='before')
    @classmethod
    def _coerce_price_market_type(cls, v):
        """Coerce int priceMarketType to str for PriceMarketType enum."""
        if isinstance(v, int):
            return str(v)
        return v


# ---------------------------------------------------------------------------
# Coin trade cost (主力成本变化趋势) — /trade/getCoinTradeCost
# ---------------------------------------------------------------------------
class CoinTradeCostItem(VSBaseModel):
    """主力成本变化趋势数据项（多链大户实时平均持仓成本）。

    数据来源：
    - 接口路径：POST /open/v1/trade/getCoinTradeCost
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    date: int = Field(default=0, description="时间（毫秒时间戳）")
    price: float = Field(default=0.0, description="当时市场价格 (USD)，与 cost 对比可计算价格偏离度")
    cost: float = Field(default=0.0, description="主力平均持仓成本 (USD)，根据大额交易加权计算")
    balance: float = Field(default=0.0, description="主力持仓余额，持续增加表示主力在吸筹")


# ---------------------------------------------------------------------------
# K-line (K线数据) — /trade/kline/getTradeKLineList
# ---------------------------------------------------------------------------
class KlineItem(VSBaseModel):
    """K线数据项。

    数据来源：
    - 接口路径：POST /open/v1/trade/kline/getTradeKLineList
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    time: int = Field(default=0, description="时间（毫秒时间戳）")
    open: float = Field(default=0.0, description="开盘价 (USD)")
    close: float = Field(default=0.0, description="收盘价 (USD)")
    high: float = Field(default=0.0, description="最高价 (USD)")
    low: float = Field(default=0.0, description="最低价 (USD)")
    volume: float = Field(default=0.0, description="成交量 (USD)")


# ---------------------------------------------------------------------------
# Dense area / support-resistance (支撑阻力位) — /indicator/getDenseAreaList
# ---------------------------------------------------------------------------
class DenseAreaItem(VSBaseModel):
    """AI 智能压力/支撑位数据项（AI 通过多维度数据动态生成的关键价格位）。

    数据来源：
    - 接口路径：POST /open/v1/indicator/getDenseAreaList
    - 接口文档：docs/特征分析/AI追踪/接口信息/压力支撑位.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    price: float = Field(default=0.0, description="关键位价格 (USD)，融合多维度数据计算的压力位或支撑位")
    dense_area: int = Field(default=0, description="压力支撑位标识（1=压力位, 2=支撑位）")


# ---------------------------------------------------------------------------
# Social sentiment (社交情绪) — /social-sentiment/getCoinSocialSentiment
# ---------------------------------------------------------------------------
class SentimentContentItem(VSBaseModel):
    """社媒情绪内容摘要（bullishContents/bearishContents/neutralContents 数组内元素）。

    数据来源：
    - 接口路径：POST /open/v1/social-sentiment/getCoinSocialSentiment
    - 接口文档：docs/特征分析/AI追踪/接口信息/社媒情绪.md
    """

    english: str = Field(default="", description="英文内容摘要，社媒内容 AI 总结")
    update_time: int = Field(default=0, description="内容更新时间（毫秒时间戳）")


class SocialSentimentData(VSBaseModel):
    """社媒情绪数据（单个代币的市场情绪指标，包括看涨/看跌/中立观点比例和内容）。

    数据来源：
    - 接口路径：POST /open/v1/social-sentiment/getCoinSocialSentiment
    - 接口文档：docs/特征分析/AI追踪/接口信息/社媒情绪.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    bullish_ratio: float = Field(default=0.0, description="看涨情绪比例 (0-1)，越接近1越看涨")
    bearish_ratio: float = Field(default=0.0, description="看跌情绪比例 (0-1)，越接近1越看跌")
    neutral_ratio: float = Field(default=0.0, description="中性情绪比例 (0-1)，市场观望情绪占比")
    bullish_contents: List[SentimentContentItem] = Field(default_factory=list, description="看涨内容摘要列表")
    bearish_contents: List[SentimentContentItem] = Field(default_factory=list, description="看跌内容摘要列表")
    neutral_contents: List[SentimentContentItem] = Field(default_factory=list, description="中性内容摘要列表")
    update_time: int = Field(default=0, description="数据更新时间（毫秒时间戳）")


# ---------------------------------------------------------------------------
# AI picks (AI 智能选币) — 出现在机会/风险/资金异动列表中时附加的通用信息
# ---------------------------------------------------------------------------
class AiCoinItem(VSBaseModel):
    """AI 综合选币信息（从机会/风险/资金异动列表中按 vsTokenId 筛选的通用附加信息）。

    数据来源：
    - 接口路径：POST /open/v1/ai/getChanceCoinList, POST /open/v1/ai/getRiskCoinList, POST /open/v1/ai/getFundsCoinList
    - 接口文档：docs/特征分析/AI追踪/接口信息/机会代币列表.md, docs/特征分析/AI追踪/接口信息/风险代币列表.md, docs/特征分析/AI追踪/接口信息/资金异动列表.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="代币符号")
    name: str = Field(default="", description="代币名称")
    reason: str = Field(default="", description="AI 选币理由")
    score: float = Field(default=0.0, description="AI 综合评分 (0-100)")

    # Tier 1 — core
    deviation: Optional[float] = Field(default=None, description="价格偏离度 (%)，(当前价-主力成本)/主力成本*100%，负值=低于成本")
    trade_inflow: Optional[float] = Field(default=None, description="资金净流入 (USD)，正值=主力吸筹")

    # Tier 2 — strong auxiliary
    alpha: Optional[bool] = Field(default=None, description="Alpha 超额收益信号，true 时关注度应更高")
    bullish_ratio: Optional[float] = Field(default=None, description="看涨情绪比例 (0-1)")
    bearish_ratio: Optional[float] = Field(default=None, description="看跌情绪比例 (0-1)")

    # Tier 3 — context
    fomo: Optional[bool] = Field(default=None, description="FOMO 情绪过热，true 时需警惕追高风险")
    fomo_escalation: Optional[bool] = Field(default=None, description="FOMO 进一步升级，true 时风险显著增加")
    grade: Optional[int] = Field(default=None, ge=1, le=3, description="机会等级 (1-3)，等级越高风险越高")
    gains: Optional[float] = Field(default=None, description="推送后最大涨幅 (%)")
    declines: Optional[float] = Field(default=None, description="推送后最大跌幅 (%)")

    # Tier 4 — verification
    active: Optional[int] = Field(default=None, description="24h 活跃地址数，反映市场参与热度")
    newly: Optional[int] = Field(default=None, description="24h 新增地址数，反映新资金流入")
    trade_type: Optional[int] = Field(default=None, description="交易类型（1=现货, 2=合约永续, 3=交割合约）")
    price_market_type: Optional[int] = Field(default=None, description="主力行为指标（1=上涨, 2=下跌）")
    score_change: Optional[float] = Field(default=None, description="AI 评分环比变化")


# ---------------------------------------------------------------------------
# Chance coin list (机会代币列表) — /open/v1/ai/getChanceCoinList
# ---------------------------------------------------------------------------
class ChanceCoinTradeDataItem(VSBaseModel):
    """机会代币交易时间数据项（chanceCoinTradeDataV1Vos 数组内元素）。

    数据来源：
    - 接口路径：POST /open/v1/ai/getChanceCoinList
    - 接口文档：docs/特征分析/AI追踪/接口信息/机会代币列表.md
    """

    time_range: str = Field(default="", description="时间范围标识（如 m15, H4）")
    time_particle_enum: int = Field(default=0, description="时间粒度枚举值")
    trade_inflow: float = Field(default=0.0, description="交易净流入金额 (USD)，正值=资金流入，负值=资金流出")
    trade_amount: float = Field(default=0.0, description="交易总金额 (USD)")


class ChanceCoinItem(VSBaseModel):
    """机会代币（AI 通过多维度数据追踪的具有上涨潜力的代币）。

    数据来源：
    - 接口路径：POST /open/v1/ai/getChanceCoinList
    - 接口文档：docs/特征分析/AI追踪/接口信息/机会代币列表.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="币种符号")
    price: float = Field(default=0.0, description="当前价格 (USD)")
    max_price: float = Field(default=0.0, description="历史最高价格 (USD)")
    min_price: float = Field(default=0.0, description="历史最低价格 (USD)")
    percent_change_1h: float = Field(default=0.0, alias="percentChange1h", description="1小时价格变化百分比")
    percent_change_24h: float = Field(default=0.0, alias="percentChange24h", description="24小时价格变化百分比")
    percent_change_7d: float = Field(default=0.0, alias="percentChange7d", description="7天价格变化百分比")
    percent_change_30d: float = Field(default=0.0, alias="percentChange30d", description="30天价格变化百分比")
    percent_change_60d: float = Field(default=0.0, alias="percentChange60d", description="60天价格变化百分比")
    percent_change_90d: float = Field(default=0.0, alias="percentChange90d", description="90天价格变化百分比")
    cost: float = Field(default=0.0, description="主力成本价格 (USD)，根据大额交易加权计算")
    cost_change: float = Field(default=0.0, description="成本变化率")
    deviation: float = Field(default=0.0, description="价格偏离度 (%)，(当前价-主力成本)/主力成本*100%")
    market_cap: float = Field(default=0.0, description="市值 (USD)")
    market_cap_ranking: int = Field(default=0, description="市值排名")
    circulating_supply: float = Field(default=0.0, description="流通供应量")
    circulation_rate: float = Field(default=0.0, description="流通率 (%)")
    active: int = Field(default=0, description="24h 活跃地址数")
    newly: int = Field(default=0, description="24h 新增地址数")
    trade_type: int = Field(default=0, description="交易类型（1=现货, 2=合约永续, 3=交割合约）")
    chance_coin_trade_data_v1_vos: List[ChanceCoinTradeDataItem] = Field(
        default_factory=list, description="各时间窗口交易数据列表",
    )
    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    push_price: float = Field(default=0.0, description="入场推送价格 (USD)，系统首次推送该机会代币时的价格")
    push_max_price: float = Field(default=0.0, description="推送后最高价 (USD)")
    gains: float = Field(default=0.0, description="推送后最大涨幅 (%)")
    push_min_price: float = Field(default=0.0, description="推送后最低价 (USD)")
    declines: float = Field(default=0.0, description="推送后最大跌幅 (%)")
    score: float = Field(default=0.0, description="AI 综合评分 (0-100)，评分越高上涨潜力越大")
    score_change: float = Field(default=0.0, description="AI 评分环比变化")
    grade: int = Field(default=0, description="机会等级 (1-3)，等级越高风险越高")
    alpha: bool = Field(default=False, description="Alpha 超额收益信号")
    fomo: bool = Field(default=False, description="FOMO 情绪过热，true 时需警惕追高风险")
    fomo_escalation: bool = Field(default=False, description="FOMO 进一步升级，true 时风险显著增加")
    bullish_ratio: float = Field(default=0.0, description="看涨情绪比例 (0-1)")
    bearish_ratio: float = Field(default=0.0, description="看跌情绪比例 (0-1)")


# ---------------------------------------------------------------------------
# Risk coin list (风险代币列表) — /open/v1/ai/getRiskCoinList
# ---------------------------------------------------------------------------
class RiskCoinItem(VSBaseModel):
    """风险代币（AI 通过多维度数据追踪的具有下跌风险趋势的代币）。

    数据来源：
    - 接口路径：POST /open/v1/ai/getRiskCoinList
    - 接口文档：docs/特征分析/AI追踪/接口信息/风险代币列表.md
    """

    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="币种符号")
    price: float = Field(default=0.0, description="当前价格 (USD)")
    max_price: float = Field(default=0.0, description="历史最高价格 (USD)")
    min_price: float = Field(default=0.0, description="历史最低价格 (USD)")
    percent_change_1h: float = Field(default=0.0, alias="percentChange1h", description="1小时价格变化百分比")
    percent_change_24h: float = Field(default=0.0, alias="percentChange24h", description="24小时价格变化百分比")
    percent_change_7d: float = Field(default=0.0, alias="percentChange7d", description="7天价格变化百分比")
    percent_change_30d: float = Field(default=0.0, alias="percentChange30d", description="30天价格变化百分比")
    percent_change_60d: float = Field(default=0.0, alias="percentChange60d", description="60天价格变化百分比")
    percent_change_90d: float = Field(default=0.0, alias="percentChange90d", description="90天价格变化百分比")
    cost: float = Field(default=0.0, description="主力成本价格 (USD)，根据大额交易加权计算")
    cost_change: float = Field(default=0.0, description="成本变化率")
    deviation: float = Field(default=0.0, description="价格偏离度 (%)，正值过大时需警惕回调风险")
    market_cap: float = Field(default=0.0, description="市值 (USD)")
    market_cap_ranking: int = Field(default=0, description="市值排名")
    circulating_supply: float = Field(default=0.0, description="流通供应量")
    circulation_rate: float = Field(default=0.0, description="流通率 (%)")
    active: int = Field(default=0, description="24h 活跃地址数")
    newly: int = Field(default=0, description="24h 新增地址数")
    trade_type: int = Field(default=0, description="交易类型（1=现货, 2=合约永续, 3=交割合约）")
    chance_coin_trade_data_v1_vos: List[ChanceCoinTradeDataItem] = Field(
        default_factory=list, description="各时间窗口交易数据列表",
    )
    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    push_price: float = Field(default=0.0, description="风险推送价格 (USD)，系统首次推送该风险代币时的价格")
    push_max_price: float = Field(default=0.0, description="推送后最高价 (USD)")
    gains: float = Field(default=0.0, description="推送后涨幅 (%)")
    push_min_price: float = Field(default=0.0, description="推送后最低价 (USD)")
    declines: float = Field(default=0.0, description="推送后跌幅 (%)，验证风险预警准确性")
    score: float = Field(default=0.0, description="AI 风险评分 (0-100)，评分越高下跌风险越大")
    bullish_ratio: float = Field(default=0.0, description="看涨情绪比例 (0-1)")
    bearish_ratio: float = Field(default=0.0, description="看跌情绪比例 (0-1)")


# ---------------------------------------------------------------------------
# Funds coin list (资金异动列表) — /open/v1/ai/getFundsCoinList
# ---------------------------------------------------------------------------
class FundsCoinItem(VSBaseModel):
    """资金异动代币（CEX 上现货或合约存在主力资金异动的代币）。

    数据来源：
    - 接口路径：POST /open/v1/ai/getFundsCoinList
    - 接口文档：docs/特征分析/AI追踪/接口信息/资金异动列表.md
    """

    update_time: int = Field(default=0, description="更新时间（毫秒时间戳）")
    trade_type: int = Field(default=0, description="交易类型（1=现货, 2=合约永续, 3=交割合约）")
    vs_token_id: str = Field(default="", description="代币 ID")
    symbol: str = Field(default="", description="币种符号")
    name: str = Field(default="", description="代币名称")
    start_time: int = Field(default=0, description="异动开始时间（毫秒时间戳）")
    end_time: int = Field(default=0, description="异动结束时间（毫秒时间戳）")
    number_24h: int = Field(default=0, alias="number24h", description="24h 内异动次数，次数越多异动越频繁")
    number_not_24h: int = Field(default=0, alias="numberNot24h", description="24h 外异动次数（3个月内），反映趋势行情异动")
    price: float = Field(default=0.0, description="当前价格 (USD)")
    push_price: float = Field(default=0.0, description="异动推送价格 (USD)")
    gains: float = Field(default=0.0, description="推送后涨幅 (%)")
    decline: float = Field(default=0.0, description="推送后跌幅 (%)")
    percent_change_24h: float = Field(default=0.0, alias="percentChange24h", description="24小时价格变化百分比")
    market_cap: float = Field(default=0.0, description="市值 (USD)")
    alpha: bool = Field(default=False, description="Alpha 信号，主力异常活跃或上涨可能性高")
    fomo: bool = Field(default=False, description="FOMO 情绪活跃，上涨趋势可能延续但需注意追高风险")
    fomo_escalation: bool = Field(default=False, description="FOMO 情绪过热加剧，风险显著增加")
    bullish_ratio: float = Field(default=0.0, description="看涨情绪比例 (0-1)")


# ---------------------------------------------------------------------------
# Generic envelope — all VS responses share this shape
# ---------------------------------------------------------------------------
class VSResponse(VSBaseModel):
    """通用 API 响应信封（所有 ValueScan 接口统一返回结构）。

    数据来源：
    - 适用所有接口
    - 接口文档：docs/特征分析/链上数据/ValueScan_链上数据接口详情.md
    """

    code: int = Field(default=0, description="响应码（200=成功）")
    message: str = Field(default="", description="响应消息")
    data: Any = Field(default=None, description="响应数据")
    request_id: str = Field(default="", description="请求追踪 ID")

    model_config = ConfigDict(frozen=False)
