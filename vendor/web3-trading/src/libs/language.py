"""
Language detection and localization utilities
"""
import os
import re
import glob
import json
import fasttext
from opencc import OpenCC
import logging

logger = logging.getLogger(__name__)

base_path = os.path.dirname(os.path.abspath(__file__))
FASTTEXT_MODEL = fasttext.load_model(os.path.join(base_path, '../../data/lid.176.ftz'))
cc_s2t = OpenCC('s2t')  # 简体转繁体
cc_t2s = OpenCC('t2s')  # 繁体转简体


# 思考过程节点变量对应的翻译ID
THINKING_NODES_ANALYZING_QUERY_START_ID = '3136a70b7ed14800a7cf'
THINKING_NODES_ANALYZING_QUERY_END_ID = '920b00f308054000affa'
THINKING_NODES_SEARCHING_KEY_INFORMATION_START_ID = '5604cf176ba74000aa67'
THINKING_NODES_SEARCHING_KEY_INFORMATION_END_ID = '865ffd0316614000a5fd'
THINKING_NODES_GENERATING_RESPONSE_START_ID = '05c2760249e64000ae5d'
THINKING_NODES_GENERATING_RESPONSE_END_ID = '62541645f38b4000ade2'
THINKING_NODES_DEEP_THINKING_START_ID = 'acf623d4e2154800a7ae'
THINKING_NODES_DEEP_THINKING_END_ID = '40255e78f5174800ac12'
THINKING_NODES_RESEARCH_DECOMPOSITION_START_ID = 'cdac092b26374000a18a'
THINKING_NODES_RESEARCH_DECOMPOSITION_CONTENT_ID = '3f246815caed4800a129'
THINKING_NODES_RESEARCH_DECOMPOSITION_END_ID = '74ad2a9f68f74000a936'
THINKING_NODES_SUB_TOPIC_ID = 'e0cbeb9f6b954000a4c8'
THINKING_NODES_SEARCHING_RELATED_INFORMATION_ID = '2b15f650ee7f4000a8a6'
THINKING_NODES_ANALYZING_SEARCH_RESULTS_ID = '50de5eab52834000a148'
THINKING_NODES_FOUND_INFORMATION_ID = '852072f327584800a874'
THINKING_NODES_EXPLORE_IN_DEPTH_ID = '05fc12d0fa504800ac05'
THINKING_NODES_CONTINUE_DEEP_RESEARCHING_ID = 'ceb352e3176b4000a682'
THINKING_NODES_GENERATING_REPORT_START_ID = 'ab5ba014d58f4000a76a'
THINKING_NODES_GENERATING_REPORT_END_ID = '39abf94277504000a2b3'

# DAG 规划过程的翻译ID
DAG_PLANNING_TASKS_START_ID = 'f1a2b3c4d5e64000a001'
DAG_PLANNING_TASK_PREFIX_ID = 'f1a2b3c4d5e64000a002'
DAG_PLANNING_STILL_PLANNING_ID = 'f1a2b3c4d5e64000a003'


# MCP工具ID对应的翻译ID
MCP_TOOLS_INDICATOR_LOOKUP_ID = 'e6d2636d73584000a0f1'
MCP_TOOLS_OPPORTUNITY_ANALYSIS_ID = '7ea483b10fcb4000a11f'
MCP_TOOLS_WEB_SEARCH_ID = '7152f07dd2e44000a454'
MCP_TOOLS_KNOWLEDGE_BASE_SEARCH_ID = 'e22261ee3a694800af5d'
MCP_TOOLS_RECOMMEND_FINANCIAL_PRODUCT_ID = 'bf84896626fb4800a870'
MCP_TOOLS_RECOMMEND_CRYPTO_ID = '890d3becc4d24000a780'
MCP_TOOLS_RETRIEVE_FUNDAMENTAL_EVENTS_ID = '3723c421af794800aeb4'
MCP_TOOLS_RECHARGE_AND_WITHDRAW_ID = 'bd341067a42f4000a45d'
MCP_TOOLS_COINS_INFO_ID = 'c01n51nf0a1b2c3d4e5f'
MCP_TOOLS_COINS_NEWS_ID = 'c01n5n3w5a2b3c4d5e6f'
MCP_TOOLS_CMC_CURRENCY_FUNDING_RATES_ID = 'cmc7fund1ng8rat35x9a'
MCP_TOOLS_MARKET_SENTIMENT_AND_FUND_FLOWS_ID = 'mark3t53nt1m3ntf10w5'
MCP_TOOLS_BATCH_INDICATOR_CALCULATION_ID = 'batch1nd1cat0rca1cx2y'
# 新增：24小时基础K线和基础指标工具ID
MCP_TOOLS_BASIC_CANDLESTICK_24H_ID = '24hour_basic_candlestick_data'
MCP_TOOLS_BASIC_INDICATORS_ID = 'basic_indicators'

