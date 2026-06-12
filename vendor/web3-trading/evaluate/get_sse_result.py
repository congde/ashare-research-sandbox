#!/usr/bin/env python3
"""
批量测试脚本
从算法数据集.xlsx中读取所有查询，向API发送请求并保存流式响应结果
"""

import os
import json
import time
import random
import requests
from pathlib import Path
from tqdm import tqdm
from uuid import uuid4
import pandas as pd
import openpyxl
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# API配置
# API_URL = "http://127.0.0.1:10240/api/chat/query"
# API_URL = "https://www.kucoin.plus/_api/kia/app/v1/chat/query"
API_URL = "https://www.kucoin.com/_api/kia/sse/chat/query?c=d77edeedf99b49f281c5155a8e8831b0&lang=zh_HK"

HEADERS = {
  'Cookie': 'x-visited=true; X_GRAY_TEMP_UUID=53fc94c0-076d-40f5-8365-58f84ccbf3cb; smidV2=202506261737327fb95f1f2a80c482d467a11adb49f992000b08aab7fa4f920; _fbp=fb.1.1750930670708.536132945; X-TRACE=k41J62m142wvKyVWBOgDeNJuV+xEf41StP40DAUMqGQ=; _cfuvid=eH3Kk7x3geSDma_C3gZOVF55S8DdzH8qHW8c0KR8gCg-1753182077615-0.0.1.1-604800000; kc_theme=light; _tea_utm_cache_586864={%22utm_source%22:%22cloud_mining%22}; _uetvid=39bd3270527111f0939149a6b51b5691; _gcl_au=1.1.450088660.1758800628; rtg_usr=v1.0:17513820779:1751625728939:1761899915701; cslfp=eyJ1dWlkQ2xpZW50IjoiZjJmMDA2NjItNmM5Ni00ZDZmLWJlNDEtYjkyMjg5ZGViYWM5Iiwia2V5IjoiOWQwOWZkOTE0MWNmOTA2NjRiNWZjY2FjYjUwY2NmYWI0YjFmNmM1ZTczZGFiYzcxZjI4MzlhZWE5MmViOTYxYiJ9; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%22248403857%22%2C%22first_id%22%3A%22197ab9978f62e11-0b090f618dcd028-17525636-1405320-197ab9978f73879%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%2C%22%24latest_utm_source%22%3A%22cloud_mining%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk3YWI5OTc4ZjYyZTExLTBiMDkwZjYxOGRjZDAyOC0xNzUyNTYzNi0xNDA1MzIwLTE5N2FiOTk3OGY3Mzg3OSIsIiRpZGVudGl0eV9sb2dpbl9pZCI6IjI0ODQwMzg1NyJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%22248403857%22%7D%2C%22%24device_id%22%3A%22198456b269d27c9-0e37e7d6fbdb328-17525636-1405320-198456b269e3cd5%22%7D; _gid=GA1.2.1148325134.1764252999; WEBGRAY=beta_web:seo-cms-web-ssr.customer-web-ssr.public-web.ucenter-web-private-ssr; g_state={"i_l":0,"i_ll":1764310765901,"i_b":"Lg7KcIG38GZXP/JjiGk7d1ExuOhgpFslofVSX1JbNTU"}; AWSALB=m5nqcK+nO/b87+vhLbJltr8CxusqKk08imkn86uNcpNjZ18VmZdSChKn9v2ltRG4Hh7z+a35Kwc1QimCD/yslgQwZ/87HOEagcdv9mIFdtCrzV9j4dUoUCNHzOkL; AWSALBCORS=m5nqcK+nO/b87+vhLbJltr8CxusqKk08imkn86uNcpNjZ18VmZdSChKn9v2ltRG4Hh7z+a35Kwc1QimCD/yslgQwZ/87HOEagcdv9mIFdtCrzV9j4dUoUCNHzOkL; SESSION=NzljYTUyMjQtZDNkNy00MTMwLThhN2YtZTgyZDJiNjdmODg0; JSESSIONID=DCFF7A406BB3DA90A1FA19E20278EDDF; __cf_bm=3hikVM66rRC7jSZP7Q3imDNOVYN__c1z3ZSik8DPKrM-1764312521-1.0.1.1-kPQVoHXBiIliD2U1S.mVGTxLvOww18BQFzNGaaBzzMgZao.PBwHzdTf.fSqoNa.8Y.synbL66NXfMBQLAg7HkOybdjr1h1katITDeMgZF4M; cf_clearance=58yBHSxzYb4zYkA6ZGn3mDPkw1iULkRIjjaDb.Kgm4Q-1764312522-1.2.1.1-Q1sfL7wek6OQeeiCgQyXEMTIwVuyh3BzbbjoAeh3Nubmw.OoKrb1Dr5X7Y67ceNU48H6XPi1wWGB_lAzZDvRTPSb7Bc6FMEzLtaNFZzKbi8.drzuIfLWwHBe5QPqi5U2rMJVSh.Kaujpgc43oKLxOrnsXVxBIWtCkBH4l06x6yYRXuqsPnitlYdpkdxR_VzGAAQl7T08xV.FBFXQ.b1MHudqEokory46Uv9FqcYoDSo; X-GRAY=xgray-market-operation-11-15&xgray-kcop1127&xgray-kcmg-20251127; X_GRAY_TMP=1764312347597; .thumbcache_c294bfec3668b22bff5f6aa9bb528f6a=xT4nWlM1hmGu5J+BYbU+Rhe2W2Kx7RNXLtD5gwe6zKeabHdYqhdITuAAMBGbZZSOWwu2ovZqgoQJR9vcKpFKkg%3D%3D; _ga=GA1.1.1364451098.1761109746; _ga_YHWW24NNH9=GS2.1.s1764310793$o9$g1$t1764312526$j60$l0$h0',
  'Content-Type': 'application/json'
}


