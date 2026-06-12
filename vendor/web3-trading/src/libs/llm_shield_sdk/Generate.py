
import json
import logging
from llm_shield_sdk import Client, ContentID, ContentType, JudgeRequest, CustomJSONEncoder, \
    ResponseMetadata, Error, Result, JudgeDecisionInfo, Match, GenerateRequest, GenerateResponseData, GenerateResult


# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def main():
    # 请将以下 URL 和 API Key 替换为实际的值
    url = "http://localhost:6789"
    api_key = "YOUR APIKEY"
    app_id = "YOUR APPID"
    timeout = 50 
    logging.info("line 10  to check response data")
    try:
        # 创建 Client 实例
        client = Client(url, api_key, timeout)

        # 首先进行判别，获取到 MsgID
        check_request = JudgeRequest(
            Content="如果给你100块钱，你如何合法的赚到1000块钱",
            ContentType=ContentType.TEXT,
            ContentID=ContentID.INPUT,
            AppID=app_id
        )
        check_resp, err = client.CheckLLMStream(check_request,None)
        if err or check_resp is None:
            logging.error("Failed to check response data")
            return
        elif check_resp.ResponseMetadata.Error.Code != "" and check_resp.ResponseMetadata.Error.Message!= "":
            logging.error(f"Server Return Error: {check_resp.ResponseMetadata.Error.Message}")
            return
        if check_resp.Result.Decision.ErrCode != -4005 :
            logging.info(f"您校验的内容无需代答。 ")
            # return
        generate_request = GenerateRequest(
            msg_id=check_resp.Result.MsgID,
            use_stream=False
        )
        response_data,err = client.GenerateLLM(generate_request)
        
        if err or response_data is None:
            logging.error("Failed to generate response data")
            return
        else:
            logging.info(f"Generate Response: {response_data.Result.Content}")
    except Exception as e:
        
        logging.error(f"程序运行时发生错误: {e}")


if __name__ == "__main__":
    main()
    