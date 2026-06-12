from llm_shield_sdk_v2 import *


def main():
    # 配置信息（请替换为实际值）
    SERVICE_URL = "http://YOUR_URL"
    API_KEY = "YOUR_APIKEY"
    APP_ID = "YOUR_APPID"
    TIMEOUT = 30  # 超时时间（秒）

    try:
        # 构建请求（使用 pydantic 模型）
        request = ModerateV2Request(
            scene=APP_ID,
            message=MessageV2(
                    role="user",
                    content="云南人都吸毒",
                    contentType=ContentTypeV2.TEXT
                ),
            history=[
                MessageV2(
                    role="user",
                    content="请给我一份云南十一出行计划",
                    content_type=ContentTypeV2.TEXT
                ),
                MessageV2(
                    role="assistant",
                    content="Day 1：抵达昆明・滇池与石林初探...",
                    content_type=ContentTypeV2.TEXT
                )
            ]
        )

        # 发送请求并获取响应
        client = ClientV2(SERVICE_URL, API_KEY, TIMEOUT)
        response = client.Moderate(request)

        # 使用 pydantic 的内置序列化方法
        print("审核结果（JSON格式）:")
        print(response.model_dump_json(by_alias=True, indent=2))  # pydantic 模型直接转 JSON

    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    main()