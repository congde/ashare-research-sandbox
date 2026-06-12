# -*- coding: utf-8 -*-
"""
脚本说明：
    连接MongoDB数据库，从kia_qa表中读取最近50条满足条件的记录并导出到JSON文件。

条件：
    1. answer字段中存在"type"为"ANSWER_RESPONSE"的元素
    2. "type"为"ANSWER_RESPONSE"的元素的step中CONTENT_CORRECTION字段或者CONTENT字段不为空

使用方式：
    cd /Users/charles/workspace/ai-web3-tradding-agent
    .venv/bin/python scripts/export_kia_qa.py                # 默认导出（可能有重复query）
    .venv/bin/python scripts/export_kia_qa.py --unique-query # 导出query不重复的记录
"""

import json
import os
import re
import argparse
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 从 .env 读取 MongoDB 配置
# COMPONENT.MONGO.URL = "mongodb://{username}:{password}@10.40.64.98:27017/ai-assistant?authSource=admin..."
MONGO_URL = os.environ.get("COMPONENT.MONGO.URL", "")
MONGO_USERNAME = os.environ.get("COMPONENT.MONGO.USERNAME", "")
MONGO_PASSWORD = os.environ.get("COMPONENT.MONGO.PASSWORD", "")

# 集合名称
MONGO_COLLECTION_NAME = "kia_qa"

# 导出配置
EXPORT_LIMIT = 50
SCRIPT_DIR = Path(__file__).parent  # 脚本所在目录
OUTPUT_FILE = SCRIPT_DIR / f"kia_qa_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


def get_mongo_client():
    """创建MongoDB连接，使用.env中的配置"""
    # 替换URL中的 {username} 和 {password} 占位符
    uri = MONGO_URL.replace("{username}", MONGO_USERNAME).replace("{password}", MONGO_PASSWORD)
    
    print(f"连接URI: {uri[:50]}...")  # 只打印部分，避免泄露密码
    
    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,  # 服务器选择超时 5秒
        connectTimeoutMS=10000,          # 连接超时 10秒
        socketTimeoutMS=30000,           # Socket操作超时 30秒
        maxPoolSize=10,                  # 最大连接池大小
        retryWrites=True,                # 写操作自动重试
    )
    return client


def get_db_name_from_url(url):
    """从MongoDB URL中提取数据库名称"""
    # URL格式: mongodb://user:pass@host:port/dbname?params
    match = re.search(r'@[^/]+/([^?]+)', url)
    if match:
        return match.group(1)
    return "ai-assistant"  # 默认数据库名


def query_kia_qa_records(client, db_name, limit=50, unique_query=False):
    """
    查询满足条件的kia_qa记录
    
    条件:
    1. answer字段中存在"type"为"ANSWER_RESPONSE"的元素
    2. 该元素的step中CONTENT_CORRECTION字段或者CONTENT字段不为空
    
    参数:
    - unique_query: 如果为True，则确保返回的记录中query字段不重复
    """
    db = client[db_name]
    collection = db[MONGO_COLLECTION_NAME]
    
    if unique_query:
        # 使用聚合管道进行去重查询
        # 先按query分组，取每组中createTime最新的一条记录
        pipeline = [
            {
                "$match": {
                    "answer": {
                        "$elemMatch": {
                            "type": "ANSWER_RESPONSE",
                            "$or": [
                                {"step.CONTENT": {"$exists": True, "$ne": "", "$ne": None}},
                                {"step.CONTENT_CORRECTION": {"$exists": True, "$ne": "", "$ne": None}}
                            ]
                        }
                    }
                }
            },
            {
                "$sort": {"createTime": -1}  # 先按时间倒序
            },
            {
                "$group": {
                    "_id": "$query",  # 按query分组
                    "doc": {"$first": "$$ROOT"}  # 取每组的第一条（最新的）
                }
            },
            {
                "$replaceRoot": {"newRoot": "$doc"}  # 将分组结果还原为原始文档格式
            },
            {
                "$sort": {"createTime": -1}  # 再次排序确保结果有序
            },
            {
                "$limit": limit
            },
            {
                "$project": {"_id": 0}  # 排除_id字段
            }
        ]
    else:
        # 普通查询（可能有重复query）
        pipeline = [
            {
                "$match": {
                    "answer": {
                        "$elemMatch": {
                            "type": "ANSWER_RESPONSE",
                            "$or": [
                                {"step.CONTENT": {"$exists": True, "$ne": "", "$ne": None}},
                                {"step.CONTENT_CORRECTION": {"$exists": True, "$ne": "", "$ne": None}}
                            ]
                        }
                    }
                }
            },
            {
                "$sort": {"createTime": -1}  # 按创建时间倒序，获取最新记录
            },
            {
                "$limit": limit
            },
            {
                "$project": {"_id": 0}  # 排除_id字段
            }
        ]
    
    results = list(collection.aggregate(pipeline))
    return results


