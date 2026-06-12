#!/usr/bin/env python3
"""
脚本用于从 line_num_id_mapping_with_result.json 中提取数据并转换为 Excel 格式
Excel 按 tool_name 分组，每个 tool_name 创建一个工作表
列包括：query、agentType、sessionId、qaId、tool_name、tool_args、tool_result、deep_think、answer_content、followup_questions
"""

import json
import sys
from typing import Dict, List, Any, Optional
import traceback
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font


def extract_tool_info(step: Dict[str, Any]) -> Optional[str]:
    """从 TOOL_EXECUTION 的 step 中提取 function 名称"""
    if step.get("type") == "TOOL_EXECUTION":
        # tool_result = step.get("step", {}).get("TOOL_RESULT", {})
        # input_data = tool_result.get("input", {}) if tool_result else {}
        # function_data = input_data.get("function", {}) if input_data else {}
        # return function_data.get("name"), function_data.get("arguments")
        content = step.get("step", {}).get("CONTENT", "")
        tool_name = content.split(": ")[0]
        return tool_name, ""
    return None, None


def extract_tool_result(step: Dict[str, Any]) -> Optional[str]:
    """从 TOOL_EXECUTION 的 step 中提取 output 中的 text"""
    if step.get("type") == "TOOL_EXECUTION":
        tool_result = step.get("step", {}).get("TOOL_RESULT", {})
        output_data = tool_result.get("output", []) if tool_result else []
        if output_data and len(output_data) > 0:
            return output_data[0].get("text")
    return None


def extract_content(step: Dict[str, Any]) -> Optional[str]:
    """从 ANSWER_RESPONSE 的 step 中提取 CONTENT，优先使用 CONTENT_CORRECTION"""
    if step.get("type") == "ANSWER_RESPONSE":
        step_data = step.get("step", {})
        # 优先使用 CONTENT_CORRECTION，如果没有则使用 CONTENT
        content = step_data.get("CONTENT_CORRECTION") or step_data.get("CONTENT")
        return content
    return None


def extract_followup_suggestions(step: Dict[str, Any]) -> Optional[str]:
    """从 QUERY_FOLLOWUP_SUGGESTIONS 的 step 中提取 CONTENT"""
    if step.get("type") == "QUERY_FOLLOWUP_SUGGESTIONS":
        step_data = step.get("step", {})
        content = step_data.get("CONTENT")
        if isinstance(content, list):
            # 如果是列表，用分号连接
            return "\n".join(content)
        return content
    return None


def extract_deep_think(step: Dict[str, Any]) -> Optional[str]:
    """从 DEEP_THINK 的 step 中提取 CONTENT，优先使用 CONTENT_CORRECTION"""
    if step.get("type") == "DEEP_THINK":
        step_data = step.get("step", {})
        # 优先使用 CONTENT_CORRECTION，如果没有则使用 CONTENT
        content = step_data.get("CONTENT_CORRECTION") or step_data.get("CONTENT")
        return content
    return None


def sanitize_sheet_name(name: str) -> str:
    """清理工作表名称，确保符合 Excel 要求"""
    # Excel 工作表名称不能包含: \ / ? * [ ]
    invalid_chars = ['\\', '/', '?', '*', '[', ']']
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Excel 工作表名称最大长度为 31
    if len(name) > 31:
        name = name[:31]
    # 如果名称为空，使用默认名称
    if not name:
        name = "Sheet"
    return name


