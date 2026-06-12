#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File    :   kia_chat_query.py
@Time    :   2025/09/16 15:48:17
@Desc    :   全流程压测场景
'''

# here put the import lib

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locust import HttpUser, task, events, constant_throughput
import time
import json
import os
import pandas as pd
import random
import queue
import traceback
import urllib3
import logging
from pathlib import Path
from datetime import datetime
import csv
import uuid


timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

# 创建logs目录
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

# 配置日志
def setup_logging():
    """配置日志输出到当前目录的logs文件夹"""
    
    # 生成带时间戳的日志文件名
    log_file = log_dir / f"stress_test_{timestamp}.log"
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # 创建独立的logger（不使用root logger）
    custom_logger = logging.getLogger('stress_test')
    custom_logger.setLevel(logging.INFO)
    # 避免日志传播到root logger
    custom_logger.propagate = False
    
    # 如果已经有handlers，不要重复添加
    if not custom_logger.handlers:
        # 添加文件处理器
        custom_logger.addHandler(file_handler)
        # 打印日志文件路径到控制台
        print(f"📝 日志文件: {log_file}")
    
    return custom_logger

# 不在模块级别初始化logger，而是在Locust初始化时
logger = None

def get_logger():
    """获取logger实例，如果不存在则创建"""
    global logger
    if logger is None:
        logger = setup_logging()
    return logger

# 禁用不安全请求的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 创建队列
QUICK_REASONING_Q = queue.Queue()
DEEP_THINK_Q = queue.Queue()
DEEP_RESEARCH_Q = queue.Queue()

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """初始化时读取 csv 数据"""
    global logger
    
    # 在Locust初始化时配置logger
    logger = setup_logging()
    logger.info("=" * 80)
    logger.info("Locust 压力测试开始初始化")
    logger.info("=" * 80)

    # 新建结果csv
    result_csv_path = log_dir / f"result_{timestamp}.csv"
    with open(result_csv_path, 'w', newline='', encoding='utf_8_sig') as f:
        writer = csv.writer(f)
        writer.writerow(["query", "agentType", "qaId", "request_start_time", "full_response_time", "first_token_time", "token_interval", "total_tokens", "error_msg"])

    try:
        # 读取csv文件
        csv_path = os.path.join(os.path.dirname(__file__), os.pardir, "data", "kia0.4压测数据-20251011.csv")
        logger.info(f"正在读取CSV文件: {csv_path}")
        df = pd.read_csv(csv_path)
        
        # 将数据保存到全局变量
        for _, row in df.iterrows():
            data = {
                "query": row['query'],
                "agentType": row['agentType']
            }
            if row['agentType'] == 'QUICK_REASONING':
                QUICK_REASONING_Q.put_nowait(data)
            elif row['agentType'] == 'DEEP_THINK':
                DEEP_THINK_Q.put_nowait(data)
            elif row['agentType'] == 'DEEP_RESEARCH':
                DEEP_RESEARCH_Q.put_nowait(data)
        
        logger.info("数据加载完成，各队列数据量：")
        logger.info(f"QUICK_REASONING队列: {QUICK_REASONING_Q.qsize()}条")
        logger.info(f"DEEP_THINK队列: {DEEP_THINK_Q.qsize()}条")
        logger.info(f"DEEP_RESEARCH队列: {DEEP_RESEARCH_Q.qsize()}条")
        logger.info(f"总计: {QUICK_REASONING_Q.qsize() + DEEP_THINK_Q.qsize() + DEEP_RESEARCH_Q.qsize()}条")
    except Exception as e:
        logger.error(f"读取csv文件失败: {e}")
        raise

def stream_processor(response, query: str, agent_type: str, request_start_time: float):
    """
    处理流式响应并计算相关指标

    Args:
        response: 响应对象
        query: 请求查询
        agent_type: 请求类型
        request_start_time: 请求开始时间
    """
    # 初始化统计信息
    all_token_data = []
    first_token_time = None
    full_response_time = 0
    token_timestamps = []
    total_tokens = 0
    error_msg = ''
    success_finish = False
    token_interval = 0  # 确保在所有分支中都有定义

    def fire_metrics():
        """内部函数：发送性能指标"""
        events.request.fire(
            request_type=f"{agent_type}/首Token耗时",
            name=f"{agent_type}/首Token耗时",
            response_time=first_token_time if first_token_time else 0,
            response_length=0,
            exception=error_msg,
            context={}
        )
        events.request.fire(
            request_type=f"{agent_type}/Token间耗时",
            name=f"{agent_type}/Token间耗时",
            response_time=token_interval,
            response_length=0,
            exception=error_msg,
            context={}
        )
        events.request.fire(
            request_type=f"{agent_type}/总请求耗时",
            name=f"{agent_type}/总请求耗时",
            response_time=full_response_time,
            response_length=0,
            exception=error_msg,
            context={}
        )

    try:
        get_logger().info(f"{agent_type} 收到响应，状态码: {response.status_code}")
        if response.status_code != 200:
            error_msg = f"{agent_type} HTTP错误: {response.status_code}"
            fire_metrics()
            response.failure(error_msg)
            return

        qaId = ""
        for line in response.iter_lines(decode_unicode=True, delimiter="\n"):
            # logger.info(line)
            if not isinstance(line, str):
                line = str(line)
            if not line or not line.strip() or line.startswith(": ping"):
                continue
            
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                token_data = json.loads(line)

                # 判断是否存在异常或者错误
                if 'status' in token_data and token_data['status'] == 'FAILED':
                    content = token_data.get('content')
                    error_log = token_data.get('log', '')
                    error_msg = f"{agent_type} 请求失败，content: {content}, log: {error_log}"
                    get_logger().error(f"{agent_type} 请求失败: {error_msg}")
                    break

                # 记录首token耗时和token间耗时
                if "content" in token_data:
                    delta_content = str(token_data["content"])
                    qaId = token_data.get('qaId', '')
                    if delta_content and len(delta_content.strip()) > 0:
                        total_tokens += 1
                        current_time = time.time()
                        token_timestamps.append(current_time)

                        if first_token_time is None:
                            first_token_time = (current_time - request_start_time) * 1000

                # 标记请求正常结束
                if 'status' in token_data and token_data['status'] == 'COMPLETED':
                    success_finish = True 
                    break

                all_token_data.append(line)
            except Exception as e:
                get_logger().info(f"Error: {traceback.format_exc()}")
                continue

        # 计算指标
        if token_timestamps:
            full_response_time = (token_timestamps[-1] - request_start_time) * 1000
            if total_tokens >= 2:
                effective_time = token_timestamps[-1] - token_timestamps[0]
                token_rate = total_tokens / effective_time if effective_time > 0 else 0
                token_interval = 1000 / token_rate if token_rate > 0 else 0
                get_logger().info(f"{agent_type} Token间耗时: {token_interval:.2f} ms")

        # 检查是否正常结束
        if not success_finish:
            error_msg = f"{agent_type} 请求未正常结束"
            get_logger().error(f"{agent_type} 请求未正常结束, {all_token_data}")
        else:
            error_msg = None

        # 发送性能指标
        fire_metrics()

        # 将结果追加到结果csv
        with open(log_dir / f"result_{timestamp}.csv", 'a', newline='', encoding='utf_8_sig') as f:
            writer = csv.writer(f)
            writer.writerow([query, agent_type, qaId, request_start_time, full_response_time, first_token_time if first_token_time else 0, token_interval, total_tokens, error_msg])
        
        if error_msg:
            response.failure(error_msg)

    except Exception as e:
        error_msg = f"{agent_type} 请求处理异常: {str(e)}"
        get_logger().error(f"{error_msg}")
        get_logger().error(f"{agent_type} 请求处理异常详细信息: {traceback.format_exc()}")
        fire_metrics()
        response.failure(error_msg)

class AIServiceUser(HttpUser):
    host = "http://127.0.0.1:10240"  # 基础主机地址，可通过命令行参数覆盖
    # wait_time = constant_throughput(1)  # 每秒1个请求

    def on_start(self):
        # 生成 1-1000 之间的随机数，并格式化为 4 位数字
        random_id = str(random.randint(1, 1000)).zfill(4)
        user_id = f"test-{random_id}"
        
        # 创建Token管理器
        # self.token_manager = create_token_manager(user_id, update_interval=25*60)
        
        # 设置请求头
        self.headers = {
            "Content-Type": "application/json",
            "X-USER-ID": "kia666",
            # "MS-Token": self.token_manager.get_current_token()
        }
        
        self.body = {
            # "sessionId": None,
            "query": "",
            "agentType": "",
            "extraBody": {}
        }

    def update_ms_token_if_needed(self):
        """检查并在需要时更新MS-Token"""
        self.token_manager.update_token_if_needed()
        # 更新headers中的Token
        self.headers["MS-Token"] = self.token_manager.get_current_token()

    @task(74)
    def quick_reasoning_request(self):
        """快速推理场景"""
        # 检查并更新MS-Token
        # self.update_ms_token_if_needed()
        error_msg = None
    

        try:
            quick_reasoning_data = QUICK_REASONING_Q.get_nowait()
        except queue.Empty:
            error_msg += "QUICK_REASONING队列为空，无可用测试数据"
            quick_reasoning_data = {"query": "", "agentType": "QUICK_REASONING"}

        # 将两个值都赋值到body中
        self.body["query"] = quick_reasoning_data["query"]
        self.body["agentType"] = quick_reasoning_data["agentType"]
        self.body["sessionId"] = uuid.uuid4().hex
        get_logger().debug(f"QUICK_REASONING 场景，使用数据: query={self.body['query']}, agentType={self.body['agentType']}")

        
        request_start_time = time.time()
        
        # 添加调试信息
        get_logger().info(f"QUICK_REASONING 请求详情:")
        get_logger().info(f"URL: {self.host}/api/chat/local_query")
        get_logger().info(f"Headers: {self.headers}")
        get_logger().info(f"Body: {self.body}")
        
        with self.client.post(
                f"{self.host}/api/chat/local_query",
                data=json.dumps(self.body),
                headers=self.headers,
                stream=True,
                catch_response=True,
                verify=False
                # timeout=60  # 添加请求超时时间
        ) as response:
            stream_processor(response, quick_reasoning_data["query"], "QUICK_REASONING", request_start_time)
            # 将取出的数据中重新放回队列中
            QUICK_REASONING_Q.put_nowait(quick_reasoning_data)

    @task(22)
    def deep_think_request(self):
        """深度思考场景"""
        error_msg = None 
        # 检查并更新MS-Token
        # self.update_ms_token_if_needed()

        try:
            deep_think_data = DEEP_THINK_Q.get_nowait()
        except queue.Empty:
            error_msg += "DEEP_THINK队列为空，无可用测试数据"
            deep_think_data = {"query": "", "agentType": "DEEP_THINK"}

        # 将两个值都赋值到body中
        self.body["query"] = deep_think_data["query"]
        self.body["agentType"] = deep_think_data["agentType"]
        self.body["sessionId"] = uuid.uuid4().hex
        get_logger().debug(f"DEEP_THINK 场景，使用数据: query={self.body['query']}, agentType={self.body['agentType']}")

        
        request_start_time = time.time()
        
        # 添加调试信息
        get_logger().info(f"DEEP_THINK 请求详情:")
        get_logger().info(f"URL: {self.host}/api/chat/local_query")
        get_logger().info(f"Headers: {self.headers}")
        get_logger().info(f"Body: {self.body}")
        
        with self.client.post(
                f"{self.host}/api/chat/local_query",
                data=json.dumps(self.body),
                headers=self.headers,
                stream=True,
                catch_response=True,
                verify=False
                # timeout=60  # 添加请求超时时间
        ) as response:
            stream_processor(response, deep_think_data["query"], "DEEP_THINK", request_start_time)
            # 将取出的数据中重新放回队列中
            DEEP_THINK_Q.put_nowait(deep_think_data)

    @task(12)
    def deep_research_request(self):
        """深度研究场景"""
        error_msg = None

        # 检查并更新MS-Token
        # self.update_ms_token_if_needed()

        try:
            deep_research_data = DEEP_RESEARCH_Q.get_nowait()
        except queue.Empty:
            error_msg += "DEEP_RESEARCH 队列为空，无可用测试数据"
            deep_research_data = {"query": "", "agentType": "DEEP_RESEARCH"}

        # 将两个值都赋值到body中
        self.body["query"] = deep_research_data["query"]
        self.body["agentType"] = deep_research_data["agentType"]
        self.body["sessionId"] = uuid.uuid4().hex
        get_logger().debug(f"DEEP_RESEARCH 场景，使用数据: query={self.body['query']}, agentType={self.body['agentType']}")

        
        request_start_time = time.time()
        
        # 添加调试信息
        get_logger().info(f"DEEP_RESEARCH 请求详情:")
        get_logger().info(f"URL: {self.host}/api/chat/local_query")
        get_logger().info(f"Headers: {self.headers}")
        get_logger().info(f"Body: {self.body}")
        
        with self.client.post(
                f"{self.host}/api/chat/local_query",
                data=json.dumps(self.body),
                headers=self.headers,
                stream=True,
                catch_response=True,
                verify=False
                # timeout=60  # 添加请求超时时间
        ) as response:
            stream_processor(response, deep_research_data["query"], "DEEP_RESEARCH", request_start_time)
            # 将取出的数据中重新放回队列中
            DEEP_RESEARCH_Q.put_nowait(deep_research_data)
            