#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File    :   stress_test_welcome.py
@Time    :   2025/11/13
@Desc    :   welcome接口压测场景
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


timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

# 创建logs目录
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

# 配置日志
def setup_logging():
    """配置日志输出到当前目录的logs文件夹"""
    
    # 生成带时间戳的日志文件名
    log_file = log_dir / f"stress_test_welcome_{timestamp}.log"
    
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
    custom_logger = logging.getLogger('stress_test_welcome')
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
WELCOME_Q = queue.Queue()

# 支持的语言列表（从代码中看到的语言代码）
SUPPORTED_LANGUAGES = [
    "en_US", "zh_CN", "zh_HK", "ja_JP", "ko_KR", 
    "es_ES", "fr_FR", "de_DE", "it_IT", "pt_PT",
    "ru_RU", "ar_AE", "hi_IN", "th_TH", "vi_VN",
    "id_ID", "ms_MY", "fil_PH", "tr_TR", "uk_UA",
    "ur_PK", "bn_BD", "pl_PL", "nl_NL"
]

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """初始化时读取 csv 数据或生成测试数据"""
    global logger
    
    # 在Locust初始化时配置logger
    logger = setup_logging()
    logger.info("=" * 80)
    logger.info("Locust Welcome接口压力测试开始初始化")
    logger.info("=" * 80)

    # 新建结果csv
    result_csv_path = log_dir / f"result_welcome_{timestamp}.csv"
    with open(result_csv_path, 'w', newline='', encoding='utf_8_sig') as f:
        writer = csv.writer(f)
        writer.writerow(["language", "memory_limit", "request_start_time", "full_response_time", "status_code", "welcome_message", "recommended_questions", "error_msg"])

    try:
        # 尝试读取csv文件（如果存在）
        csv_path = os.path.join(os.path.dirname(__file__), os.pardir, "data", "welcome_test_data.csv")
        
        if os.path.exists(csv_path):
            logger.info(f"正在读取CSV文件: {csv_path}")
            df = pd.read_csv(csv_path)
            
            # 将数据保存到全局变量
            for _, row in df.iterrows():
                data = {
                    "language": row.get('language', 'en_US'),
                    "memory_limit": row.get('memory_limit', 10)
                }
                WELCOME_Q.put_nowait(data)
        else:
            # 如果CSV文件不存在，生成默认测试数据
            logger.info(f"CSV文件不存在: {csv_path}，使用默认测试数据")
            # 为每种语言生成测试数据
            for language in SUPPORTED_LANGUAGES:
                for memory_limit in [10]:
                    data = {
                        "language": language,
                        "memory_limit": memory_limit
                    }
                    WELCOME_Q.put_nowait(data)
        
        logger.info("数据加载完成，队列数据量：")
        logger.info(f"WELCOME队列: {WELCOME_Q.qsize()}条")
    except Exception as e:
        logger.error(f"读取csv文件失败: {e}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        # 即使出错也生成一些默认数据
        for language in ["en_US", "zh_CN"]:
            for memory_limit in [10]:
                data = {
                    "language": language,
                    "memory_limit": memory_limit
                }
                WELCOME_Q.put_nowait(data)
        logger.info(f"使用默认测试数据，队列数据量: {WELCOME_Q.qsize()}条")

def response_processor(response, language: str, memory_limit: int, request_start_time: float):
    """
    处理响应并计算相关指标

    Args:
        response: 响应对象
        language: 请求语言
        memory_limit: 内存限制
        request_start_time: 请求开始时间
    """
    full_response_time = 0
    status_code = 0
    welcome_message = ""
    recommended_questions = []
    error_msg = ''

    try:
        full_response_time = (time.time() - request_start_time) * 1000  # 转换为毫秒
        status_code = response.status_code
        
        get_logger().info(f"Welcome接口收到响应，状态码: {status_code}, 耗时: {full_response_time:.2f}ms")
        
        if response.status_code != 200:
            error_msg = f"HTTP错误: {status_code}"
            response.failure(error_msg)
        else:
            try:
                # 解析JSON响应
                result = response.json()
                # get_logger().info(f"result: {result}")
                data = result.get('data', {})
                
                # 检查响应结构
                welcome_message = data.get('welcome_message', {})
                recommended_questions = data.get('recommended_questions', [])
                
                # 验证响应完整性
                if not welcome_message or not recommended_questions:
                    error_msg = f"响应不完整: welcome_message={welcome_message}, recommended_questions={recommended_questions}"
                    get_logger().warning(f"Welcome接口响应不完整: {error_msg}")
                    response.failure(error_msg)
                else:
                    get_logger().info(f"Welcome接口请求成功: language={language}, memory_limit={memory_limit}")
                    response.success()
                    
            except json.JSONDecodeError as e:
                error_msg = f"JSON解析失败: {str(e)}"
                get_logger().error(f"Welcome接口JSON解析失败: {error_msg}")
                response.failure(error_msg)
            except Exception as e:
                error_msg = f"响应处理异常: {str(e)}"
                get_logger().error(f"Welcome接口响应处理异常: {error_msg}")
                get_logger().error(f"异常详情: {traceback.format_exc()}")
                response.failure(error_msg)

        # 发送性能指标
        events.request.fire(
            request_type="Welcome/总请求耗时",
            name="Welcome/总请求耗时",
            response_time=full_response_time,
            response_length=0,
            exception=error_msg if error_msg else None,
            context={}
        )

        # 将结果追加到结果csv
        with open(log_dir / f"result_welcome_{timestamp}.csv", 'a', newline='', encoding='utf_8_sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                language, 
                memory_limit, 
                request_start_time, 
                full_response_time, 
                status_code,
                welcome_message,
                recommended_questions,
                error_msg
            ])

    except Exception as e:
        error_msg = f"Welcome接口请求处理异常: {str(e)}"
        get_logger().error(f"{error_msg}")
        get_logger().error(f"异常详细信息: {traceback.format_exc()}")
        response.failure(error_msg)

