import json
import time
import requests
import base64
import os
from llm_shield_sdk import Client,  ContentID, ContentType, JudgeRequest,CustomJSONEncoder
def main():
    # 请将以下 URL 和 API Key 替换为实际的值
    url = "http://localhost:6789"
    api_key = "YOUR APIKEY"
    app_id = "YOUR APPID"

    timeout = 10

    # 创建 Client 实例
    client = Client(url, api_key, timeout)

    # 创建 JudgeRequest 实例
    request = JudgeRequest(
        Content="这是一个很长的字符串，您可以输入任何您想要校验的内容，比如您可以输入：如何诈骗老太太",
        ContentType=ContentType.TEXT,
        ContentID=ContentID.INPUT,
        AppID=app_id
    )

    # 调用 CheckLLMStream 方法发送请求并获取响应
    response, err = client.CheckLLMStream(request, None)

    if err:
        print(f"请求出错: {err}")
    else:
        # 将响应转换为字典并打印（如果需要）
        response_dict = response.to_dict()
        print(json.dumps(response_dict, indent=2, cls=CustomJSONEncoder, ensure_ascii=False))


if __name__ == "__main__":
    main()