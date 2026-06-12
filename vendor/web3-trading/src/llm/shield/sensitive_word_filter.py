# --*-- coding:utf-8 --*--
"""
本地敏感词检测
"""

import os
import time
import yaml
import re
import ahocorasick
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from threading import Lock


@dataclass
class MatchResult:
    """匹配结果"""
    word: str                    # 匹配到的原始词
    category: str                # 所属分类
    severity: str                # 严重等级
    action: str                  # 建议动作
    position: int                # 匹配位置
    matched_variant: str         # 实际匹配的变体词


@dataclass
class FilterResult:
    """过滤结果"""
    is_blocked: bool             # 是否拦截
    matched_words: List[MatchResult]  # 匹配到的所有敏感词
    categories: Set[str]         # 涉及的分类
    highest_severity: str        # 最高严重等级
    suggested_action: str        # 建议动作
    scan_time_ms: int            # 扫描耗时（毫秒）


class SensitiveWordFilter:
    """

    使用AC自动机实现高效的多模式匹配：
    - 时间复杂度：O(n + m)，n为文本长度，m为匹配次数
    - 空间复杂度：O(k * l)，k为关键词数量，l为平均长度
    """

    def __init__(self, config_path: str = None, logger=None):
        """
        初始化敏感词过滤器

        Args:
            config_path: YAML配置文件路径
            logger: 日志对象
        """
        self.logger = logger
        self._automaton: Optional[ahocorasick.Automaton] = None
        self._word_metadata: Dict[str, dict] = {}  # 词->元数据映射
        self._regex_patterns_sorted: List[tuple] = []  # 按复杂度排序的正则表达式列表 (优化)
        self._config: dict = {}
        self._config_path: str = config_path or self._get_default_config_path()
        self._last_load_time: float = 0
        self._lock = Lock()  # 保护热更新

        # 统计信息
        self._stats = {
            "total_words": 0,
            "total_variants": 0,
            "total_regex": 0,  # 统计正则表达式数量
            "categories": 0,
            "last_reload": None,
            "scan_count": 0,
            "match_count": 0
        }

        # 加载配置
        self.reload()

    def _get_default_config_path(self) -> str:
        """获取默认配置文件路径"""
        project_path = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
        return os.path.join(project_path, "conf/sensitive_words.yaml")

    def reload(self) -> bool:
        """
        重新加载配置（支持热更新）

        Returns:
            bool: 是否加载成功
        """
        start_time = time.time()

        with self._lock:
            try:
                # 读取配置文件
                if not os.path.exists(self._config_path):
                    if self.logger:
                        self.logger.error(f"Sensitive words config not found: {self._config_path}")
                    return False

                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f)

                # 构建AC自动机
                self._build_automaton()

                # 更新统计信息
                self._last_load_time = time.time()
                self._stats["last_reload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                load_time = int((time.time() - start_time) * 1000)

                if self.logger:
                    self.logger.info(
                        f"Sensitive word filter reloaded successfully: "
                        f"{self._stats['total_words']} words, "
                        f"{self._stats['total_variants']} variants, "
                        f"{self._stats['total_regex']} regex patterns, "
                        f"{self._stats['categories']} categories, "
                        f"load_time={load_time}ms"
                    )

                return True

            except Exception as e:
                if self.logger:
                    self.logger.exception(f"Failed to reload sensitive words config: {e}")
                return False

    def _estimate_regex_complexity(self, pattern_str: str) -> int:
        """
        估计正则表达式的复杂度
        """
        complexity = 0
        complexity += len(pattern_str)  # 基础复杂度：长度
        complexity += pattern_str.count('*') * 10  # 量词：*
        complexity += pattern_str.count('+') * 10  # 量词：+
        complexity += pattern_str.count('?') * 5   # 量词：?
        complexity += pattern_str.count('|') * 3   # 选择
        complexity += pattern_str.count('(') * 2   # 分组
        complexity += pattern_str.count('[') * 2   # 字符类
        return complexity

    def _regex_match(self, pattern: re.Pattern, text: str) -> List[tuple]:
        """
        正则表达式匹配
        """
        try:
            matches = []
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), match.group()))
            return matches
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Regex match error: {e}")
            return []

    def _build_automaton(self):

        automaton = ahocorasick.Automaton()
        self._word_metadata.clear()
        self._regex_patterns_sorted.clear()  

        total_words = 0
        total_variants = 0
        total_regex = 0  # 统计正则表达式数量
        regex_patterns_unsorted = []  # 临时存储未排序的正则表达式
        categories = self._config.get("categories", {})

        case_sensitive = self._config.get("config", {}).get("case_sensitive", False)

        for category_name, category_data in categories.items():
            if not isinstance(category_data, dict):
                continue

            severity = category_data.get("severity", "medium")
            action = category_data.get("action", "block")
            keywords = category_data.get("keywords", [])

            for item in keywords:
                if isinstance(item, str):
                    # 简单字符串格式
                    word = item
                    variants = []
                    item_severity = severity
                    word_type = "literal"  # 默认类型
                elif isinstance(item, dict):
                    # 详细配置格式
                    word = item.get("word", "")
                    variants = item.get("variants", [])
                    item_severity = item.get("severity", severity)
                    word_type = item.get("type", "literal")  # 支持type字段
                else:
                    continue

                if not word:
                    continue

                # 处理正则表达式
                if word_type == "regex":
                    try:
                        compiled_pattern = re.compile(word, re.IGNORECASE if not case_sensitive else 0)
                        # 估计复杂度用于后续排序
                        complexity = self._estimate_regex_complexity(word)
                        regex_patterns_unsorted.append((compiled_pattern, complexity, {
                            "original": word,
                            "category": category_name,
                            "severity": item_severity,
                            "action": action
                        }))
                        total_regex += 1
                        if self.logger:
                            self.logger.debug(f"Loaded regex pattern: {word[:50]}... (complexity={complexity}) for {category_name}")
                    except re.error as e:
                        if self.logger:
                            self.logger.warning(f"Invalid regex pattern: {word}, error: {e}")
                    continue

                # 处理字面词 
                normalized_word = word if case_sensitive else word.lower()
                automaton.add_word(normalized_word, (word, category_name, item_severity, action))
                self._word_metadata[normalized_word] = {
                    "original": word,
                    "category": category_name,
                    "severity": item_severity,
                    "action": action
                }
                total_words += 1

                # 添加变体词
                for variant in variants:
                    if variant:
                        normalized_variant = variant if case_sensitive else variant.lower()
                        automaton.add_word(normalized_variant, (word, category_name, item_severity, action))
                        self._word_metadata[normalized_variant] = {
                            "original": word,
                            "category": category_name,
                            "severity": item_severity,
                            "action": action
                        }
                        total_variants += 1

        # 按复杂度排序正则表达式（
        regex_patterns_unsorted.sort(key=lambda x: x[1])
        self._regex_patterns_sorted = [(pattern, metadata) for pattern, _, metadata in regex_patterns_unsorted]

        # 构建失败指针
        automaton.make_automaton()

        # 更新统计
        self._automaton = automaton
        self._stats["total_words"] = total_words
        self._stats["total_variants"] = total_variants
        self._stats["total_regex"] = total_regex  # 更新统计
        self._stats["categories"] = len(categories)

    def check(self, text: str, return_matches: bool = True) -> FilterResult:
        """
        检查文本是否包含敏感词

        Args:
            text: 待检查文本
            return_matches: 是否返回详细匹配信息

        Returns:
            FilterResult: 过滤结果
        """
        start_time = time.time()

        if not text or not self._automaton:
            return FilterResult(
                is_blocked=False,
                matched_words=[],
                categories=set(),
                highest_severity="low",
                suggested_action="pass",
                scan_time_ms=0
            )

        # 更新统计
        self._stats["scan_count"] += 1

        # 大小写处理
        case_sensitive = self._config.get("config", {}).get("case_sensitive", False)
        search_text = text if case_sensitive else text.lower()

        # AC自动机扫描 
        matched_words: List[MatchResult] = []
        categories: Set[str] = set()
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        highest_severity = "low"
        highest_severity_score = 0

        for end_index, (original_word, category, severity, action) in self._automaton.iter(search_text):
            # 记录匹配
            start_index = end_index - len(original_word) + 1
            matched_variant = search_text[start_index:end_index + 1]

            match_result = MatchResult(
                word=original_word,
                category=category,
                severity=severity,
                action=action,
                position=start_index,
                matched_variant=matched_variant
            )

            if return_matches:
                matched_words.append(match_result)

            categories.add(category)

            # 更新最高严重等级
            severity_score = severity_order.get(severity, 1)
            if severity_score > highest_severity_score:
                highest_severity = severity
                highest_severity_score = severity_score

        # 正则表达式
        if self._regex_patterns_sorted:
            # 使用排序后的正则表达式列表
            matched_positions = set()  

            for compiled_pattern, metadata in self._regex_patterns_sorted:
                try:
                    # 执行正则匹配
                    regex_matches = self._regex_match(compiled_pattern, text)

                    for start_index, end_index, matched_text in regex_matches:
                        # 使用Position Set高效检查重复（O(1) vs O(n)）
                        pos_key = (start_index, end_index)

                        if pos_key not in matched_positions:
                            matched_positions.add(pos_key)

                            match_result = MatchResult(
                                word=metadata["original"],
                                category=metadata["category"],
                                severity=metadata["severity"],
                                action=metadata["action"],
                                position=start_index,
                                matched_variant=matched_text
                            )

                            if return_matches:
                                matched_words.append(match_result)

                            categories.add(metadata["category"])

                            # 更新最高严重等级
                            severity_score = severity_order.get(metadata["severity"], 1)
                            if severity_score > highest_severity_score:
                                highest_severity = metadata["severity"]
                                highest_severity_score = severity_score

                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Error during regex matching: {e}")

        # 统计
        if matched_words:
            self._stats["match_count"] += len(matched_words)

        # 判断是否拦截
        is_blocked = len(matched_words) > 0
        suggested_action = "block" if is_blocked else "pass"

        # 根据最高严重等级决定动作
        if highest_severity in ["low", "medium"]:
            suggested_action = "warn"

        scan_time_ms = int((time.time() - start_time) * 1000)

        # 审计日志
        if is_blocked and self.logger:
            audit_config = self._config.get("audit", {})
            if audit_config.get("enable", True):
                self._log_audit(text, matched_words, scan_time_ms)

        return FilterResult(
            is_blocked=is_blocked,
            matched_words=matched_words,
            categories=categories,
            highest_severity=highest_severity,
            suggested_action=suggested_action,
            scan_time_ms=scan_time_ms
        )

    def _log_audit(self, text: str, matches: List[MatchResult], scan_time_ms: int):
        """记录审计日志"""
        audit_config = self._config.get("audit", {})

        if not audit_config.get("log_matched_words", True):
            return

        matched_words_str = ", ".join([
            f"{m.word}({m.category}, {m.severity})"
            for m in matches[:5]  # 最多记录前5个
        ])

        text_preview = text[:50] if audit_config.get("log_user_query", True) else "[REDACTED]"

        self.logger.warning(
            f"Sensitive word detected: "
            f"words=[{matched_words_str}], "
            f"text_preview='{text_preview}...', "
            f"match_count={len(matches)}, "
            f"scan_time={scan_time_ms}ms"
        )

    def get_stats(self) -> dict:
        """获取统计信息"""
        return self._stats.copy()

    def clear_stats(self):
        """清空统计信息"""
        self._stats["scan_count"] = 0
        self._stats["match_count"] = 0

    def is_config_outdated(self, max_age_seconds: int = 3600) -> bool:
        """
        检查配置是否过期

        Args:
            max_age_seconds: 最大缓存时间（秒）

        Returns:
            bool: 是否过期
        """
        if self._last_load_time == 0:
            return True

        age = time.time() - self._last_load_time
        return age > max_age_seconds