def process_qa_data(qa_data: Dict[str, Any]) -> Dict[str, Any]:
    """处理单个 QA 数据，提取所需字段"""
    result = {
        "query": qa_data.get("query", ""),
        "agentType": qa_data.get("agentType", ""),
        "sessionId": qa_data.get("sessionId", ""),
        "qaId": qa_data.get("qaId", ""),
        "tool_name": "",
        "tool_args": "",
        "tool_result": "",
        "deep_think": "",
        "answer_content": "",
        "followup_questions": "",
    }
    
    # 处理 answer 数组
    answer_list = qa_data.get("answer", [])
    for answer_item in answer_list:
        if not isinstance(answer_item, dict):
            continue
            
        # 提取 TOOL_EXECUTION 相关数据
        tool_info = extract_tool_info(answer_item)
        if tool_info[0]:
            result["tool_name"] = tool_info[0]
            result["tool_args"] = tool_info[1]
            
        tool_result = extract_tool_result(answer_item)
        if tool_result:
            result["tool_result"] = tool_result
            
        # 提取 ANSWER_RESPONSE 的 CONTENT
        content = extract_content(answer_item)
        if content:
            result["answer_content"] = content
            
        # 提取 DEEP_THINK 的 CONTENT
        deep_think = extract_deep_think(answer_item)
        if deep_think:
            result["deep_think"] = deep_think
            
        # 提取 QUERY_FOLLOWUP_SUGGESTIONS 的 CONTENT
        followup_questions = extract_followup_suggestions(answer_item)
        if followup_questions:
            result["followup_questions"] = followup_questions
    
    return result


def main():
    """主函数"""
    input_file = "line_num_id_mapping_with_result.json"
    output_file = "extracted_data.xlsx"
    
    try:
        # 读取 JSON 文件
        print(f"正在读取 {input_file}...")
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 按 tool_name 分组，并保存 key 值用于排序
        # 结构: {tool_name: [(key, processed_data), ...]}
        grouped_data = defaultdict(list)
        print("正在处理数据...")
        
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            
            tool_name = value.get("tool_name", "UNKNOWN")
            # 获取 qaList
            qa_list = value.get("data", {}).get("qaList", [])
            
            for qa_item in qa_list:
                processed_data = process_qa_data(qa_item)
                # 将 key 转换为整数用于排序，如果转换失败则使用字符串比较
                try:
                    key_int = int(key)
                except ValueError:
                    key_int = float('inf')  # 非数字key放在最后
                grouped_data[tool_name].append((key_int, processed_data))
        
        # 对每个 tool_name 的数据按 key 排序
        for tool_name in grouped_data:
            grouped_data[tool_name].sort(key=lambda x: x[0])
        
        # 创建 Excel 工作簿
        print(f"正在写入 {output_file}...")
        wb = Workbook()
        # 删除默认工作表
        wb.remove(wb.active)
        
        fieldnames = ["query", "agentType", "sessionId", "qaId", "tool_name", "tool_args", "tool_result", "deep_think", "answer_content", "followup_questions"]
        
        total_records = 0
        # 为每个 tool_name 创建一个工作表
        for tool_name in sorted(grouped_data.keys()):
            sheet_name = sanitize_sheet_name(tool_name)
            ws = wb.create_sheet(title=sheet_name)
            
            # 写入表头
            header_font = Font(bold=True)
            for col_idx, fieldname in enumerate(fieldnames, start=1):
                cell = ws.cell(row=1, column=col_idx, value=fieldname)
                cell.font = header_font
            
            # 写入数据
            row_idx = 2
            for _, processed_data in grouped_data[tool_name]:
                for col_idx, fieldname in enumerate(fieldnames, start=1):
                    value = processed_data.get(fieldname, "")
                    ws.cell(row=row_idx, column=col_idx, value=value)
                row_idx += 1
                total_records += 1
            
            # 自动调整列宽
            for col_idx in range(1, len(fieldnames) + 1):
                column_letter = get_column_letter(col_idx)
                max_length = 0
                for row in ws[column_letter]:
                    try:
                        if row.value:
                            max_length = max(max_length, len(str(row.value)))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)  # 最大宽度限制为50
                ws.column_dimensions[column_letter].width = adjusted_width
        
        # 保存 Excel 文件
        wb.save(output_file)
        
        print(f"成功处理 {total_records} 条记录，输出到 {output_file}")
        print(f"共创建 {len(grouped_data)} 个工作表，按 tool_name 分组")
        
    except FileNotFoundError:
        print(f"错误：找不到文件 {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误：JSON 解析失败 - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误：{e}, {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()