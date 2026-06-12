import json
import requests
import time

LLM_STREAM_SEND_BASE_WINDOW = 10
LLM_STREAM_SEND_EXPONENT = 2

# 定义 ContentID 枚举
class ContentID(object):
    INPUT = 1
    OUTPUT = 2


# 定义 ContentType 枚举
class ContentType(object):
    TEXT = 1
    AUDIO = 2
    IMAGE = 3
    VIDEO = 4


# 定义 Match 类
class Match(object):
    def __init__(self, Label="", Word=""):
        self.Label = Label
        self.Word = Word


# 定义 JudgeDecisionInfo 类
class JudgeDecisionInfo(object):
    def __init__(self, ErrCode=0, ErrMsg="", Labels="", Matches=None, DecisionCategory=None, RuleIDs=None):
        self.ErrCode = ErrCode
        self.ErrMsg = ErrMsg
        self.Labels = Labels
        self.Matches = Matches if Matches else []
        self.DecisionCategory = DecisionCategory if DecisionCategory else []
        self.RuleIDs = RuleIDs if RuleIDs else []


# 定义 Error 类
class Error(object):
    def __init__(self, Code="", Message=""):
        self.Code = Code
        self.Message = Message


# 定义 Result 类
class Result(object):
    def __init__(self, Decision=None, MsgID=""):
        self.Decision = Decision if Decision else JudgeDecisionInfo()
        self.MsgID = MsgID


# 定义 JudgeResponse 类
class JudgeResponse(object):
    def __init__(self, response_metadata=None, result=None):
        self.ResponseMetadata = response_metadata if isinstance(response_metadata, ResponseMetadata) else ResponseMetadata()
        self.Result = result if isinstance(result, Result) else Result()

    def to_dict(self):
        return {
            "ResponseMetadata": self.ResponseMetadata.__dict__ if self.ResponseMetadata else {},
            "Result": self.Result.__dict__ if self.Result else {}
        }


# 定义 JudgeRequest 类
class JudgeRequest(object):
    def __init__(self, Content="", ContentType=ContentType.TEXT, ContentID=ContentID.INPUT, AppID="", MsgID="",
                 UseStream=0):
        self.Content = Content
        self.ContentType = ContentType
        self.ContentID = ContentID
        self.AppID = AppID
        self.MsgID = MsgID
        self.UseStream = UseStream


class ResponseMetadata:
    def __init__(self, error=None):
        self.Error = error if isinstance(error, Error) else Error()


class GenerateResult:
    def __init__(self, content=""):
        self.Content = content


class GenerateResponseData:
    def __init__(self, response_metadata=None, result=None):
        self.ResponseMetadata = response_metadata if isinstance(response_metadata, ResponseMetadata) else ResponseMetadata()
        self.Result = result if isinstance(result, GenerateResult) else GenerateResult()


class GenerateResponse:
    def __init__(self, reader=None):
        self.Reader = reader


class GenerateRequest:
    def __init__(self, msg_id="", use_stream=False):
        self.MsgID = msg_id
        self.UseStream = use_stream


# 自定义对象钩子，用于将字典转换为类实例
def object_hook_judge(d):
    if 'Code' in d and 'Message' in d:
        return Error(Code=d['Code'], Message=d['Message'])
    elif 'ErrCode' in d and 'ErrMsg' in d:
        matches = [Match(**match) for match in d.get('Matches', [])]
        return JudgeDecisionInfo(
            ErrCode=d['ErrCode'],
            ErrMsg=d['ErrMsg'],
            Labels=d.get('Labels', ""),
            Matches=matches,
            DecisionCategory=d.get('DecisionCategory', []),
            RuleIDs=d.get('RuleIDs', [])
        )
    elif 'Decision' in d and 'MsgID' in d:
        decision = object_hook_judge(d['Decision']) if isinstance(d['Decision'], dict) else d['Decision']
        return Result(Decision=decision, MsgID=d['MsgID'])
    elif 'ResponseMetadata' in d and 'Result' in d:
        response_metadata = object_hook_judge(d['ResponseMetadata']) if isinstance(d['ResponseMetadata'], dict) else d['ResponseMetadata']
        result = object_hook_judge(d['Result']) if isinstance(d['Result'], dict) else d['Result']
        return JudgeResponse(response_metadata=response_metadata, result=result)
    return d


def object_hook_generate(d):
    if 'Code' in d and 'Message' in d:
        return Error(Code=d['Code'], Message=d['Message'])
    elif 'ResponseMetadata' in d and 'Result' in d:
        response_metadata = d.get('ResponseMetadata')
        if isinstance(response_metadata, dict):
            response_metadata = object_hook_generate(response_metadata)
        elif response_metadata is None:
            response_metadata = ResponseMetadata()

        result_dict = d['Result']
        if isinstance(result_dict, dict) and 'Content' in result_dict:
            result = GenerateResult(content=result_dict['Content'])
        else:
            result = result_dict if not isinstance(result_dict, dict) else object_hook_generate(result_dict)

        return GenerateResponseData(response_metadata=response_metadata, result=result)
    elif 'Result' in d and isinstance(d['Result'], dict) and 'Content' in d['Result']:
        # 如果只有 Result 且包含 Content，创建 GenerateResponseData 并使用默认的 ResponseMetadata
        result = GenerateResult(content=d['Result']['Content'])
        return GenerateResponseData(response_metadata=ResponseMetadata(), result=result)
    return d