# 推荐文案ID
RECOMMENDED_COPY_CURRENCY_SUGGESTIONS_TITLE_ID = '0934a2e090a34800a2b3'

# 币种筛选表格标题ID
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_NAME_ID = '.2HpNbmBcpJg9djs4XTzKUK'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_PRICE_ID = '.price'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_24_CHANGE_ID = '.price.rate.24h'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_24_VOLUME_ID = '.bEEH8CX2HBdZPGK2QojBzS'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_ACTION_ID = '.operations'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_TRADE_ID = '.home_action_trade'
RECOMMEND_CRYPTO_TABLE_WEB_TITLE_DETAILS_ID = '.chartdetail'
RECOMMEND_CRYPTO_TABLE_APP_TITLE_COIN_ID = '.coin'
RECOMMEND_CRYPTO_TABLE_APP_TITLE_VOL_ID = '.dex_sort_amount'
RECOMMEND_CRYPTO_TABLE_APP_TITLE_PRICE_ID = '.price'
RECOMMEND_CRYPTO_TABLE_APP_TITLE_24_CHANGE_ID = '.price.rate.24h'
RECOMMEND_CRYPTO_TABLE_ACTION_ADD_WATCHLIST_ID = '.add.watchlist'
RECOMMEND_CRYPTO_TABLE_ACTION_ADD_WATCHLIST_ONE_BUTTON_ID = '.add.watchlist.one.button'

# 理财产品推荐表格标题ID
RECOMMEND_EARN_TABLE_WEB_TITLE_CURRENCY_ID = '.coin'
RECOMMEND_EARN_TABLE_WEB_TITLE_APY_ID = '.keth.switch.years.desc'
RECOMMEND_EARN_TABLE_WEB_TITLE_TERM_ID = '.1ZaSJvobFaxz3wDK48Y1c5'
RECOMMEND_EARN_TABLE_WEB_TITLE_REDEMPTION_ID = '.earn.list.head.redemption_period'
RECOMMEND_EARN_TABLE_WEB_TITLE_ACTION_ID = '.operations'
RECOMMEND_EARN_TABLE_WEB_TITLE_SUBSCRIBE_ID = '.earn.list.head.subscription'


