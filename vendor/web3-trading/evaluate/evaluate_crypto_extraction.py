# -*- coding: utf-8 -*-
"""
评测 crypto_extractor.py 对 CSV 测试用例的币种提取准确率
使用 LLM 进行币种提取
"""

import csv
import json
import sys
import os
import asyncio
from typing import List

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openai import AsyncOpenAI
from httpx import AsyncClient
from src.libs.crypto_extractor import CryptoExtractor


# LLM 配置
LLM_API_BASE = os.environ.get("OPENAI_API_BASE", "https://litellm-ali.sit.kucoin.net/")
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen3.5-27B")


def load_test_cases(csv_path: str) -> list:
    """加载测试用例"""
    test_cases = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig 处理 BOM
        reader = csv.DictReader(f)
        for row in reader:
            query = row['query']
            answer_response = row.get('answer_response', '')

            expected_output = json.loads(row['expected'])
            test_cases.append({
                'query': query,
                'answer_response': answer_response,
                'expected': expected_output
            })
    return test_cases


async def evaluate_with_llm(
    extractor: CryptoExtractor,
    llm: AsyncOpenAI,
    model: str,
    test_cases: list
) -> dict:
    """使用 LLM 评测提取准确率"""
    total = len(test_cases)
    exact_match = 0  # 完全匹配
    partial_match = 0  # 部分匹配（预测和期望有交集）
    false_positive = 0  # 误报（预测了但不应该预测）
    false_negative = 0  # 漏报（应该预测但没预测）
    
    detailed_results = []
    
    for i, case in enumerate(test_cases):
        query = case['query']
        answer_response = case['answer_response']
        expected = set(case['expected'])
        
        # 使用 LLM 提取
        try:
            predicted_list = await extractor.extract_with_llm(
                llm=llm,
                model=model,
                query=query,
                response=answer_response,
                temperature=0.0
            )
            predicted = set(predicted_list)
        except Exception as e:
            print(f"Error extracting [{i+1}]: {e}")
            predicted = set()
        
        # 计算匹配情况
        is_exact_match = (predicted == expected)
        intersection = predicted & expected
        fp = predicted - expected  # 预测了但不在期望中
        fn = expected - predicted  # 期望中但没预测
        
        if is_exact_match:
            exact_match += 1
            status = "✅ EXACT"
        elif intersection:
            partial_match += 1
            status = "⚠️ PARTIAL"
        elif not expected and not predicted:
            exact_match += 1
            status = "✅ EXACT (both empty)"
        else:
            status = "❌ MISMATCH"
        
        if fp:
            false_positive += len(fp)
        if fn:
            false_negative += len(fn)
        
        result = {
            'index': i + 1,
            'query': query,
            'answer_response': answer_response,
            'expected': sorted(expected),
            'predicted': sorted(predicted),
            'status': status,
            'false_positives': sorted(fp),
            'false_negatives': sorted(fn)
        }
        detailed_results.append(result)
        
        # 实时打印每条 case 的结果
        print(f"[{i+1}/{total}] {status}")
        print(f"  Query: {result['query']}")
        print(f"  Expected:  {result['expected']}")
        print(f"  Predicted: {result['predicted']}")
        if fp:
            print(f"  FP (extra): {sorted(fp)}")
        if fn:
            print(f"  FN (missed): {sorted(fn)}")
        print()
    
    return {
        'total': total,
        'exact_match': exact_match,
        'partial_match': partial_match,
        'exact_match_rate': exact_match / total * 100,
        'partial_or_exact_rate': (exact_match + partial_match) / total * 100,
        'false_positives': false_positive,
        'false_negatives': false_negative,
        'detailed_results': detailed_results
    }


def print_report(results: dict):
    """打印评测报告"""
    print("=" * 80)
    print("📊 Crypto Extraction Evaluation Report")
    print("=" * 80)
    print(f"\n📈 Overall Statistics:")
    print(f"  Total test cases: {results['total']}")
    print(f"  Exact matches: {results['exact_match']} ({results['exact_match_rate']:.2f}%)")
    print(f"  Partial matches: {results['partial_match']}")
    print(f"  Exact + Partial rate: {results['partial_or_exact_rate']:.2f}%")
    print(f"  False positives (extra predictions): {results['false_positives']}")
    print(f"  False negatives (missed predictions): {results['false_negatives']}")
    
    # 只显示失败的 case
    failed_cases = [r for r in results['detailed_results'] if '✅' not in r['status']]
    if failed_cases:
        print("\n" + "=" * 80)
        print("❌ Failed Cases (Non-exact matches):")
        print("=" * 80)
        
        for r in failed_cases:
            print(f"\n[{r['index']}] {r['status']}")
            print(f"  Query: {r['query']}")
            print(f"  Expected: {r['expected']}")
            print(f"  Predicted: {r['predicted']}")
            if r['false_positives']:
                print(f"  FP (extra): {r['false_positives']}")
            if r['false_negatives']:
                print(f"  FN (missed): {r['false_negatives']}")
    
    print("\n" + "=" * 80)
    print(f"Summary: {results['exact_match']}/{results['total']} exact matches ({results['exact_match_rate']:.2f}%)")
    print("=" * 80)


async def main():
    # 加载测试用例
    csv_path = os.path.join(os.path.dirname(__file__), '币种提取评测集 - 整体测试结果.csv')
    print(f"Loading test cases from: {csv_path}")
    test_cases = load_test_cases(csv_path)
    print(f"Loaded {len(test_cases)} test cases")
    
    # 初始化 LLM 客户端
    print(f"\nLLM Config:")
    print(f"  API Base: {LLM_API_BASE}")
    print(f"  Model: {LLM_MODEL}")
    
    llm = AsyncOpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_API_BASE,
        timeout=60.0,
        http_client=AsyncClient(verify=False)
    )
    
    # 初始化提取器
    extractor = CryptoExtractor()
    
    # 执行评测
    print("\nRunning evaluation with LLM...")
    results = await evaluate_with_llm(extractor, llm, LLM_MODEL, test_cases)
    
    # 打印报告
    print_report(results)
    
    # 保存详细结果到 JSON 文件
    output_json_path = os.path.join(os.path.dirname(__file__), 'crypto_extraction_eval_result.json')
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {output_json_path}")
    
    # 保存详细结果到 CSV 文件
    output_csv_path = os.path.join(os.path.dirname(__file__), 'crypto_extraction_eval_result.csv')
    with open(output_csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        # 写入表头
        writer.writerow(['index', 'query', 'answer_response', 'expected', 'predicted', 'status', 'false_positives', 'false_negatives'])
        # 写入每条记录
        for r in results['detailed_results']:
            writer.writerow([
                r['index'],
                r['query'],
                r['answer_response'],
                json.dumps(r['expected'], ensure_ascii=False),
                json.dumps(r['predicted'], ensure_ascii=False),
                r['status'],
                json.dumps(r['false_positives'], ensure_ascii=False),
                json.dumps(r['false_negatives'], ensure_ascii=False)
            ])
    print(f"CSV results saved to: {output_csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