class JudgeStreamSession:
    def __init__(self):
        self.StreamBuf = ""
        self.CurrentSendWindow = LLM_STREAM_SEND_BASE_WINDOW
        self.StreamSendLen = 0
        self.MsgID = None
        self.defaultOut = JudgeResponse()

# 定义 Client 类
class Client(object):
    def __init__(self, url, api_key, timeout):
        self.url = url
        self.api_key = api_key
        self.httpClient = requests.Session()
        self.httpClient.timeout = timeout

    # CheckLLMStream 方法
    def CheckLLMStream(self, request , session):
        if request is None:
            request = JudgeRequest()
        if session is None and request.UseStream!= 0:
            return None, Exception("when useStream is not 0 ,session cannot be null")
        if request.UseStream!= 0:
            session.StreamBuf += request.Content
            session.StreamSendLen += len(request.Content)
            if session.MsgID is not None:
                request.MsgID = session.MsgID
            if session.StreamSendLen <= session.CurrentSendWindow and request.MsgID != "" and request.UseStream != 2:
                return session.defaultOut, None
            else:
                request.Content = session.StreamBuf
                session.CurrentSendWindow = session.CurrentSendWindow * LLM_STREAM_SEND_EXPONENT
                session.StreamSendLen = 0



        # 将请求结构体序列化为 JSON
        requestBody = json.dumps(request.__dict__)
        #print("请求数据为: ", request.Content)
        # 创建 HTTP 请求
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }
        try:
            resp = self.httpClient.post(self.url + "/v1/judge", data=requestBody, headers=headers)
            if resp.status_code != 200:
                return None, Exception("bad response code: %d" % resp.status_code)

            # 读取响应体
            responseBody = resp.text
            print("服务端返回的响应数据: ", responseBody)

            response = json.loads(responseBody, object_hook=object_hook_judge)

            if response.ResponseMetadata.Error.Code != "":
                print("服务端返回Error ", response.ResponseMetadata.Error.Code + " " + response.ResponseMetadata.Error.Message)
                return response, None
            if request.UseStream!= 0:
                if session.MsgID is None:
                    session.MsgID = response.Result.MsgID
                session.defaultOut = response
            return response, None
        except Exception as e:
            return None, Exception("failed to send request: %s" % str(e))

    def GenerateLLM(self, request):
        # 如果请求对象为空，创建一个默认的 JudgeRequest 实例
        if request is None:
            request = JudgeRequest()
        try:
            # 将请求对象转换为 JSON 字符串
            request_body = json.dumps(request.__dict__)

            # 设置请求头
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key
            }

            # 发送 POST 请求
            response = self.httpClient.post(self.url + "/v1/generate", data=request_body, headers=headers)

            # 检查响应状态码
            if response.status_code != 200:
                return None, Exception(f"Bad response code: {response.status_code}")

            # 获取响应体
            response_body = response.text
            # print("服务端返回的响应数据: ", response_body)

            # 解析响应体为 Python 对象
            response_obj = json.loads(response_body, object_hook=object_hook_generate)

            return response_obj, None

        except json.JSONDecodeError as e:
            # 处理 JSON 解析错误
            return None, Exception(f"Failed to decode response JSON: {str(e)}")
        

    def GenerateLLMStream(self, request):
        if request is None:
            request = GenerateRequest()

        # 将请求结构体序列化为 JSON
        requestBody = requests.compat.json.dumps(request.__dict__)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }
        try:
            # 发送 HTTP 请求
            resp = self.httpClient.post(self.url + "/v1/generate", data=requestBody, headers=headers, stream=True)
            if resp.status_code != 200:
                raise Exception("bad response code: %d" % resp.status_code)

            for line in resp.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.lstrip().startswith('data:'):
                        sse_data = line[line.index(':') + 1:].strip()
                        yield sse_data
        except Exception as e:
            return None, Exception("failed to send request: %s" % str(e))


# 自定义 JSON 编码器
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Error):
            return {
                "Code": obj.Code,
                "Message": obj.Message
            }
        elif isinstance(obj, JudgeDecisionInfo):
            return {
                "ErrCode": obj.ErrCode,
                "ErrMsg": obj.ErrMsg,
                "Labels": obj.Labels,
                "Matches": [{"Label": match.Label, "Word": match.Word} for match in obj.Matches],
                "DecisionCategory": obj.DecisionCategory,
                "RuleIDs": obj.RuleIDs
            }
        return super().default(obj)