# 本地化文本字典
LOCALIZED_MESSAGES = {
    # THINKING NODES
    'analyzing_query_start': THINKING_NODES_ANALYZING_QUERY_START_ID,
    'analyzing_query_end': THINKING_NODES_ANALYZING_QUERY_END_ID,
    'calling_tools_start': THINKING_NODES_SEARCHING_KEY_INFORMATION_START_ID,
    'calling_tools_end': THINKING_NODES_SEARCHING_KEY_INFORMATION_END_ID,
    'deep_think_start': THINKING_NODES_DEEP_THINKING_START_ID,
    'deep_think_end': THINKING_NODES_DEEP_THINKING_END_ID,
    'generating_answer_start': THINKING_NODES_GENERATING_RESPONSE_START_ID,
    'generating_answer_end': THINKING_NODES_GENERATING_RESPONSE_END_ID,
    # MCP TOOLS
    'get_crypto_market_data': MCP_TOOLS_INDICATOR_LOOKUP_ID,
    'get_crypto_investment_outlook': MCP_TOOLS_OPPORTUNITY_ANALYSIS_ID,
    'web_search': MCP_TOOLS_WEB_SEARCH_ID,
    'KB_search': MCP_TOOLS_KNOWLEDGE_BASE_SEARCH_ID,
    'recommend_financial_product': MCP_TOOLS_RECOMMEND_FINANCIAL_PRODUCT_ID,
    'coin_screener': MCP_TOOLS_RECOMMEND_CRYPTO_ID,
    'retrieve_fundamental_events': MCP_TOOLS_RETRIEVE_FUNDAMENTAL_EVENTS_ID,
    'recharge_and_withdraw': MCP_TOOLS_RECHARGE_AND_WITHDRAW_ID,
    'coins_info': MCP_TOOLS_COINS_INFO_ID,
    'coins_news': MCP_TOOLS_COINS_NEWS_ID,
    'cmc_currency_funding_rates': MCP_TOOLS_CMC_CURRENCY_FUNDING_RATES_ID,
    'market_sentiment_and_fund_flows': MCP_TOOLS_MARKET_SENTIMENT_AND_FUND_FLOWS_ID,
    'batch_indicator_calculation': MCP_TOOLS_BATCH_INDICATOR_CALCULATION_ID,
    # 新增工具
    'basic_candlestick_24h': MCP_TOOLS_BASIC_CANDLESTICK_24H_ID,
    'basic_indicators': MCP_TOOLS_BASIC_INDICATORS_ID,
    # DAG PLANNING
    'dag_planning_start': DAG_PLANNING_TASKS_START_ID,
    'dag_task_prefix': DAG_PLANNING_TASK_PREFIX_ID,
    'dag_still_planning': DAG_PLANNING_STILL_PLANNING_ID,
    # RECOMMENDED COPY
    'currency_suggestions_title': RECOMMENDED_COPY_CURRENCY_SUGGESTIONS_TITLE_ID,
    # recommend_crypto_table_title
    'recommend_crypto_table_web_title_name': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_NAME_ID,
    'recommend_crypto_table_web_title_price': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_PRICE_ID,
    'recommend_crypto_table_web_title_24_change': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_24_CHANGE_ID,
    'recommend_crypto_table_web_title_24_volume': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_24_VOLUME_ID,
    'recommend_crypto_table_web_title_action': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_ACTION_ID,
    'recommend_crypto_table_web_title_trade': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_TRADE_ID,
    'recommend_crypto_table_web_title_details': RECOMMEND_CRYPTO_TABLE_WEB_TITLE_DETAILS_ID,
    'recommend_crypto_table_app_title_coin': RECOMMEND_CRYPTO_TABLE_APP_TITLE_COIN_ID,
    'recommend_crypto_table_app_title_vol': RECOMMEND_CRYPTO_TABLE_APP_TITLE_VOL_ID,
    'recommend_crypto_table_app_title_price': RECOMMEND_CRYPTO_TABLE_APP_TITLE_PRICE_ID,
    'recommend_crypto_table_app_title_24_change': RECOMMEND_CRYPTO_TABLE_APP_TITLE_24_CHANGE_ID,
    'recommend_crypto_table_action_add_watchlist': RECOMMEND_CRYPTO_TABLE_ACTION_ADD_WATCHLIST_ID,
    'recommend_crypto_table_action_add_watchlist_one_button': RECOMMEND_CRYPTO_TABLE_ACTION_ADD_WATCHLIST_ONE_BUTTON_ID,
    # recommend_earn_table_title
    'recommend_earn_table_web_title_currency': RECOMMEND_EARN_TABLE_WEB_TITLE_CURRENCY_ID,
    'recommend_earn_table_web_title_apy': RECOMMEND_EARN_TABLE_WEB_TITLE_APY_ID,
    'recommend_earn_table_web_title_term': RECOMMEND_EARN_TABLE_WEB_TITLE_TERM_ID,
    'recommend_earn_table_web_title_redemption': RECOMMEND_EARN_TABLE_WEB_TITLE_REDEMPTION_ID,
    'recommend_earn_table_web_title_action': RECOMMEND_EARN_TABLE_WEB_TITLE_ACTION_ID,
    'recommend_earn_table_web_title_subscribe': RECOMMEND_EARN_TABLE_WEB_TITLE_SUBSCRIBE_ID,
}

# 技能展示名本地化（从 conf/i18n/skill_display_names.json 读取）
SKILL_DISPLAY_NAME_MAP = {}
_skill_display_file = os.path.join(base_path, '../../conf/i18n/skill_display_names.json')
try:
    if os.path.exists(_skill_display_file):
        with open(_skill_display_file, 'r', encoding='utf-8') as f:
            SKILL_DISPLAY_NAME_MAP = json.load(f)
except Exception as e:
    logger.warning(f"Failed to load skill display names from {_skill_display_file}: {e}")