class WelcomeServiceUser(HttpUser):
    host = "http://127.0.0.1:10240"  # 基础主机地址，可通过命令行参数覆盖
    # wait_time = constant_throughput(1)  # 每秒1个请求

    def on_start(self):
        # 生成 1-1000 之间的随机数，并格式化为 4 位数字
        random_id = str(random.randint(1, 1000)).zfill(4)
        user_id = f"test-{random_id}"
        
        # 设置请求头
        self.headers = {
            "Content-Type": "application/json",
            "X-USER-ID": "kia666",
        }

    @task
    def welcome_request(self):
        """Welcome接口压测场景"""
        error_msg = None

        try:
            welcome_data = WELCOME_Q.get_nowait()
        except queue.Empty:
            error_msg = "WELCOME队列为空，无可用测试数据"
            get_logger().warning(error_msg)
            # 使用默认值
            welcome_data = {
                "language": "en_US",
                "memory_limit": 10
            }

        language = welcome_data.get("language", "en_US")
        memory_limit = welcome_data.get("memory_limit", 10)
        
        get_logger().debug(f"Welcome场景，使用数据: language={language}, memory_limit={memory_limit}")

        request_start_time = time.time()
        
        # 构建请求URL
        url = f"{self.host}/api/chat/welcome?language={language}&memory_limit={memory_limit}"
        
        # 添加调试信息
        get_logger().info(f"Welcome请求详情:")
        get_logger().info(f"URL: {url}")
        get_logger().info(f"Headers: {self.headers}")
        
        with self.client.get(
                url,
                headers=self.headers,
                catch_response=True,
                verify=False
                # timeout=60  # 添加请求超时时间
        ) as response:
            response_processor(response, language, memory_limit, request_start_time)
            # 将取出的数据重新放回队列中
            WELCOME_Q.put_nowait(welcome_data)

