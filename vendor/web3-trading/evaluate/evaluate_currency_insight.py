import asyncio
import logging
import os
import sys
import re

import json_repair
import pandas as pd
from tqdm import tqdm
from pydantic import BaseModel

base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(base_path, "src"))

from web.application import source_env
source_env("local")

from agent.currency_insight import create_currency_insight_workflow
from llm.llm import DefaultLLM


logger = logging.getLogger(__name__)
currency_insight_graph = create_currency_insight_workflow()
llm = DefaultLLM(
    base_url=os.getenv("deepseek_base_url"),   
    api_key=os.getenv("deepseek_api_key"),
    default_model_name="deepseek-v4-flash"
)

# 内容相关性
relevance_system_prompt = """
# 你是一个专业投资分析专家，你需要根据用户给定的内容，判断该内容是否与给定的主题相关。

# 具体评估规则如下：
keyPoints: 市场表现类，只评估val字段的值是否和市场表现相关且合理；
pricePerformance: 价格表现类，只评估val字段的值是否和价格表现相关且合理
technicalIndicators: 技术指标类，只评估technicalIndicators.val列表里的val字段的值是否和技术指标相关且合理；
opportunitySummary: 机会分析总结类，只评估opportunitySummary.val列表里的val字段的值是否和机会分析相关且合理；
marketSentiment: 市场情绪类，只评估marketSentiment.val列表里的val列表字段的值是否和市场情绪相关且合理；

以上规则评估合理性只要满足该类别主题即可，不做严格的扩展要求，如价格表现里面还增加了技术指标分析，这算是合理的

# 输出JSON数据格式（当不相关时reason字段才有内容，否则reason字段为空字符串）：
{"is_relevant": bool,"reason": str}
"""

digital_system_prompt = """
# 你是一个专业投资分析专家，你需要根据用户给定的内容，判断该内容中的数值类型信息与工具返回结果中的数值信息是否一致，如果是四舍五入的情况认为是一致的。

# 输出JSON数据格式（当不一致时reason字段才有内容，否则reason字段为空字符串）：
{"is_consistent": bool, "reason": str}
"""



class ContentRelevanceEvaluator(BaseModel):
    is_relevant: bool
    reason: str


async def initialize():
    from libs.eureka import eureka
    await eureka.up()
    from mcp.mcp_http_client import mcp_client
    await mcp_client.initialize()


async def fetch_one(symbol, market_type):
    resp = await currency_insight_graph.ainvoke({
        "symbol": symbol,
        "market_type": market_type,
        "source": "currency_insights",
        "extra": {},
        "status": "Ok",
        "reason": ""
    })
    # assert resp.get("format_ok"), f"Response format error for {symbol} in {market_type}"
    return resp


async def main():
    await initialize()

    tasks = []
    for _ in range(20):
        for symbol in "KCS，BTC，ETH，BNB，XRP，SOL，TRX，DOGE，ADA，BCH，XLM，ASTER，HYPE".split("，"):
            for market_type in ["spot", "future"]:
                tasks.append(fetch_one(symbol, market_type))

    is_error = 0
    batch_size = 20
    output_file = "currency_insight_results.csv"
    columns = ['symbol', 'market_type', 'source', 'tool_calls', 'tool_results', 'insight_data', 'messages', 'format_ok']
    for i in tqdm(range(0, len(tasks), batch_size), desc="Processing batches", total=(len(tasks) + batch_size - 1) // batch_size):
        batch = tasks[i:i + batch_size]
        results = await asyncio.gather(*batch, return_exceptions=True)
        
        evaluate_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in task: {result}")
                is_error += 1
                pattern = r"symbol:\s*(\w+),\s*market_type:\s*(\w+)"
                match = re.search(pattern, str(result))
                if match:
                    symbol = match.group(1)
                    market_type = match.group(2)
                    result = {k: None for k in columns}
                    result.update({"symbol": symbol, "market_type": market_type, "source": "currency_insights", "format_ok": False, "error": str(result)})
                else:
                    result = {k: None for k in columns}
                    result.update({"source": "currency_insights", "format_ok": False, "error": str(result)})
                result["status"] = "Failed"
            elif result.get("status", "") != "Ok":
                is_error += 1
                resp = result.get("insight_data", {})
                result["error"] = result.get("reason")
                result["status"] = "Failed"
            else:
                # 检测字段缺失
                resp = result.get("insight_data", {})
                if len(resp.get("keyPoints", [])) < 1:
                    is_error += 1
                    result["error"] = "Missing keyPoints"
                    result["format_ok"] = False
                    result["status"] = "Failed"
                elif len(resp.get("technicalIndicators", {}).get("val", [])) < 1:
                    is_error += 1
                    result["error"] = "Missing technicalIndicators"
                    result["format_ok"] = False
                    result["status"] = "Failed"
                elif len(resp.get("opportunitySummary", {}).get("val", [])) < 1:
                    is_error += 1
                    result["error"] = "Missing opportunitySummary"
                    result["format_ok"] = False
                    result["status"] = "Failed"
                elif not result.get("format_ok", False):
                    is_error += 1
                    result["error"] = "LLM Format not OK"
                    result["format_ok"] = False
                    result["status"] = "Failed"
                else:
                    result["error"] = ""

                if result.get("error", ""):
                    evaluate_results.append(result)
                    continue

                # 评估字段内容：字段内容跟字段key相关，不相关or模型幻觉为不通过
                content_resp = {
                    "keyPoints": resp.get("keyPoints", []),
                    "pricePerformance": resp.get("pricePerformance", []),
                    "technicalIndicators": resp.get("technicalIndicators", {}),
                    "opportunitySummary": resp.get("opportunitySummary", {}),
                    "marketSentiment": resp.get("marketSentiment", {})
                }
                content_result = await llm.ainvoke(
                    messages=[
                        {"role": "system", "content": relevance_system_prompt},
                        {"role": "user", "content": str(content_resp)}
                    ]
                )
                content_result = json_repair.loads(content_result.content)
                if not content_result.get("is_relevant"):
                    is_error += 1
                    result["error"] = content_result.get("reason", "Content evaluation failed")
                    result["format_ok"] = False
                    result["status"] = "Failed"
                    evaluate_results.append(result)
                    continue

                # 评估字段真实性：字段内容数值需跟机会分析工具返回内容一致，不一致为不通过
                content_result = await llm.ainvoke(
                    messages=[
                        {"role": "system", "content": digital_system_prompt},
                        {"role": "user", "content": f"工具返回数值信息：{result.get('tool_results', [])}\n\n字段内容数值信息：{content_resp}"}
                    ]
                )
                content_result = json_repair.loads(content_result.content)
                if not content_result.get("is_consistent"):
                    is_error += 1
                    result["error"] = content_result.get("reason", "Digital consistency evaluation failed")
                    result["format_ok"] = False
                    result["status"] = "Failed"

            evaluate_results.append(result)
        
        results_df = pd.DataFrame(evaluate_results)
        file_exists = os.path.exists(output_file)
        with open(output_file, 'a') as f:
            results_df.to_csv(f, header=not file_exists, index=False, encoding='utf-8')
        
    print(f"Total: {len(tasks)}, Error Rate: {is_error / len(tasks):.2%}")


if __name__ == "__main__":
    asyncio.run(main())