# KB_search支持的语种英文名称到语言代码的映射
KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP = {
    "English": "en",
    "Russian": "ru",
    "Spanish": "es",
    "Arabic": "ar",
    "Vietnamese": "vi",
    "Turkish": "tr",
    "French": "fr",
    "Portuguese": "pt",
    "Indonesian": "id",
    "German": "de",
    "Chinese (Simplified)": "zh_cn",
    "Chinese (Traditional)": "zh_hk",
}

# 公司翻译支持的语种代码（也是前端传过来的语种代码，注意这里除了中文，其他的只保留前面的语种代码，去掉了后面的地区代码）与英文名称的映射
LANGUAGE_CODE_TO_NAME_MAP = {
    "ar": ("Arabic", "阿拉伯语"),
    "bn": ("Bengali", "孟加拉语"),
    "de": ("German", "德语"),
    "en": ("English", "英语"),
    "es": ("Spanish", "西班牙语"),
    "fil": ("Filipino", "菲律宾语"),
    "fr": ("French", "法语"),
    "hi": ("Hindi", "印地语"),  
    "id": ("Indonesian", "印尼语"),
    "it": ("Italian", "意大利语"),
    "ja": ("Japanese", "日语"),
    # "ko": ("Korean", "韩语"),  # 该语种前端已下线
    "ms": ("Malay", "马来语"),  # langdetect包不支持
    "nl": ("Dutch", "荷兰语"),
    "pl": ("Polish", "波兰语"),
    "pt": ("Portuguese", "葡萄牙语"),
    "ru": ("Russian", "俄语"),
    "th": ("Thai", "泰语"),
    "tr": ("Turkish", "土耳其语"),
    "uk": ("Ukrainian", "乌克兰语"),
    "ur": ("Urdu", "乌尔都语"),
    "vi": ("Vietnamese", "越南语"),
    "zh_cn": ("Chinese (Simplified)", "中文简体"),  # 该语种前端已下线
    "zh_hk": ("Chinese (Traditional)", "中文繁体"),
}

# 公司翻译支持的语种英文名称到语言代码的映射
ENGLISH_NAME_TO_CODE_MAP = {
    "Arabic": "ar",
    "Bengali": "bn",
    "German": "de",
    "English": "en",
    "Spanish": "es",
    "Filipino": "fil",
    "French": "fr",
    "Hindi": "hi",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    # "Korean": "ko",
    "Malay": "ms",
    "Dutch": "nl",
    "Polish": "pl",
    "Portuguese": "pt",
    "Russian": "ru",
    "Thai": "th",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Urdu": "ur",
    "Vietnamese": "vi",
    "Chinese (Simplified)": "zh_cn",
    "Chinese (Traditional)": "zh_hk",
}


# 公司翻译支持的语种英文名称到语言代码（含地区）的映射
ENGLISH_NAME_TO_CODE_LOCAL_MAP = {
    "Arabic": "ar_AE",
    "Bengali": "bn_BD",
    "German": "de_DE",
    "English": "en_US",
    "Spanish": "es_ES",
    "Filipino": "fil_PH",
    "French": "fr_FR",
    "Hindi": "hi_IN",
    "Indonesian": "id_ID",
    "Italian": "it_IT",
    "Japanese": "ja_JP",
    # "Korean": "ko_KR",
    "Malay": "ms_MY",
    "Dutch": "nl_NL",
    "Polish": "pl_PL",
    "Portuguese": "pt_PT",
    "Russian": "ru_RU",
    "Thai": "th_TH",
    "Turkish": "tr_TR",
    "Ukrainian": "uk_UA",
    "Urdu": "ur_PK",
    "Vietnamese": "vi_VN",
    "Chinese (Simplified)": "zh_CN",
    "Chinese (Traditional)": "zh_HK",
}


