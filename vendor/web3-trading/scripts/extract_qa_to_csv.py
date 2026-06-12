# -*- coding: utf-8 -*-
"""
脚本说明：
    从导出的kia_qa JSON文件中提取query和answer_response，保存到CSV文件。

提取规则：
    1. 提取query字段
    2. 从answer数组中找到type为"ANSWER_RESPONSE"的元素
    3. 优先取step.CONTENT_CORRECTION，如果没有则取step.CONTENT

使用方式：
    cd /Users/charles/workspace/ai-web3-tradding-agent
    .venv/bin/python scripts/extract_qa_to_csv.py <json文件路径>
    
示例：
    .venv/bin/python scripts/extract_qa_to_csv.py scripts/kia_qa_export_20251219_151628.json
"""

import json
import csv
import argparse
from pathlib import Path


def load_json(json_path):
    """加载JSON文件"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_answer_response(answer_list):
    """
    从answer数组中提取ANSWER_RESPONSE的内容
    优先取CONTENT_CORRECTION，如果没有则取CONTENT
    """
    for answer in answer_list:
        if answer.get("type") == "ANSWER_RESPONSE":
            step = answer.get("step", {})
            # 优先取CONTENT_CORRECTION
            content_correction = step.get("CONTENT_CORRECTION")
            if content_correction:
                return content_correction
            # 否则取CONTENT
            content = step.get("CONTENT")
            if content:
                return content
    return ""


def extract_qa_data(records):
    """从记录中提取query和answer_response"""
    results = []
    for record in records:
        query = record.get("query", "").strip()
        answer_list = record.get("answer", [])
        answer_response = extract_answer_response(answer_list)
        
        if query and answer_response:
            results.append({
                "query": query,
                "answer_response": answer_response
            })
    return results


def save_to_csv(data, output_path):
    """保存数据到CSV文件（utf_8_sig编码）"""
    with open(output_path, 'w', encoding='utf_8_sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["query", "answer_response"])
        writer.writeheader()
        writer.writerows(data)
    print(f"成功保存 {len(data)} 条记录到 {output_path}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="从kia_qa JSON文件中提取query和answer_response到CSV"
    )
    parser.add_argument(
        "json_file",
        type=str,
        help="输入的JSON文件路径"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="输出的CSV文件路径（默认与输入文件同名，扩展名改为.csv）"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # 处理输入文件路径
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"✗ 错误：文件不存在 - {json_path}")
        return
    
    # 脚本所在目录
    script_dir = Path(__file__).parent
    
    # 确定输出文件路径（默认放到脚本目录）
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = script_dir / json_path.with_suffix('.csv').name
    
    print("=" * 60)
    print("开始提取数据...")
    print(f"输入文件: {json_path}")
    print(f"输出文件: {output_path}")
    print("=" * 60)
    
    # 加载JSON
    print("\n正在加载JSON文件...")
    records = load_json(json_path)
    print(f"✓ 加载了 {len(records)} 条记录")
    
    # 提取数据
    print("\n正在提取query和answer_response...")
    qa_data = extract_qa_data(records)
    print(f"✓ 成功提取 {len(qa_data)} 条有效数据")
    
    # 保存到CSV
    print("\n正在保存到CSV文件...")
    save_to_csv(qa_data, output_path)
    
    print("\n" + "=" * 60)
    print("提取完成！")
    print(f"  - 输入记录数: {len(records)}")
    print(f"  - 输出记录数: {len(qa_data)}")
    print(f"  - 输出文件: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