# 输出目录
RESULTS_DIR = Path("./sse_results")
LINE_NUM_ID_MAPPING_FILE = "./line_num_id_mapping.json"

def ensure_directories():
    """确保输出目录存在"""
    RESULTS_DIR.mkdir(exist_ok=True)

def read_queries():
    """从Excel文件中读取查询，支持多个工作表"""
    queries = []
    excel_file = "../data/Kia0.7效果评估数据集.xlsx"
    
    if not os.path.exists(excel_file):
        raise FileNotFoundError(f"Excel文件不存在: {excel_file}")
    
    # 打开Excel文件获取所有工作表
    wb = openpyxl.load_workbook(excel_file)
    
    # 假设第一列是query，如果需要可以从其他列读取
    # 遍历所有工作表
    for sheet_name in wb.sheetnames:
        # 读取工作表数据
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        
        # 查找包含query的列（可能是 'query', 'Query', '问题', '问题内容' 等）
        query_column = None
        for col in df.columns:
            col_lower = str(col).lower()
            if 'query' in col_lower or '问题' in str(col) or 'question' in col_lower:
                query_column = col
                break
        
        # 如果没找到，使用第一列
        if query_column is None:
            query_column = df.columns[0]
        
        # 读取查询数据
        for idx, row in df.iterrows():
            query = str(row[query_column]).strip()
            if query and query != 'nan':  # 跳过空值和NaN
                # 使用工作表名称作为tool_name
                queries.append({
                    'line_num': len(queries) + 1,  # 全局行号
                    'query': query,
                    'tool_name': sheet_name,
                    'sheet_row': idx + 2  # Excel中的行号（从2开始，因为第1行是标题）
                })
    
    return queries

def sanitize_filename(query, tool_name, line_num):
    """将查询转换为安全的文件名，格式：{tool_name}_{query}"""
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    
    # 清理tool_name
    sanitized_tool_name = ""
    for char in tool_name:
        if char in safe_chars:
            sanitized_tool_name += char
        elif char == " ":
            sanitized_tool_name += "_"
        else:
            sanitized_tool_name += "_"
    
    # 清理query部分
    sanitized_query = ""
    for char in query:
        if char in safe_chars:
            sanitized_query += char
        elif char == " ":
            sanitized_query += "_"
        else:
            sanitized_query += "_"
    
    # 限制query部分长度
    if len(sanitized_query) > 100:
        sanitized_query = sanitized_query[:100]
    
    # 如果query部分为空或太短，使用行号
    if len(sanitized_query) < 5:
        sanitized_query = f"query_{line_num}"
    
    # 格式：{tool_name}_{query}
    return f"{sanitized_tool_name}_{sanitized_query}"