def filter_valid_records(records):
    """
    进一步过滤记录，确保满足所有条件
    （虽然MongoDB查询已经过滤了，但这里做二次验证）
    """
    valid_records = []
    
    for record in records:
        answer_list = record.get("answer", [])
        
        for answer in answer_list:
            if answer.get("type") == "ANSWER_RESPONSE":
                step = answer.get("step", {})
                content = step.get("CONTENT")
                content_correction = step.get("CONTENT_CORRECTION")
                
                # 检查CONTENT或CONTENT_CORRECTION不为空
                has_content = content is not None and content != ""
                has_correction = content_correction is not None and content_correction != ""
                
                if has_content or has_correction:
                    valid_records.append(record)
                    break  # 找到一个满足条件的answer就可以了
    
    return valid_records


def export_to_json(records, output_file):
    """导出记录到JSON文件"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    print(f"成功导出 {len(records)} 条记录到 {output_file}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="从MongoDB的kia_qa表导出满足条件的记录到JSON文件"
    )
    parser.add_argument(
        "--unique-query",
        action="store_true",
        default=False,
        help="开启此选项后，导出的记录中query字段不会重复（默认关闭）"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=EXPORT_LIMIT,
        help=f"导出记录数量限制（默认: {EXPORT_LIMIT}）"
    )
    return parser.parse_args()


def main():
    # 解析命令行参数
    args = parse_args()
    
    # 从URL中解析数据库名
    db_name = get_db_name_from_url(MONGO_URL)
    
    print("=" * 60)
    print("开始连接MongoDB数据库...")
    print(f"数据库: {db_name}")
    print(f"集合: {MONGO_COLLECTION_NAME}")
    print(f"去重模式: {'开启' if args.unique_query else '关闭'}")
    print(f"导出数量: {args.limit}")
    print("=" * 60)
    
    client = None
    try:
        client = get_mongo_client()
        
        # 测试连接
        client.admin.command('ping')
        print("✓ MongoDB连接成功")
        
        # 查询记录
        mode_desc = "query不重复的" if args.unique_query else ""
        print(f"\n正在查询满足条件的最近 {args.limit} 条{mode_desc}记录...")
        records = query_kia_qa_records(client, db_name, args.limit, args.unique_query)
        print(f"✓ 查询到 {len(records)} 条记录")
        
        # 二次验证过滤
        valid_records = filter_valid_records(records)
        print(f"✓ 验证后有效记录: {len(valid_records)} 条")
        
        if valid_records:
            # 导出到JSON
            export_to_json(valid_records, OUTPUT_FILE)
            
            # 打印摘要信息
            print("\n" + "=" * 60)
            print("导出摘要:")
            print(f"  - 总记录数: {len(valid_records)}")
            print(f"  - 输出文件: {OUTPUT_FILE}")
            print("=" * 60)
        else:
            print("\n⚠ 未找到满足条件的记录")
        
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        raise
    finally:
        if client:
            client.close()
            print("\n✓ 连接已关闭")


if __name__ == "__main__":
    main()