ID_TO_TRANSLATION = {}
# 从conf/i18n/thinking_nodes/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/thinking_nodes/messages_*.properties')):
    language_code = os.path.basename(filepath).replace('messages_', '').replace('.properties', '').lower()
    if language_code not in ['zh_cn', 'zh_hk']:
        language_code = language_code.split('_')[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        messages = f.read()
        for line in messages.split('\n'):
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key not in ID_TO_TRANSLATION:
                    ID_TO_TRANSLATION[key] = {}
                ID_TO_TRANSLATION[key][language_code] = value.strip()

# 从conf/i18n/mcp_tools/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/mcp_tools/messages_*.properties')):
    language_code = os.path.basename(filepath).replace('messages_', '').replace('.properties', '').lower()
    if language_code not in ['zh_cn', 'zh_hk']:
        language_code = language_code.split('_')[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        messages = f.read()
        for line in messages.split('\n'):
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key not in ID_TO_TRANSLATION:
                    ID_TO_TRANSLATION[key] = {}
                ID_TO_TRANSLATION[key][language_code] = value.strip()

# 从conf/i18n/recommended_copy/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/recommended_copy/messages_*.properties')):
    language_code = os.path.basename(filepath).replace('messages_', '').replace('.properties', '').lower()
    if language_code not in ['zh_cn', 'zh_hk']:
        language_code = language_code.split('_')[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        messages = f.read()
        for line in messages.split('\n'):
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key not in ID_TO_TRANSLATION:
                    ID_TO_TRANSLATION[key] = {}
                ID_TO_TRANSLATION[key][language_code] = value.strip()



# 从conf/i18n/table_recommend_crypto/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/table_recommend_crypto/messages_*.properties')):
    language_code = os.path.basename(filepath).replace('messages_', '').replace('.properties', '').lower()
    if language_code not in ['zh_cn', 'zh_hk']:
        language_code = language_code.split('_')[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        messages = f.read()
        for line in messages.split('\n'):
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key not in ID_TO_TRANSLATION:
                    ID_TO_TRANSLATION[key] = {}
                ID_TO_TRANSLATION[key][language_code] = value.strip()

# 新增：从conf/i18n/welcome/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/welcome/messages_*.properties')):
    language_code = os.path.basename(filepath).replace('messages_', '').replace('.properties', '').lower()
    if language_code not in ['zh_cn', 'zh_hk']:
        language_code = language_code.split('_')[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        messages = f.read()
        for line in messages.split('\n'):
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key not in ID_TO_TRANSLATION:
                    ID_TO_TRANSLATION[key] = {}
                ID_TO_TRANSLATION[key][language_code] = value.strip()


# 全局字典：存储所有固定问句的多语言翻译
FIXED_MESSAGE_ID_TO_TRANSLATION = {}

# 从conf/i18n/table_recommend_crypto/中读取所有格式为messages_${language}.properties的文件，并存到字典中
for filepath in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../conf/i18n/fixed_message/*.properties')):
    # 提取 source 名称作为 key
    source_key = os.path.splitext(os.path.basename(filepath))[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                lang_key, value = line.split('=', 1)
                lang_key = lang_key.strip()
                value = value.strip()
                # lang_key 作为语言码
                if source_key not in FIXED_MESSAGE_ID_TO_TRANSLATION:
                    FIXED_MESSAGE_ID_TO_TRANSLATION[source_key] = {}
                FIXED_MESSAGE_ID_TO_TRANSLATION[source_key][lang_key] = value


def get_localized_message(key: str, language: str, **kwargs) -> str:
    """
    获取本地化消息
    
    Args:
        key: 消息键
        language: 语言代码
        **kwargs: 格式化参数
        
    Returns:
        str: 本地化后的消息
    """
    # 1) skill key 的内置本地化（避免前端显示 raw key）
    skill_map = SKILL_DISPLAY_NAME_MAP.get(key)
    if skill_map:
        translation = skill_map.get(language) or skill_map.get("en", key)
        try:
            return translation.format(**kwargs)
        except KeyError:
            return translation

    # 2) 直接 key 查找（如 conf/i18n/welcome/messages_*.properties）
    translation = ID_TO_TRANSLATION.get(key, {}).get(language, "")
    if translation:
        try:
            return translation.format(**kwargs)
        except KeyError:
            return translation
   
    # 3) 固定消息的本地化
    fixed_map = FIXED_MESSAGE_ID_TO_TRANSLATION.get(key)
    if fixed_map:
        translation = fixed_map.get(language)
        try:
            return translation.format(**kwargs)
        except KeyError:
            return translation

    # 4) 处理特殊 key 映射
    if key == "customer_service_kb_search":
        key = "KB_search"

    # 5) 常规 i18n ID 映射
    translation_id = LOCALIZED_MESSAGES.get(key, "")
    translation = ID_TO_TRANSLATION.get(translation_id, {}).get(language, "")
    try:
        return translation.format(**kwargs)
    except KeyError:
        return translation

def detect_chinese_variant(text: str) -> str:
    """
    判断中文字符串是简体中文还是繁体中文
    注意：此函数假设输入的字符串已经是中文，不进行中文检测
    
    Args:
        text: 中文字符串（已确认是中文）
        
    Returns:
        "Chinese (Simplified)" -> 简体中文
        "Chinese (Traditional)" -> 繁体中文
        
    Examples:
        >>> detect_chinese_variant("你好世界")
        'Chinese (Simplified)'
        >>> detect_chinese_variant("這是一個繁體中文句子。")
        'Chinese (Traditional)'
    """
    # 使用OpenCC进行转换来判断繁简体
    # 如果转成简体后变了，说明原文是繁体
    text_t2s = cc_t2s.convert(text)
    if text != text_t2s:
        return "Chinese (Traditional)"
    
    # 如果转成繁体后变了，说明原文是简体
    text_s2t = cc_s2t.convert(text)
    if text != text_s2t:
        return "Chinese (Simplified)"
    
    # 如果转换后都不变（可能是文本中的字没有繁简区别，或者都是简体），
    # 默认返回简体中文
    return "Chinese (Simplified)"


# fastText 语言代码到项目语言代码的映射（处理不一致的情况）
FASTTEXT_TO_PROJECT_CODE_MAP = {
    "tl": "fil",  # Tagalog -> Filipino (fastText uses tl for Tagalog/Filipino)
    "zh": "zh_cn",  # 通用中文 -> 简体中文（会在后续通过 detect_chinese_variant 进一步判断繁简体）
    "mr": "hi",  # Marathi -> Hindi (fastText sometimes confuses short Hindi text like "नमस्ते")
    # Note: Malay (ms) and Indonesian (id) are very similar, fastText may return 'id' for both
    # We keep the original detection to avoid breaking Indonesian detection
}


def _has_chinese_without_japanese_kana(text: str) -> bool:
    """
    判断文本是否「明显为中文」：含有 CJK 汉字且不含日文假名（平假名/片假名）。
    用于在 fastText 之前优先识别中文，避免因 default_lang_code=ja 或 fastText 误判导致中文问题被回复成日文。
    """
    if not text or not text.strip():
        return False
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    has_hiragana = bool(re.search(r"[\u3040-\u309f]", text))
    has_katakana = bool(re.search(r"[\u30a0-\u30ff]", text))
    return has_cjk and not has_hiragana and not has_katakana


def detect_reply_language(text: str, default_lang_code: str = "en") -> str:
    """
    Detect reply language name from text using fastText.

    Returns English name used by prompts, e.g. "English", "Chinese (Simplified)".
    Falls back to default_lang_code when confidence is low.

    When the query clearly looks like Chinese (contains CJK characters and no Japanese kana),
    Chinese is returned first so that Chinese questions are not answered in Japanese when
    the UI language or fastText suggests Japanese.
    """
    if not text:
        return LANGUAGE_CODE_TO_NAME_MAP.get(default_lang_code, ("English",))[0]

    # 用户用中文提问时优先按中文回复，避免因主站语言/默认语种为日文或 fastText 误判而返回日文
    if _has_chinese_without_japanese_kana(text):
        return detect_chinese_variant(text)

    lang_code = default_lang_code
    try:
        labels, probs = FASTTEXT_MODEL.predict(text.replace("\n", " "), k=1)
        # 降低阈值到 0.50 以捕获更多短文本场景（如 "Halo dunia", "Kumusta ka"）
        # 原阈值 0.60 对短文本过于严格，导致大量 fallback
        if labels and probs and probs[0] >= 0.50:
            lang_code = labels[0].replace("__label__", "")
            # 映射 fastText 代码到项目代码
            lang_code = FASTTEXT_TO_PROJECT_CODE_MAP.get(lang_code, lang_code)
    except Exception as e:
        logger.warning(f"Language detection failed, fallback to {default_lang_code}: {e}")

    if lang_code in {"zh", "zh_cn", "zh_hk", "zh_tw", "zh-hk", "zh-tw"}:
        return detect_chinese_variant(text)

    return LANGUAGE_CODE_TO_NAME_MAP.get(lang_code, ("English",))[0]


def format_system_language(system_language):
    """
    格式化系统语言, 返回统一的语种代码和语种英文名称
    """
    system_language = system_language.lower()
    if system_language not in ['zh_cn', 'zh_hk']:
        system_language = system_language.split('_')[0]
    if system_language not in LANGUAGE_CODE_TO_NAME_MAP:
        system_language = 'en'
    return system_language

