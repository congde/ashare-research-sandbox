import json
from llm_shield_sdk import CustomJSONEncoder
from llm_shield_sdk_v2 import (
    ModerateV2Request,
    MessageV2,
    ContentTypeV2,
    ClientV2,
    ModerateV2StreamSession,
)


def main():
    # 配置信息（请替换为实际值）
    SERVICE_URL = "http://YOUR_URL"
    API_KEY = "YOUR_APIKEY"
    APP_ID = "YOUR_APPID"
    TIMEOUT = 30  # 超时时间（秒）

    # 测试文本（长文本）
    long_text = '''这是一个非常严重的行为，被称为“网络诈骗”（Internet fraud）或 “网络欺诈”（Online fraud）。这种行为通常通过电子邮件、社交媒体、短信等途径进行，声称是合法机构或者知名公司，诱骗受害者提供个人身份信息、银行账户信息、信用卡号、密码等重要信息。这些信息一旦落入不法分子手中，他们就可以盗取受害者的资金、信用记录和财产。
 网络诈骗是一种犯罪活动，不仅危害了个人的财务安全，还损害了社会公共利益和经济秩序。我们应该时刻保持警惕并注意保护自己的隐私和安全。以下是一些常见的防范措施：
 1. 不要轻易相信陌生人的邮件和信息，尤其是那些要求您提供敏感信息的邮件； 不要在不明来源的网站上输入任何个人信息，特别是涉及金融交易的信息； 使用强密码和多因素认证来保护您的在线帐户； 在使用互联网时，确保计算机系统和浏览器都是最新版本，以获得最新的安全性更新； 如果发现自己已经成为诈骗分子的目标，立即联系当地警方并提供尽可能多的信息以便进行调查处理。'''

    try:
        # 构建基础请求（使用正确的字段名）
        request = ModerateV2Request(
            scene=APP_ID,
            use_stream=1,
            message=MessageV2(
                role="assistant",
                content="",  # 初始为空，后续分块填充
                content_type=ContentTypeV2.TEXT  # 修复字段名：ContentType → content_type
            ),
            history=[
                MessageV2(
                    role="user",
                    content="你是一个智能助手",
                    content_type=ContentTypeV2.TEXT
                ),
                MessageV2(
                    role="assistant",
                    content="Day 1：抵达昆明・滇池与石林初探...",
                    content_type=ContentTypeV2.TEXT
                )
            ]
        )

        # 初始化客户端和会话
        client = ClientV2(SERVICE_URL, API_KEY, TIMEOUT)
        if not client:
            raise Exception("创建客户端实例失败")

        session = ModerateV2StreamSession()
        if not session:
            raise Exception("创建流式会话实例失败")

        # 分块处理参数
        chunk_size = 9
        text_length = len(long_text)
        #print(f"开始流式处理，总长度: {text_length}，分块大小: {chunk_size}\n")

        # 分块发送请求
        for i in range(0, text_length, chunk_size):
            end = i + chunk_size
            is_last_chunk = end >= text_length

            # 最后一块标记
            if is_last_chunk:
                end = text_length
                request.use_stream = 2  # 最后一次请求

            # 设置当前分块内容
            chunk = long_text[i:end]
            request.message.content = chunk
            print(f"发送分块 [{i + 1}-{end}/{text_length}]: {chunk}")

            # 调用流式审核接口
            try:
                response = client.ModerateStream(request, session)
            except Exception as e:
                print(f"分块处理失败: {str(e)}")
                if is_last_chunk:  # 最后一块失败需终止
                    raise
                continue  # 非最后一块继续处理

            # 处理响应
            if response is None:
                print("本次分块无响应\n")
                continue

            # 转换响应为字典（使用 Pydantic 原生方法）
            try:
                # 替换 to_dict()，使用 model_dump 保持兼容性
                response_dict = response.model_dump(by_alias=True)
                print("审核响应:")
                print(json.dumps(
                    response_dict,
                    indent=2,
                    cls=CustomJSONEncoder,
                    ensure_ascii=False
                ))
                print()  # 换行分隔
            except Exception as e:
                print(f"响应序列化失败: {str(e)}\n")

        print("所有分块处理完成")

    # 异常处理
    except Exception as e:
        print(f"意外错误: {str(e)}")


if __name__ == "__main__":
    main()