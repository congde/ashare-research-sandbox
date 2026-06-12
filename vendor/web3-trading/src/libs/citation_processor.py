"""
引用注脚处理模块
提供标准化的引用格式转换功能
"""

import re
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class CitationProcessor:
    """
    引用处理器
    负责将简单的 [1] 格式转换为标准 Markdown 引用格式 [citations:1](url "title")
    """
    
    # 引用关键字，用于标识引用注脚
    CITATION_KEYWORD = "citations"
    
    @staticmethod
    def convert_to_markdown_citations(
        text: str,
        citation_map: Dict[int, Dict[str, str]],
        citation_ids: Optional[List[int]] = None
    ) -> Tuple[str, List[Dict]]:
        """
        将文本中的 [1] 格式转换为标准 Markdown 引用格式
        
        Args:
            text: 包含引用标记的原始文本
            citation_map: 引用映射字典，格式: {index: {"url": "...", "title": "..."}}
            citation_ids: 可选的引用ID列表，如果不提供则自动检测
            
        Returns:
            Tuple[str, List[Dict]]: (转换后的文本, 使用的引用列表)
            
        Example:
            输入: "深圳今日天气晴朗[1]。"
            输出: "深圳今日天气晴朗[citations:1](https://example.com "天气预报")。"
        """
        if not citation_map or not text.strip():
            return text, []
        
        # 检测文本中的所有引用标记
        citation_matches = re.findall(r"\[(\d+)\]", text)
        if not citation_matches:
            return text, []
        
        # 确定实际使用的引用ID
        if citation_ids is None:
            citation_ids = []
            for match in citation_matches:
                citation_id = int(match)
                if citation_id in citation_map and citation_id not in citation_ids:
                    citation_ids.append(citation_id)
        
        if not citation_ids:
            return text, []
        
        logger.info(f"Found {len(citation_ids)} citations to convert: {citation_ids}")
        
        # 创建ID映射(旧ID -> 新连续ID)
        id_mapping = {}
        final_citations = []
        
        for new_id, old_id in enumerate(citation_ids, 1):
            id_mapping[old_id] = new_id
            url_info = citation_map.get(old_id, {})
            final_citations.append({
                "index": new_id,
                "url": url_info.get("url", "").strip(),
                "title": url_info.get("title", "")
            })
        
        # 检查是否需要重新编号
        consecutive_numbers = list(range(1, len(citation_ids) + 1))
        needs_renumbering = citation_ids != consecutive_numbers
        
        if needs_renumbering:
            logger.info(f"Renumbering citations: {citation_ids} -> {consecutive_numbers}")
        
        # 执行转换
        converted_text = text
        
        # Step 1: 替换为临时标记(避免冲突)
        for old_id in sorted(id_mapping.keys(), reverse=True):
            new_id = id_mapping[old_id]
            temp_placeholder = f"__TEMP_CITE_{new_id}__"
            converted_text = converted_text.replace(f"[{old_id}]", temp_placeholder)
        
        # Step 2: 替换为最终的 Markdown 格式
        for new_id in range(1, len(citation_ids) + 1):
            temp_placeholder = f"__TEMP_CITE_{new_id}__"
            old_id = citation_ids[new_id - 1]
            url_info = citation_map.get(old_id, {})
            url = url_info.get("url", "").strip()
            title = url_info.get("title", "").replace('"', '\\"')  # 转义标题中的引号
            
            # 格式: [citations:序号](目标链接 "链接标题")
            markdown_citation = f'[{CitationProcessor.CITATION_KEYWORD}:{new_id}]({url} "{title}")'
            converted_text = converted_text.replace(temp_placeholder, markdown_citation)
        
        logger.info(f"Successfully converted {len(final_citations)} citations to Markdown format")
        return converted_text, final_citations
    
    @staticmethod
    def extract_citation_pattern(text: str) -> List[Tuple[str, int, str, str]]:
        """
        从文本中提取所有 Markdown 格式的引用
        
        Args:
            text: 包含 Markdown 引用的文本
            
        Returns:
            List[Tuple[str, int, str, str]]: [(完整匹配, 序号, URL, 标题), ...]
            
        Example:
            输入: "天气晴朗[citations:1](https://example.com "天气预报")。"
            输出: [("[citations:1](https://example.com "天气预报")", 1, "https://example.com", "天气预报")]
        """
        # 匹配格式: [citations:数字](url "title")
        pattern = rf'\[{CitationProcessor.CITATION_KEYWORD}:(\d+)\]\(([^\s]+)\s+"([^"]*)"\)'
        matches = re.findall(pattern, text)
        
        results = []
        for match in matches:
            index = int(match[0])
            url = match[1]
            title = match[2].replace('\\"', '"')  # 反转义
            full_match = f'[{CitationProcessor.CITATION_KEYWORD}:{index}]({url} "{match[2]}")'
            results.append((full_match, index, url, title))
        
        return results
    
    @staticmethod
    def validate_citations(text: str) -> Tuple[bool, List[str]]:
        """
        验证文本中的引用格式是否正确
        
        Args:
            text: 待验证的文本
            
        Returns:
            Tuple[bool, List[str]]: (是否全部有效, 错误信息列表)
        """
        errors = []
        
        # 检查是否有旧格式的引用(纯数字)
        old_format_citations = re.findall(r"\[(\d+)\]", text)
        if old_format_citations:
            # 需要排除 Markdown 格式中的数字引用
            markdown_citations = CitationProcessor.extract_citation_pattern(text)
            markdown_indices = {str(idx) for _, idx, _, _ in markdown_citations}
            
            pure_old_format = [c for c in old_format_citations if c not in markdown_indices]
            if pure_old_format:
                errors.append(f"发现未转换的旧格式引用: {pure_old_format}")
        
        # 检查 Markdown 格式引用的完整性
        markdown_citations = CitationProcessor.extract_citation_pattern(text)
        for full_match, index, url, title in markdown_citations:
            if not url:
                errors.append(f"引用[{index}]缺少URL")
            if not title:
                errors.append(f"引用[{index}]缺少标题")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    @staticmethod
    def convert_back_to_simple_format(text: str) -> str:
        """
        将 Markdown 格式的引用转换回简单格式 [1]
        用于某些需要简化显示的场景
        
        Args:
            text: 包含 Markdown 引用的文本
            
        Returns:
            str: 转换为简单格式的文本
        """
        # 匹配格式: [citations:数字](url "title") -> [数字]
        pattern = rf'\[{CitationProcessor.CITATION_KEYWORD}:(\d+)\]\([^\)]+\)'
        converted_text = re.sub(pattern, r'[\1]', text)
        return converted_text
    
    @staticmethod
    def get_citation_summary(citation_map: Dict[int, Dict[str, str]]) -> str:
        """
        生成引用摘要信息，用于日志或调试
        
        Args:
            citation_map: 引用映射字典
            
        Returns:
            str: 格式化的引用摘要
        """
        if not citation_map:
            return "无引用信息"
        
        summary_lines = [f"共 {len(citation_map)} 条引用:"]
        for idx, info in sorted(citation_map.items()):
            url = info.get("url", "")
            title = info.get("title", "无标题")
            summary_lines.append(f"  [{idx}] {title[:50]}... - {url[:60]}...")
        
        return "\n".join(summary_lines)


def convert_citations_in_text(
    text: str,
    citation_map: Dict[int, Dict[str, str]]
) -> Tuple[str, List[Dict]]:
    """
    便捷函数：转换文本中的引用格式
    
    这是 CitationProcessor.convert_to_markdown_citations 的简化接口
    
    Args:
        text: 包含引用标记的原始文本
        citation_map: 引用映射字典
        
    Returns:
        Tuple[str, List[Dict]]: (转换后的文本, 使用的引用列表)
    """
    return CitationProcessor.convert_to_markdown_citations(text, citation_map)