# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/04
URL风险检测处理器
用于检测用户query、AI回复内容、引用中的URL是否存在风险
'''
import os
import re
import json
import logging
import asyncio
import time
from typing import List, Dict, Optional, Tuple, Set
from pydantic import BaseModel

from libs import http
from libs.wrapper import usage_time
from llm.shield.translate import translate

logger = logging.getLogger(__name__)


class URLRiskLevel:
    """URL风险等级"""
    BLACK = "black"  # 黑名单
    GRAY = "gray"    # 灰名单
    WHITE = "white"  # 白名单


class URLCheckResult(BaseModel):
    """URL检测结果"""
    has_risk: bool = False  # 是否有风险
    risky_urls: List[str] = []  # 有风险的URL列表
    url_details: Dict[str, Dict] = {}  # URL详细信息 {url: {level, tags, ...}}
    

class URLRiskChecker:
    """
    URL风险检测器
    
    功能:
    1. 从文本中提取URL
    2. 调用360威胁情报API检测URL风险
    3. 判定black和gray等级的URL为有风险
    
    处理策略:
    - Query中有风险URL: 返回兜底消息，拦截整个请求 (BLOCKED_QUERY)
    - Answer中有风险URL: 不拦截回答，只在Citations阶段移除风险URL的引用
    - Citations中有风险URL: 移除对应的引用项，重新编号，清理文本中的引用标记
    """
    
    # URL正则表达式 - 匹配http/https开头的URL
    # 注意: 排除末尾的标点符号(逗号、句号、引号等)和Markdown格式符号
    URL_PATTERN = re.compile(
        r'https?://(?:www\.)?'  # http:// or https://
        r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}'  # domain
        r'(?::[0-9]{1,5})?'  # optional port
        # 路径部分: 只允许ASCII可见字符,排除空白、标点、Unicode(中文等)
        r'(?:/[a-zA-Z0-9._~:/?#\[\]@!$&\'()*+,;=%\-]*)?',
        re.IGNORECASE
    )
    
    # 纯域名正则表达式 - 匹配不带协议的域名
    # 支持多语言边界：中文、日语、韩语、阿拉伯语、俄语、德语、法语等
    # 包含各种标点符号和Unicode字符边界
    PLAIN_DOMAIN_PATTERN = re.compile(
        r'(?:^|'  # 行首
        r'[\s\t\n\r]|'  # 空白字符
        r'[,，.。;；:：!！?？、]|'  # 中英文标点
        r'''[\'"\"''""\(\)\[\]\{\}]|'''  # 引号和括号
        r'[*_~`]|'  # Markdown格式符号: **加粗**, __斜体__, ~~删除线~~, `代码`
        r'[\u4e00-\u9fff]|'  # 中文（CJK统一汉字）
        r'[\u3040-\u309f]|'  # 日文平假名
        r'[\u30a0-\u30ff]|'  # 日文片假名
        r'[\uac00-\ud7af]|'  # 韩文音节
        r'[\u0600-\u06ff]|'  # 阿拉伯文
        r'[\u0400-\u04ff]'  # 西里尔文（俄语等）
        r')'
        # 域名捕获组 - 支持IDN (TLD仅允许ASCII)
        r'((?:www\.)?'
        r'[a-zA-Z0-9\u00c0-\u024f\u0400-\u04ff\u0600-\u06ff-]+'  # 主域名：拉丁扩展、西里尔、阿拉伯 (不包含CJK)
        r'(?:\.[a-zA-Z0-9\u00c0-\u024f\u0400-\u04ff\u0600-\u06ff-]+)*'  # 可选子域名
        r'\.[a-zA-Z]{2,}'  # TLD必须是纯ASCII字母 (com, org, xyz等)
        r')'
        r'(?::[0-9]{1,5})?'  # optional port
        r'(?='  # 前向断言（后面是）
        r'/'  # 斜杠（路径开始）
        r'|$'  # 结束
        r'|[\s\t\n\r]'  # 空白
        r'|[,，.。;；:：!！?？、]'  # 标点
        r'''|[\'"\"''""\(\)\[\]\{\}]'''  # 引号和括号
        r'|[*_~`]'  # Markdown格式符号: **加粗**, __斜体__, ~~删除线~~, `代码`
        r'|[\u4e00-\u9fff]'  # 中文
        r'|[\u3040-\u309f]'  # 日文平假名
        r'|[\u30a0-\u30ff]'  # 日文片假名
        r'|[\uac00-\ud7af]'  # 韩文
        r'|[\u0600-\u06ff]'  # 阿拉伯文
        r'|[\u0400-\u04ff]'  # 西里尔文
        r')',
        re.IGNORECASE | re.UNICODE
    )
    
    # 域名提取正则表达式 - 用于从URL中提取域名
    DOMAIN_EXTRACT_PATTERN = re.compile(
        r'^(?:https?://)?'  # optional http:// or https://
        r'(?:www\.)?'  # optional www.
        r'([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}',  # domain
        re.IGNORECASE
    )
    
    _I18N_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "conf/i18n/llm_shield"
    )
    
    # 离线黑名单文件路径 (可通过config配置)
    _BLACKLIST_PATH = None  # 延迟初始化，从config读取
    
    def __init__(self, api_url: str = None, api_key: str = None, timeout: float = None, 
                 blacklist_path: str = None, block_gray: bool = None):
        """
        初始化URL风险检测器
        
        Args:
            api_url: 360威胁情报API地址 (优先级: 参数 > config > 环境变量 > 默认值)
            api_key: API密钥
            timeout: 请求超时时间(秒)
            blacklist_path: 离线黑名单文件路径 (相对或绝对路径)
            block_gray: 是否拦截gray等级的URL (True=拦截black+gray, False=仅拦截black)
        """
        # 尝试从config读取配置
        try:
            from web.config import config
            config_api_url = getattr(config, 'url_risk_api_url', None)
            config_api_key = getattr(config, 'url_risk_api_key', None)
            config_timeout = getattr(config, 'url_risk_timeout', None)
            config_blacklist_path = getattr(config, 'url_risk_blacklist_path', None)
            config_block_gray = getattr(config, 'url_risk_block_gray', None)
        except Exception as e:
            logger.warning(f"Failed to load config, using defaults: {e}")
            config_api_url = None
            config_api_key = None
            config_timeout = None
            config_blacklist_path = None
            config_block_gray = None
        
        # 配置优先级: 参数 > config > 环境变量 > 默认值
        self.api_url = (
            api_url or 
            config_api_url or 
            os.environ.get("URL_RISK_API_URL")
        )
        
        self.api_key = (
            api_key or 
            config_api_key or 
            os.environ.get("URL_RISK_API_KEY")
        )
        
        self.timeout = (
            timeout if timeout is not None else
            config_timeout if config_timeout is not None else
            5.0
        )
        
        # 离线黑名单路径处理
        blacklist_path = blacklist_path or config_blacklist_path
        if blacklist_path:
            # 如果是相对路径，基于项目根目录解析
            if not os.path.isabs(blacklist_path):
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                blacklist_path = os.path.join(project_root, blacklist_path)
            self._BLACKLIST_PATH = blacklist_path
        else:
            # 使用默认路径
            self._BLACKLIST_PATH = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "conf/domain_blacklist/domain_blacklist.json"
            )
        
        # 是否拦截gray等级 (默认True)
        self.block_gray = (
            block_gray if block_gray is not None else
            config_block_gray if config_block_gray is not None else
            True
        )
        
        # 离线黑名单 (延迟加载)
        self._blacklist_set: Optional[Set[str]] = None
        self._blacklist_load_time_ms: float = 0.0
        self._blacklist_enabled: bool = True  # 默认启用离线黑名单
        
        # logger.info(
        #     f"URLRiskChecker initialized:\n"
        #     f"  API URL: {self.api_url}\n"
        #     f"  API Key: {self.api_key[:10]}***\n"
        #     f"  Timeout: {self.timeout}s\n"
        #     f"  Blacklist Path: {self._BLACKLIST_PATH}\n"
        #     f"  Block Gray: {self.block_gray}"
        # )
        
    def _load_offline_blacklist(self):
        """
        延迟加载离线黑名单到内存 (使用 set 实现 O(1) 查询)
        
        仅在首次使用时加载，避免不必要的启动开销
        """
        if self._blacklist_set is not None:
            return  # 已加载
        
        start = time.perf_counter()
        
        try:
            if not os.path.exists(self._BLACKLIST_PATH):
                logger.warning(f"⚠️  离线黑名单文件不存在: {self._BLACKLIST_PATH}")
                self._blacklist_set = set()  # 空集合
                self._blacklist_enabled = False
                return
            
            with open(self._BLACKLIST_PATH, 'r', encoding='utf-8') as f:
                domains = json.load(f)
                
            # 转换为小写 set (域名不区分大小写)
            self._blacklist_set = {
                str(domain).strip().lower() 
                for domain in domains 
                if domain and str(domain).strip()
            }
            
            self._blacklist_load_time_ms = (time.perf_counter() - start) * 1000
            
            logger.info(
                f"✅ 离线黑名单加载成功: {len(self._blacklist_set):,} 个域名 "
                f"(耗时: {self._blacklist_load_time_ms:.2f} ms)"
            )
            
        except Exception as e:
            logger.error(f"❌ 离线黑名单加载失败: {e}", exc_info=True)
            self._blacklist_set = set()
            self._blacklist_enabled = False
    
    def _is_in_offline_blacklist(self, domain: str) -> bool:
        """
        O(1) 查询域名是否在离线黑名单中
        
        Args:
            domain: 域名 (自动转小写)
            
        Returns:
            是否在黑名单中
        """
        if not self._blacklist_enabled or not domain:
            return False
        
        # 延迟加载
        if self._blacklist_set is None:
            self._load_offline_blacklist()
        
        return domain.strip().lower() in self._blacklist_set
    
    def extract_urls(self, text: str) -> List[str]:
        """
        从文本中提取所有URL和域名
        
        支持检测:
        1. 完整URL: https://example.com/path
        2. 纯域名: ilikefishing.xyz
        3. www域名: www.malicious-site.com
        
        Args:
            text: 待检测文本
            
        Returns:
            URL/域名列表
        """
        if not text:
            return []
        
        results = []
        
        # 1. 提取完整URL (http/https)
        full_urls = self.URL_PATTERN.findall(text)
        results.extend(full_urls)
        
        # 2. 提取纯域名 (不带协议的)
        # 先移除已匹配的完整URL，避免重复检测
        text_without_urls = self.URL_PATTERN.sub(' ', text)
        plain_domains = self.PLAIN_DOMAIN_PATTERN.findall(text_without_urls)
        results.extend(plain_domains)
        
        # 去重
        return list(set(results))
    
    def extract_domain(self, url: str) -> str:
        """
        从URL中提取域名
        
        支持:
        - https://example.com/path -> example.com
        - www.example.com -> example.com
        - example.com -> example.com
        
        Args:
            url: 完整URL或域名
            
        Returns:
            纯域名（不含协议、www、路径、端口）
        """
        match = self.DOMAIN_EXTRACT_PATTERN.match(url)
        if match:
            # 移除协议和www前缀
            domain = url
            domain = re.sub(r'^https?://', '', domain)
            domain = re.sub(r'^www\.', '', domain)
            # 只保留域名部分,去除路径
            domain = domain.split('/')[0]
            # 去除端口
            domain = domain.split(':')[0]
            return domain
        return url
    
    @usage_time
    async def check_urls(self, urls: List[str]) -> URLCheckResult:
        """
        批量检测URL风险
        
        双重检测机制:
        1. 优先使用360威胁情报API (在线检测)
        2. API失败时使用离线黑名单备份
        3. 任何一个检测到风险即判定为有风险
        
        支持检测:
        - 完整URL: https://example.com/path
        - 纯域名: example.com 或 ilikefishing.xyz
        
        360 API 支持同时提交域名和完整URL，会自动处理
        
        Args:
            urls: URL/域名列表
            
        Returns:
            URLCheckResult: 检测结果
        """
        if not urls:
            return URLCheckResult()
        
        # 提取域名（用于域名匹配）
        domains = [self.extract_domain(url) for url in urls]
        domains = [d for d in domains if d]  # 过滤空值
        
        # 去重域名（360 API 会自动去重，但我们提前去重减少请求量）
        unique_domains = list(set(domains))
        
        logger.info(f"📊 URL检测统计: 总URL数={len(urls)}, 总域名数={len(domains)}, 去重后域名数={len(unique_domains)}")
        
        if not unique_domains:
            return URLCheckResult()
        
        # === 第一步: 离线黑名单快速检测 ===
        offline_risky_domains = set()
        if self._blacklist_enabled:
            for domain in unique_domains:
                if self._is_in_offline_blacklist(domain):
                    offline_risky_domains.add(domain)
                    logger.warning(f"🚫 离线黑名单命中: {domain}")
        
        if offline_risky_domains:
            logger.info(f"📋 离线黑名单检测: {len(offline_risky_domains)}/{len(unique_domains)} 个域名命中")
        
        # === 第二步: 360 API 在线检测 ===
        api_result = None
        api_success = False
        
        # 构建请求 - 直接提交域名（360 API 推荐使用域名）
        domain_str = ",".join(unique_domains)
        payload = {
            "query": {
                "keywords": [
                    {"field": "category", "value": "domain"},
                    {"field": "query", "value": domain_str}
                ]
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-Sec-Key": self.api_key
        }
        
        try:
            logger.info(f"🌐 调用360 API检测: domains={unique_domains}")
            
            # 调用API
            response = await http.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            logger.info(f"URL risk check response: {response}")
            
            # 解析结果
            api_result = self._parse_response(urls, domains, response)
            api_success = True
            
            if api_result.has_risk:
                logger.info(f"🌐 360 API检测: {len(api_result.risky_urls)} 个URL有风险")
            
        except Exception as e:
            logger.error(f"❌ 360 API检测失败: {e}", exc_info=True)
            api_success = False
        
        # === 第三步: 合并双重检测结果 ===
        if api_success and api_result:
            # API检测成功，合并离线黑名单结果
            if offline_risky_domains:
                # 将离线黑名单检测到的风险域名添加到结果中
                for domain in offline_risky_domains:
                    # 找到对应的URL
                    for i, d in enumerate(domains):
                        if d == domain and urls[i] not in api_result.risky_urls:
                            api_result.risky_urls.append(urls[i])
                            api_result.url_details[urls[i]] = {
                                "domain": domain,
                                "level": "black",
                                "source": "offline_blacklist",
                                "confidence": "离线黑名单"
                            }
                
                # 更新风险标记
                if offline_risky_domains and not api_result.has_risk:
                    api_result.has_risk = True
                    logger.info(f"✅ 双重检测: 离线黑名单补充检测到风险")
            
            return api_result
        
        else:
            # API失败，仅使用离线黑名单结果
            logger.warning(f"⚠️  360 API不可用，降级使用离线黑名单检测")
            
            result = URLCheckResult()
            
            if offline_risky_domains:
                result.has_risk = True
                
                # 构建详细结果
                for i, domain in enumerate(domains):
                    if domain in offline_risky_domains:
                        url = urls[i]
                        result.risky_urls.append(url)
                        result.url_details[url] = {
                            "domain": domain,
                            "level": "black",
                            "source": "offline_blacklist",
                            "confidence": "离线黑名单",
                            "tags": [{"name": "离线黑名单", "desc": "域名存在于本地黑名单库"}]
                        }
                
                logger.warning(f"📋 离线黑名单检测结果: {len(result.risky_urls)} 个URL有风险")
            
            return result

    
    def _parse_response(
        self, 
        urls: List[str], 
        domains: List[str], 
        response: Dict
    ) -> URLCheckResult:
        """
        解析API响应
        
        Args:
            urls: 原始URL列表
            domains: 域名列表
            response: API响应
            
        Returns:
            URLCheckResult: 检测结果
        """
        result = URLCheckResult()
        
        # 检查响应状态
        if response.get("code") != "0":
            logger.warning(f"URL risk check failed: {response.get('msg')}")
            return result
        
        data = response.get("data", [])
        if not data:
            logger.info("No risky URLs found")
            return result
        
        # 创建域名到URL的映射
        domain_to_url = {}
        for url in urls:
            domain = self.extract_domain(url)
            domain_to_url[domain] = url
        
        # 检查每个域名的风险
        for item in data:
            ioc = item.get("ioc")  # 域名
            level = item.get("level")  # 风险等级: black/gray/white
            
            if not ioc or not level:
                continue
            
            # 根据配置决定是否拦截gray等级
            # block_gray=True: 拦截 black + gray
            # block_gray=False: 仅拦截 black
            is_risky = False
            if level == URLRiskLevel.BLACK:
                is_risky = True
            elif level == URLRiskLevel.GRAY and self.block_gray:
                is_risky = True
            
            if is_risky:
                result.has_risk = True
                
                # 找到对应的原始URL
                original_url = domain_to_url.get(ioc, ioc)
                result.risky_urls.append(original_url)
                
                # 保存详细信息
                result.url_details[original_url] = {
                    "domain": ioc,
                    "level": level,
                    "source": "api",  # 标记来源为360 API
                    "confidence": item.get("confidence", ""),
                    # "tags": item.get("tags", []),
                    # "first_time": item.get("first_time", ""),
                    # "last_time": item.get("last_time", "")
                }
                
                logger.warning(
                    f"Risky URL detected: {original_url} (domain={ioc}, level={level})"
                )
        
        return result
    
    async def check_text(self, text: str) -> URLCheckResult:
        """
        检测文本中的URL风险
        
        Args:
            text: 待检测文本
            
        Returns:
            URLCheckResult: 检测结果
        """
        urls = self.extract_urls(text)
        if not urls:
            return URLCheckResult()
        
        return await self.check_urls(urls)
    
    def get_fallback_message(self, language_code: str = "zh-cn") -> str:
        """
        获取URL风险的兜底消息
        
        注意: 此消息仅用于Query风控场景，当用户输入的query中包含风险URL时使用
        Answer中的风险URL不使用此消息，而是直接移除引用
        
        Args:
            language_code: 语言代码
            
        Returns:
            本地化的提示消息
        """
        # 使用"敏感话题"的key
        msg = translate(language_code, "21109315dbba4000a894", self._I18N_PATH)
        category = translate(language_code, "a89e495ae4f84000a024", self._I18N_PATH)
        return msg.format(category=category)
    
    def remove_risky_citations(
        self, 
        citations: List[Dict], 
        risky_urls: List[str]
    ) -> Tuple[List[Dict], bool]:
        """
        移除有风险的引用
        
        Args:
            citations: 引用列表 [{"index": 1, "url": "xxx", "title": "xxx"}, ...]
            risky_urls: 有风险的URL列表
            
        Returns:
            (清理后的引用列表, 是否有删除)
        """
        if not citations or not risky_urls:
            return citations, False
        
        original_count = len(citations)
        
        # 记录原始引用的索引序列
        original_indices = [c.get('index') for c in citations]
        logger.info(f"🔢 [remove_risky_citations] Original citations count: {original_count}")
        logger.info(f"🔢 [remove_risky_citations] Original indices: {original_indices[:20]}")  # 只显示前20个
        
        # 提取风险URL的域名列表
        risky_domains = set()
        for url in risky_urls:
            domain = self.extract_domain(url)
            if domain:
                risky_domains.add(domain)
        
        logger.info(f"🔍 风险域名列表: {risky_domains}")
        
        # 过滤掉有风险的URL (通过域名匹配)
        safe_citations = []
        for citation in citations:
            url = citation.get("url", "")
            citation_domain = self.extract_domain(url)
            
            # 检查引用的域名是否在风险域名列表中
            if citation_domain not in risky_domains:
                safe_citations.append(citation)
                logger.debug(f"✅ 保留安全引用: {url} (domain: {citation_domain})")
            else:
                logger.warning(f"❌ 移除风险引用: {citation} (domain: {citation_domain} 在风险列表中)")
        
        # 重新编号
        renumbered_indices = []
        for idx, citation in enumerate(safe_citations, 1):
            old_index = citation.get("index")
            citation["index"] = idx
            renumbered_indices.append(f"{old_index}→{idx}")
        
        logger.info(f"🔢 [remove_risky_citations] Renumbering: {', '.join(renumbered_indices[:20])}")  # 只显示前20个
        
        has_removed = len(safe_citations) < original_count
        
        if has_removed:
            logger.info(
                f"❌ [remove_risky_citations] Removed {original_count - len(safe_citations)} risky citations, "
                f"remaining: {len(safe_citations)}"
            )
            # 显示最终的索引序列
            final_indices = [c.get('index') for c in safe_citations]
            logger.info(f"✅ [remove_risky_citations] Final indices after renumbering: {final_indices[:20]}")
        else:
            logger.info(f"✅ [remove_risky_citations] No risky citations found, all {len(safe_citations)} citations are safe")
        
        return safe_citations, has_removed
    

    def remove_risky_citation_marks(
        self, 
        text: str, 
        removed_indices: List[int]
    ) -> str:
        """
        从文本中移除被删除的引用标记，并重新编号剩余的引用
        支持两种格式：
        1. [数字] - 简单引用格式
        2. [citations:数字](url "title") - Markdown引用格式
        
        Args:
            text: 原始文本
            removed_indices: 被移除的引用索引列表 (例如: [2, 5])
            
        Returns:
            清理后的文本
            
        示例:
            text = "内容[1]更多[citations:2](url)其他[3]信息[citations:4](url)结束[5]"
            removed_indices = [2, 4]
            返回: "内容[1]更多其他[2]信息结束[3]"
        """
        if not text or not removed_indices:
            return text
        
        logger.info(f"🔢 [引用标记重编号] 开始处理...")
        logger.info(f"   移除的索引: {sorted(removed_indices)}")
        
        # 找出所有引用标记及其位置（支持两种格式）
        # 格式1: [数字]
        # 格式2: [citations:数字](url "title")
        simple_pattern = re.compile(r'\[(\d+)\]')
        markdown_pattern = re.compile(r'\[citations:(\d+)\]\([^)]+\)')
        
        simple_matches = list(simple_pattern.finditer(text))
        markdown_matches = list(markdown_pattern.finditer(text))
        
        logger.info(f"   原文中找到 {len(simple_matches)} 个简单引用标记 [数字]")
        logger.info(f"   原文中找到 {len(markdown_matches)} 个Markdown引用标记 [citations:数字](...)")
        
        # 构建索引映射: 旧索引 -> 新索引
        # 核心思路：每个旧索引需要减去其之前被移除的索引数量
        index_mapping = {}
        removed_set = set(removed_indices)
        
        # 获取所有出现的索引（从两种格式中）
        all_indices_simple = set(int(m.group(1)) for m in simple_matches)
        all_indices_markdown = set(int(m.group(1)) for m in markdown_matches)
        all_indices = sorted(all_indices_simple | all_indices_markdown)
        
        logger.info(f"   原文中的引用索引: {all_indices}")
        
        for old_idx in all_indices:
            if old_idx in removed_set:
                # 标记为删除
                index_mapping[old_idx] = None
            else:
                # 计算该索引之前有多少个被移除的索引
                num_removed_before = sum(1 for r in removed_set if r < old_idx)
                # 新索引 = 旧索引 - 之前移除的数量
                new_idx = old_idx - num_removed_before
                index_mapping[old_idx] = new_idx
        
        logger.info(f"   索引映射关系: {index_mapping}")
        
        # 从后往前替换，避免位置偏移问题
        result = text
        for match in reversed(matches):
            old_idx = int(match.group(1))
            new_idx = index_mapping.get(old_idx)
            
            start, end = match.span()
            if new_idx is None:
                # 删除这个标记
                result = result[:start] + result[end:]
                logger.debug(f"   删除标记 [{old_idx}] at position {start}")
            elif new_idx != old_idx:
                # 替换为新索引
                result = result[:start] + f'[{new_idx}]' + result[end:]
                logger.debug(f"   重编号 [{old_idx}] -> [{new_idx}] at position {start}")
        
        logger.info(f"✅ [引用标记重编号] 完成")
        
        return result

# 全局单例
_url_checker: Optional[URLRiskChecker] = None


def get_url_checker() -> URLRiskChecker:
    """获取URL检测器单例"""
    global _url_checker
    if _url_checker is None:
        _url_checker = URLRiskChecker()
    return _url_checker