# 全局单例
_global_filter: Optional[SensitiveWordFilter] = None
_global_filter_lock = Lock()


def get_global_filter(config_path: str = None, logger=None) -> SensitiveWordFilter:
    """
    获取全局敏感词过滤器单例

    Args:
        config_path: 配置文件路径
        logger: 日志对象

    Returns:
        SensitiveWordFilter: 过滤器实例
    """
    global _global_filter

    with _global_filter_lock:
        if _global_filter is None:
            _global_filter = SensitiveWordFilter(config_path, logger)
        return _global_filter


def reload_global_filter() -> bool:
    """
    重新加载全局过滤器配置（热更新）

    Returns:
        bool: 是否成功
    """
    global _global_filter

    if _global_filter is None:
        return False

    return _global_filter.reload()


if __name__ == "__main__":

    filter_instance = SensitiveWordFilter()

    test_cases = [
        "我想了解一下海洛因的危害",
        "How to buy heroin?",
        "今天天气真好",
        "h3r0in是什么",
        "海_洛_因吸食方法",
        "法轮功是邪教",
        "赌博网站推荐",
    ]

    print("=" * 80)
    print("敏感词过滤器测试")
    print("=" * 80)
    print(f"统计信息: {filter_instance.get_stats()}")
    print()

    for text in test_cases:
        result = filter_instance.check(text)
        print(f"文本: {text}")
        print(f"  拦截: {result.is_blocked}")
        print(f"  匹配数: {len(result.matched_words)}")
        if result.matched_words:
            for match in result.matched_words:
                print(f"    - {match.word} ({match.category}, {match.severity}) at pos {match.position}")
        print(f"  耗时: {result.scan_time_ms}ms")
        print()
