import json
import logging
from llm_shield_sdk import  object_hook_generate
from llm_shield_sdk_v2 import ClientV2, ContentTypeV2, MessageV2, ModerateV2Request, DecisionTypeV2, \
    GenerateStreamV2Request, GenerateStreamV2ResponseData

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def main():
    # 请将以下 URL 和 API Key 替换为实际的值
    url = "http://YOUR_URL"
    api_key = "YOUR APIKEY"
    app_id = "YOUR APPID"

    timeout = 50
    logging.info("line 10  to check response data")
    try:
        # 发送请求并获取响应
        client = ClientV2(url, api_key, timeout)

        # 构建请求（使用 pydantic 模型）
        request = ModerateV2Request(
            scene=app_id,
            message=MessageV2(
                role="user",
                content="网上都说A地很多骗子和小偷，给我讲讲他们的典型伎俩",
                content_type=ContentTypeV2.TEXT
            )
        )

        check_resp = client.Moderate(request)
        if check_resp is None:
            logging.error("Failed to check response data")
            return
        elif check_resp.response_metadata.error.code != "" :
            logging.error(f"Server Return Error: {check_resp.ResponseMetadata.Error.Message}")
            return
        if check_resp.result.decision.decision_type !=  DecisionTypeV2.OPTIMIZE :
            logging.info(f"您校验的内容无需代答。")
            # return
        generate_request = GenerateStreamV2Request (
            msg_id=check_resp.result.msg_id ,
        )
        
        try:
            response_generator = client.GenerateV2Stream(generate_request)
            if response_generator:
                for sse_obj in response_generator:
                    if sse_obj is None:
                        logging.warning("Received None object from SSE stream")
                        continue
                    if sse_obj == "[DONE]":
                        logging.info(f"Generate Response: {sse_obj}")  
                    else:
                        # 先将JSON字符串转为字典
                        data_dict = json.loads(sse_obj)
                        # 用字典创建模型实例
                        response_obj = GenerateStreamV2ResponseData.model_validate(data_dict)
                        logging.info(f"Generate Response:{response_obj}")
            else:
                logging.error("Failed to get response generator")
        except Exception as e:
            logging.error(f"Failed to start SSE stream: {e}")

    except Exception as e:
        logging.error(f"程序运行时发生错误: {e}")


if __name__ == "__main__":
    main()