def send_query(query):
    """发送单个查询请求"""
    # 按照7:3的比例随机选择agentType
    agentType = random.choices(['QUICK_REASONING', 'DEEP_THINK'], weights=[7, 3])[0]
    
    payload = {
        "query": query,
        "agentType": agentType,
        "extraBody": {},
        "sessionId": uuid4().hex,
        "language": "zh_HK"
    }
    
    try:
        response = requests.post(
            API_URL,
            headers=HEADERS,
            json=payload,
            stream=True,
            timeout=60
        )
        response.raise_for_status()
        return response, agentType
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None, None

def process_streaming_response(response, output_file):
    """处理流式响应并保存到文件"""
    session_id = None
    qa_id = None
    all_data = []

    try:
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith('data:'):
                data_str = line[5:]  # 移除 'data:' 前缀
                try:
                    data = json.loads(data_str)
                    all_data.append(data)

                    # 提取sessionId
                    if session_id is None and 'sessionId' in data:
                        session_id = data['sessionId']
                    
                    # 提取qaId
                    if qa_id is None and 'qaId' in data:
                        qa_id = data['qaId']
                        
                except json.JSONDecodeError as e:
                    print(f"JSON解析错误: {e}, 数据: {data_str}")
                    continue
    
    except Exception as e:
        print(f"处理流式响应时出错: {e}")
    
    # 保存所有数据到文件
    with open(output_file, 'w', encoding='utf-8') as f:
        for data in all_data:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')
    
    return session_id, qa_id

def process_single_query(query_info, index, lock, line_num_id_mapping, pbar):
    """处理单个查询（用于并发执行）"""
    line_num = query_info['line_num']
    query = query_info['query']
    tool_name = query_info['tool_name']
    
    try:
        # 发送请求
        response, agentType = send_query(query)
        if response is None:
            with lock:
                pbar.update(1)
            return {'success': False, 'line_num': line_num}
        
        # 生成输出文件名，包含tool_name前缀
        filename = sanitize_filename(query, tool_name, line_num)
        output_file = RESULTS_DIR / f"{index}_{filename}.txt"
        
        # 处理流式响应
        session_id, qa_id = process_streaming_response(response, output_file)
        
        result = {'success': False, 'line_num': line_num}
        if session_id:
            with lock:
                line_num_id_mapping[str(line_num)] = {
                    "query": query,
                    "agentType": agentType,
                    "sessionId": session_id,
                    "qaId": qa_id,
                    "tool_name": tool_name
                }
                result['success'] = True
                result['qa_id'] = qa_id
                result['tool_name'] = tool_name
        
        with lock:
            pbar.update(1)
        
        return result
    except Exception as e:
        print(f"处理查询 {line_num} 时出错: {e}")
        with lock:
            pbar.update(1)
        return {'success': False, 'line_num': line_num, 'error': str(e)}

def main():
    """主函数"""
    print("开始批量测试...")
    
    # 确保目录存在
    ensure_directories()
    
    # 读取查询
    queries = read_queries()
    print(f"共读取到 {len(queries)} 个查询")
    
    line_num_id_mapping = {}  # 改为字典存储，key是line_num，value是query, sessionId, qaId, tool_name
    success_count = 0
    failed_count = 0
    lock = threading.Lock()
    
    # 使用tqdm显示进度条
    with tqdm(total=len(queries), desc="处理查询", unit="个") as pbar:
        # 使用线程池，最大并发数为10
        with ThreadPoolExecutor(max_workers=10) as executor:
            # 提交所有任务
            future_to_query = {
                executor.submit(process_single_query, query_info, i+1, lock, line_num_id_mapping, pbar): query_info
                for i, query_info in enumerate(queries)
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_query):
                query_info = future_to_query[future]
                try:
                    result = future.result()
                    if result.get('success'):
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    print(f"任务执行异常: {e}")
                    failed_count += 1
    
    # 保存qaId映射到JSON文件
    with open(LINE_NUM_ID_MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump(line_num_id_mapping, f, ensure_ascii=False, indent=4)
    
    print(f"\n批量测试完成!")
    print(f"成功: {success_count}")
    print(f"失败: {failed_count}")
    print(f"line_num_id_mapping已保存到: {LINE_NUM_ID_MAPPING_FILE}")
    print(f"结果文件保存在: {RESULTS_DIR}")

if __name__ == "__main__":
    main()