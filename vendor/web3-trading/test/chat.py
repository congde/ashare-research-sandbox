# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/11 19:11:59
'''
import os
import sys
from uuid import uuid4

base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(base_path, "src"))

from libs import http

async def cancel(data: dict):
    resp = await http.post(
        "http://127.0.0.1:10240/api/chat/cancel",
        json=data,
        headers={
            "Content-Type": "application/json",
            "X-USER-ID": "kia666"
        }
    )
    print(resp)

async def main():
    session_id = uuid4().hex
    async for event in http.stream(
        "http://127.0.0.1:10240/api/chat/local_query",
        json={
            "query": "今天深圳天气",
            "sessionId": session_id,
            "extraBody": {},
            "language": "zh"
        },
        headers={
            "Content-Type": "application/json",
            "X-USER-ID": "kia666"
        },
        timeout=3600
    ):
        print(event)
    # await cancel(resp["data"])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())