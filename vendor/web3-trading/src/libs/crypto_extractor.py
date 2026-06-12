# -*- coding: utf-8 -*-
"""
@Time    :   2025/12/15 16:00:00
@Description: 从用户查询和Agent回复中提取加密货币/币种名称
"""

import re
import json
import logging
import os
import random
from typing import List, Set, Optional, Dict, Any
from dataclasses import dataclass

from openai import AsyncOpenAI

from mcp.mcp_http_client import mcp_client

logger = logging.getLogger(__name__)


@dataclass
class ExtractedCrypto:
    """提取到的加密货币信息"""
    symbol: str  # 币种符号，如 BTC
    name: Optional[str] = None  # 币种全名，如 Bitcoin
    trading_pair: Optional[str] = None  # 交易对，如 BTC-USDT


class CryptoExtractor:
    """加密货币名称提取器"""

    def __init__(self):
        # 加载提取币种的prompt
        self._extract_prompt = self._load_extract_prompt()

        # 主流加密货币符号映射 (符号: 全名)
        self.crypto_symbols = {
            # 主流币种
            'KCS': 'KuCoin Token',
            'BTC': 'Bitcoin',
            'ETH': 'Ethereum',
            # 'USDT': 'Tether',
            # 'USDC': 'USD Coin',
            'BNB': 'Binance Coin',
            'XRP': 'Ripple',
            'RLUSD': 'Ripple USD',
            'ADA': 'Cardano',
            'SOL': 'Solana',
            'DOGE': 'Dogecoin',
            'DOT': 'Polkadot',
            'AVAX': 'Avalanche',
            'SHIB': 'Shiba Inu',
            'MATIC': 'Polygon',
            'POL': 'POL (ex-MATIC)',
            'LTC': 'Litecoin',
            'LINK': 'Chainlink',
            'UNI': 'Uniswap',
            'ATOM': 'Cosmos',
            'XLM': 'Stellar',
            'VET': 'VeChain',
            'TRX': 'TRON',
            'ETC': 'Ethereum Classic',
            'FIL': 'Filecoin',
            'THETA': 'Theta Network',
            'ALGO': 'Algorand',
            'QNT': 'Quant',
            'XMR': 'Monero',
            'ICP': 'Internet Computer',
            'ONDO': 'Ondo',
            'NEAR': 'NEAR Protocol',
            'XTZ': 'Tezos',
            'GRT': 'The Graph',
            'SAND': 'The Sandbox',
            'MANA': 'Decentraland',
            'AXS': 'Axie Infinity',
            'ENJ': 'Enjin Coin',
            'CHZ': 'Chiliz',
            'FLOW': 'Flow',
            'AAVE': 'Aave',
            'CAKE': 'PancakeSwap',
            'KSM': 'Kusama',
            'RUNE': 'THORChain',
            'CRV': 'Curve DAO Token',
            'COMP': 'Compound',
            'YFI': 'yearn.finance',
            'SUSHI': 'SushiSwap',
            'ALPHA': 'Alpha Finance',
            '1INCH': '1inch',
            'SNX': 'Synthetix',
            'MKR': 'Maker',
            'ZEC': 'Zcash',
            'DASH': 'Dash',
            'QTUM': 'Qtum',
            'ZIL': 'Zilliqa',
            'BAT': 'Basic Attention Token',
            'OMG': 'OMG Network',
            'LRC': 'Loopring',
            'STORJ': 'Storj',
            'BAND': 'Band Protocol',
            'REN': 'Ren',
            'KNC': 'Kyber Network',
            'ZRX': '0x',
            'REP': 'Augur',
            'KAVA': 'Kava',
            'HBAR': 'Hedera',
            'ICX': 'ICON',
            'ONT': 'Ontology',
            'TFUEL': 'Theta Fuel',
            'HOT': 'Holo',
            'CELR': 'Celer Network',
            'FTT': 'FTX Token',
            'IOST': 'IOST',
            'IOTA': 'IOTA',
            'NANO': 'Nano',
            'XEM': 'NEM',
            'WAVES': 'Waves',
            'LSK': 'Lisk',
            'STEEM': 'Steem',
            'DGB': 'DigiByte',
            'SIA': 'Siacoin',
            'DENT': 'Dent',
            'POLY': 'Polymath',
            'FUN': 'FunFair',
            'MAID': 'MaidSafeCoin',
            'STRAT': 'Stratis',
            'ARK': 'Ark',
            'GAS': 'Gas',
            'KMD': 'Komodo',
            'LOOM': 'Loom Network',
            'PIVX': 'PIVX',
            'SYS': 'Syscoin',
            'VIA': 'Viacoin',
            'BLK': 'BlackCoin',
            'EMC': 'Emercoin',
            'EXP': 'Expanse',
            'FAIR': 'FairCoin',
            'GAME': 'GameCredits',
            'GRC': 'Gridcoin',
            'HUC': 'HunterCoin',
            'IOC': 'I/O Coin',
            'LBC': 'LBRY Credits',
            'MONA': 'MonaCoin',
            'NEOS': 'NeosCoin',
            'NLG': 'Gulden',
            'NXT': 'Nxt',
            'POT': 'PotCoin',
            'PPC': 'Peercoin',
            'RDD': 'ReddCoin',
            'SBD': 'Steem Dollars',
            'UBQ': 'Ubiq',
            'VTC': 'Vertcoin',
            'XCP': 'Counterparty',
            'BSV': 'Bitcoin SV',
            'BCH': 'Bitcoin Cash',
            'EOS': 'EOS',
            'TRX': 'TRON',
            'XLM': 'Stellar',
            'LEO': 'UNUS SED LEO',
            'CRO': 'Cronos',
            'DAI': 'Dai',
            'NEO': 'NEO',
            'MIOTA': 'IOTA',
            'XEMv': 'NEM',
            'BUSD': 'Binance USD',
            'HT': 'Huobi Token',
            'CDAI': 'Compound Dai',
            'HEGIC': 'Hegic',
            'UMA': 'UMA',
            'BAL': 'Balancer',
            'CRV': 'Curve DAO Token',
            'REN': 'Ren',
            'LEND': 'Aave',
            'YFI': 'yearn.finance',
            'AMPL': 'Ampleforth',
            'KNC': 'Kyber Network Crystal v2',
            'BNT': 'Bancor',
            'MLN': 'Enzyme',
            'ANT': 'Aragon',
            'MANA': 'Decentraland',
            'ENJ': 'Enjin Coin',
            'SAND': 'The Sandbox',
            'GALA': 'Gala',
            'AMP': 'Amp',
            'ANKR': 'Ankr',
            'AUDIO': 'Audius',
            'API3': 'API3',
            'BADGER': 'Badger DAO',
            'FARM': 'Harvest Finance',
            'CREAM': 'Cream Finance',
            'PICKLE': 'Pickle Finance',
            'KEEP': 'Keep Network',
            'NU': 'NuCypher',
            'BOND': 'BarnBridge',
            'RARI': 'Rarible',
            'SXP': 'Swipe',
            'REEF': 'Reef',
            'TLM': 'Alien Worlds',
            'ALICE': 'MyNeighborAlice',
            'CHR': 'Chromia',
            'DYDX': 'dYdX',
            'ILV': 'Illuvium',
            'IMX': 'Immutable X',
            'PEOPLE': 'ConstitutionDAO',
            'SPELL': 'Spell Token',
            'TRIBE': 'Tribe',
            'LOOKS': 'LooksRare',
            'APE': 'ApeCoin',
            'GMT': 'STEPN',
            'KDA': 'Kadena',
            'JASMY': 'JasmyCoin',
            'LDO': 'Lido DAO',
            'APT': 'Aptos',
            'OP': 'Optimism',
            'ARB': 'Arbitrum',
            'BLUR': 'Blur',
            'PEPE': 'Pepe',
            'SUI': 'Sui',
            'ORDI': 'ORDI',
            'TIA': 'Celestia',
            'SEI': 'Sei',
            'WLD': 'Worldcoin',
            'BONK': 'Bonk',
            'JTO': 'Jito',
            'PYTH': 'Pyth Network',
            'STRK': 'Starknet',
            'WIF': 'dogwifhat',
            'BOME': 'BOOK OF MEME',
            'ENA': 'Ethena',
            'W': 'Wormhole',
            'TNSR': 'Tensor',
            'TAO': 'Bittensor',
            'OMNI': 'Omni Network',
            'REZ': 'Renzo',
            'IO': 'io.net',
            'ZK': 'zkSync',
            'ZRO': 'LayerZero',
            'DOGS': 'Dogs',
            'TON': 'Toncoin',
            'NOT': 'Notcoin',
            'HMSTR': 'Hamster Kombat',
            'CATI': 'Catizen',
            'NEIRO': 'Neiro',
            'EIGEN': 'EigenLayer',
            'TRUMP': 'OFFICIAL TRUMP'
        }
        
        # 加密货币全名到符号的映射 (全名: 符号)
        self.crypto_names = {v.lower(): k for k, v in self.crypto_symbols.items()}
        
        # 中文名称映射
        self.chinese_names = {
            '比特币': 'BTC',
            '以太坊': 'ETH',
            '以太': 'ETH',
            '以太币': 'ETH',
            '以太现货': 'ETH',
            '泰达币': 'USDT',
            '泰达': 'USDT',
            '币安币': 'BNB',
            '瑞波币': 'XRP',
            '瑞波': 'XRP',
            '艾达币': 'ADA',
            '艾达': 'ADA',
            '索拉纳': 'SOL',
            '狗狗币': 'DOGE',
            '狗狗': 'DOGE',
            '狗币': 'DOGE',
            '波卡': 'DOT',
            '雪崩': 'AVAX',
            '柴犬币': 'SHIB',
            '柴犬': 'SHIB',
            '马蹄': 'MATIC',
            '多边形': 'MATIC',
            '莱特币': 'LTC',
            '莱特': 'LTC',
            '链环': 'LINK',
            '链接': 'LINK',
            '宇宙': 'ATOM',
            '恒星币': 'XLM',
            '唯链': 'VET',
            '波场': 'TRX',
            '以太经典': 'ETC',
            '文件币': 'FIL',
            '柚子': 'EOS',
            '小蚁': 'NEO',
        }
        
        # 常见的交易对后缀
        self.trading_pair_suffixes = ['USDT', 'USDC', 'BTC', 'ETH', 'USD', 'EUR', 'BNB']
        
        # 编译正则表达式模式以提高性能
        self._compile_patterns()

    def _load_extract_prompt(self) -> str:
        """加载提取币种的prompt"""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            prompt_path = os.path.join(
                current_dir,
                '..',
                'agent',
                'prompt',
                'extract_crypto_prompt'
            )
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load extract_crypto_prompt: {e}")
            return ""

    def _compile_patterns(self):
        """编译正则表达式模式"""
        # 交易对模式 (如 BTC-USDT, BTC/USDT, BTCUSDT)
        symbols = '|'.join(self.crypto_symbols.keys())
        self.trading_pair_pattern = re.compile(
            rf'\b({symbols})[-/]?({"|".join(self.trading_pair_suffixes)})\b',
            re.IGNORECASE
        )
        
        # 单独的币种符号模式
        self.symbol_pattern = re.compile(
            rf'\b({symbols})\b',
            re.IGNORECASE
        )
        
        # 币种全名模式 (支持部分匹配)
        names = '|'.join(self.crypto_names.keys())
        self.name_pattern = re.compile(
            rf'\b({names})\b',
            re.IGNORECASE
        )
        
        # 中文名称模式
        chinese_names = '|'.join(self.chinese_names.keys())
        self.chinese_name_pattern = re.compile(
            rf'({chinese_names})',
            re.IGNORECASE
        )
        
        # 合约模式 (如 BTCUSDTM, ETHUSDTM)
        self.contract_pattern = re.compile(
            rf'\b({symbols})(USDTM|USDM)\b',
            re.IGNORECASE
        )
    
    def extract_from_text(self, text: str) -> List[ExtractedCrypto]:
        """从文本中提取加密货币信息"""
        if not text:
            return []
        
        extracted = {}  # 使用字典去重
        
        # 1. 提取交易对
        for match in self.trading_pair_pattern.finditer(text):
            base, quote = match.groups()
            base_upper = base.upper()
            quote_upper = quote.upper()
            
            # 确保base是有效的加密货币符号
            if base_upper in self.crypto_symbols:
                key = base_upper
                if key not in extracted:
                    extracted[key] = ExtractedCrypto(
                        symbol=base_upper,
                        name=self.crypto_symbols.get(base_upper),
                        trading_pair=f"{base_upper}-{quote_upper}"
                    )
        
        # 2. 提取合约
        for match in self.contract_pattern.finditer(text):
            base, suffix = match.groups()
            base_upper = base.upper()
            
            if base_upper in self.crypto_symbols:
                key = base_upper
                if key not in extracted:
                    extracted[key] = ExtractedCrypto(
                        symbol=base_upper,
                        name=self.crypto_symbols.get(base_upper),
                        trading_pair=f"{base_upper}{suffix}"
                    )
        
        # 3. 提取单独的符号
        for match in self.symbol_pattern.finditer(text):
            symbol = match.group(1).upper()
            if symbol in self.crypto_symbols:
                key = symbol
                if key not in extracted:
                    extracted[key] = ExtractedCrypto(
                        symbol=symbol,
                        name=self.crypto_symbols.get(symbol)
                    )
        
        # 4. 提取英文全名
        for match in self.name_pattern.finditer(text):
            name = match.group(1).lower()
            if name in self.crypto_names:
                symbol = self.crypto_names[name]
                key = symbol
                if key not in extracted:
                    extracted[key] = ExtractedCrypto(
                        symbol=symbol,
                        name=self.crypto_symbols.get(symbol)
                    )
        
        # 5. 提取中文名称
        for match in self.chinese_name_pattern.finditer(text):
            name = match.group(1)
            if name in self.chinese_names:
                symbol = self.chinese_names[name]
                key = symbol
                if key not in extracted:
                    extracted[key] = ExtractedCrypto(
                        symbol=symbol,
                        name=self.crypto_symbols.get(symbol)
                    )
        
        return list(extracted.values())     

    def adjust_crypto_list(self, extracted_symbols: List[str]) -> List[str]:
        """调整提取的币种列表到合理范围
        
        规则：
        - 如果提取的币种为空，返回空列表
        - 如果提取的币种超过6个，只取前6个
        - 如果提取的币种不足3个，从默认列表中补充到3个
        - 自动去重并统一转为大写
        
        Args:
            extracted_symbols: 提取到的币种符号列表
            
        Returns:
            调整后的币种符号列表（长度在3-6之间）
        """
        if not extracted_symbols:
            return []

        # 默认补充币种列表（按优先级排序）
        default_cryptos = [
            'KCS-USDT', 'BTC-USDT', 'ETH-USDT', 'XRP-USDT', 'BNB-USDT', 'SOL-USDT', 'TRX-USDT', 'DOGE-USDT', 'ADA-USDT', 'BCH-USDT', 'LINK-USDT'
        ]
        
        # 确保所有符号都是大写并去重（保持顺序）
        seen = set()
        normalized = []
        for symbol in extracted_symbols:
            symbol_upper = symbol.upper()
            if symbol_upper not in seen:
                seen.add(symbol_upper)
                normalized.append(symbol_upper)
        
        # 如果超过6个，只取前6个
        if len(normalized) > 6:
            logger.info(f"Truncating {len(normalized)} symbols to 6")
            return normalized[:6]
        
        # 如果不足3个，从默认列表补充
        if len(normalized) < 3:
            # 找出还未被提取的币种
            remaining = [crypto for crypto in default_cryptos if crypto not in seen]
            # 计算需要补充的数量
            needed = 3 - len(normalized)
            # 从剩余币种中随机选取
            padding_list = random.sample(remaining, min(needed, len(remaining)))
            logger.info(f"Padding {len(normalized)} symbols to 3 with: {padding_list}")
            normalized.extend(padding_list)
        
        return normalized

    def _fallback_extraction(self, query: str, response: str = "") -> List[str]:
        """降级到正则提取（统一的降级处理）
        
        Args:
            query: 用户查询文本
            response: Agent回复文本（可选）
            
        Returns:
            标准化后的币种符号列表
        """
        text = f"{query}\n{response}".strip()
        extracted = self.extract_from_text(text)
        crypto_pairs = [crypto.symbol + '-USDT' for crypto in extracted]
        logger.info(f"Fallback extraction: {crypto_pairs}")
        return self.adjust_crypto_list(crypto_pairs)

    async def extract_with_llm(
        self,
        llm: AsyncOpenAI,
        model: str,
        query: str,
        response: str = "",
        temperature: float = 0.0
    ) -> List[str]:
        """使用大模型提取币种符号

        Args:
            llm: AsyncOpenAI客户端实例
            query: 用户查询文本
            response: Agent回复文本（可选）
            model: 使用的模型名称
            temperature: 模型temperature参数

        Returns:
            提取到的币种符号列表，如 ["BTC", "ETH"]
        """
        if not query and not response:
            return []

        self._extract_prompt = await mcp_client.get_prompt(name="extract_crypto_prompt")

        if not self._extract_prompt:
            logger.warning("Extract prompt not loaded, falling back to regex extraction")
            return self._fallback_extraction(query, response)

        if not llm:
            logger.error("LLM instance not provided, falling back to regex extraction")
            return self._fallback_extraction(query, response)

        try:
            # 构建用户消息
            user_content = f"User Query: {query}"
            if response:
                user_content += f"\n\nAgent Response: {response}"

            # 调用LLM
            logger.info(f"Calling LLM for crypto extraction with model: {model}")
            completion = await llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self._extract_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=temperature,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                }
            )

            # 解析响应
            response_text = completion.choices[0].message.content
            logger.debug(f"LLM response: {response_text}")

            # 尝试解析JSON
            try:
                result = json.loads(response_text)

                # 处理不同的响应格式
                if isinstance(result, list):
                    symbols = result
                elif isinstance(result, dict):
                    # 可能返回 {"symbols": ["BTC", "ETH"]} 或直接是符号列表
                    symbols = result.get("symbols", result.get("tokens", []))
                    if not symbols and result:
                        # 尝试从字典值中提取列表
                        for value in result.values():
                            if isinstance(value, list):
                                symbols = value
                                break
                else:
                    symbols = []

                # 确保所有符号都是大写字符串
                symbols = [str(s).upper() for s in symbols if s]

                logger.info(f"Extracted {len(symbols)} crypto symbols with LLM: {symbols}")
                return self.adjust_crypto_list(symbols)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}, using regex extraction instead")
                # 尝试从文本中提取符号
                symbols = re.findall(r'\b[A-Z]{2,10}\b', response_text)
                symbols = [s for s in symbols if s in self.crypto_symbols]
                return self.adjust_crypto_list(symbols)

        except Exception as e:
            logger.error(f"Error in LLM crypto extraction: {e}, falling back to regex extraction", exc_info=True)
            return self._fallback_extraction(query, response)


# 全局实例
crypto_extractor = CryptoExtractor()


if __name__ == "__main__":
    # 测试代码
    extractor = CryptoExtractor()
    
    test_texts = [
        "What's the price of BTC-USDT today?",
        "I want to buy some Bitcoin and Ethereum",
        "How is DOGE performing? Also check SOL/USDT",
        "Get the RSI for ETH-USDT on the 4-hour chart",
        "What's the mark price for BTCUSDTM contract?",
        "比特币今天的价格怎么样？",
        "我想了解以太坊和狗狗币的行情",
        "SHIB-USDT的走势如何？"
    ]
    
    for text in test_texts:
        print(f"\nText: {text}")
        extracted = extractor.extract_from_text(text)
        for crypto in extracted:
            print(f"  - Symbol: {crypto.symbol}, Name: {crypto.name}, Pair: {crypto.trading_pair}")