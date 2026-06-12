# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:41:27
'''
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import jinja2


# 思考标签：Qwen3 使用 <think>...</think>，Qwen3.5 可能只有 </think>（无显式开头）
# 用于兜底移除 / 解析时兼容两种格式
THINK_START_TAG = "<think>"
THINK_END_TAG = "</think>"


def strip_think_content(text: str) -> tuple[str, bool]:
    """
    移除文本中的思考块，兼容 Qwen3 (<think>...</think>) 与 Qwen3.5 (仅 </think>) 格式。
    :return: (移除思考后的内容, 是否发生了移除)
    """
    if THINK_END_TAG not in text:
        return text, False
    idx = text.index(THINK_END_TAG) + len(THINK_END_TAG)
    return text[idx:].strip(), True

def utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 格式字符串，如 2026-02-09T15:30:00Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_TEMPLATE_ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(
    searchpath=os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt")
))
def jinja_render(name, data=None) -> str:
    template = _TEMPLATE_ENV.get_template(name)
    return template.render(**(data or {}))


def jinja_render_text(text: str, data=None) -> str:
    template = _TEMPLATE_ENV.from_string(text)
    return template.render(**(data or {}))


WEB_SEARCH_QUERY_MAX_LENGTH = 50

# 中文常见标点，可作为截断边界（无空格时使用）
_CJK_PUNCT = "。，、；：！？!?,…：；"

def truncate_web_search_query(query: str, max_length: int = WEB_SEARCH_QUERY_MAX_LENGTH) -> str:
    """web_search 查询超过 max_length 时截断：优先在空格处（英文）；其次在标点处（中文）；否则硬截断。"""
    if not query or len(query) <= max_length:
        return query
    truncated = query[:max_length]
    # 1. 英文：在最后一个空格处截断
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    # 2. 中文：在最后一个标点处截断
    last_punct = max(
        (i for i, c in enumerate(truncated) if c in _CJK_PUNCT),
        default=-1
    )
    if last_punct >= max_length // 2:
        # 避免截得过短
        return truncated[:last_punct + 1]
    # 3. 无空格、无合适标点：硬截断
    return truncated


def truncate_message(text: str, max_length: int = 500) -> str:
    """
    截断过长的消息，保留前半部分和后半部分，中间用" ...[truncated]... "标记。
    
    :param text: 原始消息
    :param max_length: 允许的最大长度（字符数）
    :return: 截断后的消息
    """
    if len(text) <= max_length:
        return text
    
    # 中间插入标记
    marker = " ...[truncated]... "
    keep = max_length - len(marker)
    # 前后各保留一半
    head_len = keep // 2
    tail_len = keep - head_len
    
    return text[:head_len] + marker + text[-tail_len:]


def truncate_tool_result(text: str, max_chars: int = 60000) -> str:
    """
    截断工具返回结果，防止超出 LLM 上下文窗口。
    保留头尾，中间标注截断信息（头部 70%，通常包含更关键的内容）。
    """
    if not text or len(text) <= max_chars:
        return text

    marker = (
        f"\n\n... [TOOL RESULT TRUNCATED: original {len(text)} chars, "
        f"kept {max_chars} chars] ...\n\n"
    )
    keep = max_chars - len(marker)
    head_len = int(keep * 0.7)
    tail_len = keep - head_len
    return text[:head_len] + marker + text[-tail_len:]


@dataclass
class CustomTableStreamProcessor:
    """
    滑动窗口流处理器，用于实时检测和替换自定义标记。
    
    当检测到 <custom_table>eventId</custom_table> 或 <custom_card>eventId</custom_card> 标记时，
    会将其替换为 {{kia-chat-card eventId='eventId'}} 格式。
    
    替换后的内容会作为单独的一块返回，确保前端可以独立处理该特殊格式。
    
    使用方法:
        # 单标记模式（向后兼容）
        processor = CustomTableStreamProcessor(tag_name="custom_table", event_id="eventId")
        
        # 多标记模式（用于 direct_response 等场景，两种标记不会同时出现）
        processor = CustomTableStreamProcessor(tag_names=["custom_table", "custom_card"], event_id="eventId")

        # 多标记 + 独立 event_id 模式（多卡片场景，每个标记使用不同的 eventId）
        processor = CustomTableStreamProcessor(
            tag_names=["custom_table", "custom_card"],
            tag_event_ids={"custom_table": "call_t1", "custom_card": "call_t2"},
        )
        
        for chunk in stream:
            outputs = processor.process(chunk)
            for output in outputs:  # 遍历所有输出块
                if output:
                    yield output
        # 流结束后，获取缓冲区中剩余的内容
        remaining = processor.flush()
        if remaining:
            yield remaining
    """
    # eventId
    event_id: str = ""

    # 标记名称，默认为 "custom_table"（单标记模式）
    tag_name: str = "custom_table"
    
    # 多标记名称列表（多标记模式，用于 direct_response 等场景）
    # 当设置此参数时，会同时检测多种标记，使用先出现的那个
    tag_names: list = field(default_factory=list)

    # 每个 tag_name 独立的 event_id 映射（多卡片场景）
    # 当设置此参数时，替换标记使用对应的 event_id 而非全局 event_id
    tag_event_ids: dict = field(default_factory=dict)
    
    # 开始标记（根据 tag_name 动态生成，多标记模式下为当前活动标记）
    START_TAG: str = field(init=False)
    # 结束标记（根据 tag_name 动态生成，多标记模式下为当前活动标记）
    END_TAG: str = field(init=False)
    
    # 多标记模式下的标记列表 [(start_tag, end_tag), ...]
    _tag_list: list = field(init=False, default_factory=list)
    
    # 滑动窗口缓冲区
    buffer: str = field(default="", init=False)
    # 是否正在截流（已检测到开始标记，等待结束标记）
    is_intercepting: bool = field(default=False, init=False)
    # 截流开始位置（开始标记在 buffer 中的位置）
    intercept_start_pos: int = field(default=0, init=False)
    
    def __post_init__(self):
        """根据 tag_name 或 tag_names 初始化开始和结束标记"""
        if self.tag_names:
            # 多标记模式
            self._tag_list = [(f"<{name}>", f"</{name}>") for name in self.tag_names]
            # 默认使用第一个标记（会在检测到实际标记时更新）
            self.START_TAG = self._tag_list[0][0]
            self.END_TAG = self._tag_list[0][1]
        else:
            # 单标记模式（向后兼容）
            self.START_TAG = f"<{self.tag_name}>"
            self.END_TAG = f"</{self.tag_name}>"
            self._tag_list = [(self.START_TAG, self.END_TAG)]
    
    def process(self, chunk: str) -> list[str]:
        """
        处理输入的流内容块。
        
        Args:
            chunk: 输入的内容块
            
        Returns:
            list[str]: 需要输出的内容块列表。每个替换后的内容作为单独的元素返回，
                       确保 {{kia-chat-card eventId='...'}} 作为完整的一块独立输出。
        """
        self.buffer += chunk
        
        # 如果正在截流模式
        if self.is_intercepting:
            return self._process_intercepting()
        else:
            return self._process_normal()
    
    def _find_earliest_start_tag(self) -> tuple:
        """
        在多标记模式下，查找 buffer 中最早出现的开始标记。
        
        Returns:
            tuple: (位置, 开始标记, 结束标记)，如果没找到返回 (-1, None, None)
        """
        earliest_pos = -1
        earliest_start_tag = None
        earliest_end_tag = None
        
        for start_tag, end_tag in self._tag_list:
            pos = self.buffer.find(start_tag)
            if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                earliest_pos = pos
                earliest_start_tag = start_tag
                earliest_end_tag = end_tag
        
        return (earliest_pos, earliest_start_tag, earliest_end_tag)
    
    def _process_normal(self) -> list[str]:
        """正常模式下的处理逻辑"""
        outputs = []
        current_output = ""
        
        while True:
            # 检查是否包含完整的开始标记（多标记模式下检测所有可能的标记）
            start_pos, found_start_tag, found_end_tag = self._find_earliest_start_tag()
            
            if start_pos == -1:
                # 没有找到开始标记，检查是否有部分开始标记（可能需要等待更多内容）
                # 检查 buffer 末尾是否可能是开始标记的前缀
                partial_match_len = self._check_partial_start_tag()
                
                if partial_match_len > 0:
                    # 输出安全的部分，保留可能的部分标记
                    safe_len = len(self.buffer) - partial_match_len
                    current_output += self.buffer[:safe_len]
                    self.buffer = self.buffer[safe_len:]
                else:
                    # 没有任何标记迹象，全部输出
                    current_output += self.buffer
                    self.buffer = ""
                break
            else:
                # 找到了开始标记，更新当前活动的标记
                self.START_TAG = found_start_tag
                self.END_TAG = found_end_tag
                
                # 先输出开始标记之前的内容
                before_tag_content = self.buffer[:start_pos]
                if before_tag_content:
                    current_output += before_tag_content
                
                # 如果有累积的普通内容，先作为独立块输出
                if current_output:
                    outputs.append(current_output)
                    current_output = ""
                
                # 更新 buffer 从开始标记位置开始
                self.buffer = self.buffer[start_pos:]
                
                # 进入截流模式
                self.is_intercepting = True
                self.intercept_start_pos = 0
                
                # 继续检查是否在当前 buffer 中有完整的结束标记
                intercept_results = self._process_intercepting()
                if intercept_results:
                    # 替换后的内容作为独立块添加
                    outputs.extend(intercept_results)
                    # 如果截流完成，继续检查是否还有其他标记
                    if not self.is_intercepting:
                        continue
                break
        
        # 添加剩余的普通内容
        if current_output:
            outputs.append(current_output)
        
        return outputs
    
    def _process_intercepting(self) -> list[str]:
        """截流模式下的处理逻辑"""
        outputs = []
        
        # 检查是否包含完整的结束标记
        # 在截流模式下，buffer 应该以开始标记开头
        end_pos = self.buffer.find(self.END_TAG)
        
        if end_pos != -1:
            # 找到了结束标记，提取完整的标记内容
            full_tag = self.buffer[:end_pos + len(self.END_TAG)]
            
            # 提取 eventId（在 <custom_table> 和 </custom_table> 之间）
            # event_id = self.buffer[len(self.START_TAG):end_pos].strip()
            
            # 根据当前活动标记查找对应的 event_id（多卡片时 tag_event_ids 为列表，按顺序消费）
            active_tag = self.START_TAG[1:-1]  # "<custom_card>" -> "custom_card"
            val = self.tag_event_ids.get(active_tag, self.event_id)
            if isinstance(val, list) and val:
                eid = val.pop(0)
            else:
                eid = val if isinstance(val, str) else self.event_id
            replacement = f"{{{{kia-chat-card eventId='{eid}'}}}}"
            outputs.append(replacement)
            
            # 更新 buffer，移除已处理的内容
            self.buffer = self.buffer[end_pos + len(self.END_TAG):]
            
            # 退出截流模式
            self.is_intercepting = False
            self.intercept_start_pos = 0
        
        # 如果没有找到结束标记，继续等待更多内容（不输出）
        return outputs
    
    def _check_partial_start_tag(self) -> int:
        """
        检查 buffer 末尾是否可能是任意开始标记的前缀（多标记模式下检查所有标记）。
        
        Returns:
            int: 部分匹配的最大长度，0 表示没有匹配
        """
        max_partial_len = 0
        
        # 检查所有可能的开始标记
        for start_tag, _ in self._tag_list:
            for i in range(1, len(start_tag)):
                partial = start_tag[:i]
                if self.buffer.endswith(partial):
                    max_partial_len = max(max_partial_len, i)
        
        return max_partial_len
    
    def flush(self) -> str:
        """
        流结束时，刷新缓冲区中剩余的内容。
        
        Returns:
            str: 缓冲区中剩余的内容
        """
        remaining = self.buffer
        self.buffer = ""
        self.is_intercepting = False
        self.intercept_start_pos = 0
        return remaining
