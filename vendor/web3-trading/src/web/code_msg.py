# -*- encoding: utf-8 -*-
import re


# ----------- 系统内部 --------------
CODE_SUCCESS = 200  # success
CODE_PARAMETER_ERROR = 400  # parameter error
CODE_NO_LOGIN = 401  # user not login
CODE_PARAM_REQUIRED = 402  # param required
CODE_NO_AUTH = 403  # no auth
CODE_NOT_EXIST = 404  # not exist
CODE_METHOD_NOT_ALLOWED = 405  # method not allowed
CODE_VERSION_ERROR = 406  # version error
CODE_REQUEST_TIMEOUT = 408  # request timeout
CODE_ALREADY_EXIST = 409  # already exist
CODE_REQUEST_TOO_LARGE = 413  # request too large
CODE_NOT_SUPPORT = 415  # not supported
CODE_IP_CHANGED = 416  # ip changed
CODE_GET_LOCK_ERROR = 423  # get lock error
CODE_SERVER_ERROR = 500  # internal error
CODE_SERVER_UNAVAILABLE = 503  # service unavailable

CODE_CONVERSATION_IN_PROGRESS = 100001  # This conversation is in progress. Please try again later.
CODE_SESSION_ID_NOT_FOUND = 100002  # The sessionId is not found.
CODE_QA_ID_NOT_FOUND = 100003  # The qaId is not found.
CODE_WELCOME_MESSAGE_NOT_FOUND = 100004 # Failed to get welcome message and recommend questions.
CODE_NETWORK_ERROR = 100005  # Network issue or client actively disconnected.
CODE_QUERY_RISK = 100006  # 
CODE_SESSION_DELETED = 100007  # This conversation has been deleted.

CODE_RISK_ERROR = 200001  # Sorry, I can't provide details on that as your question falls under the category: {category}. I'm an AI assistant specialized in crypto — feel free to ask me anything related to this field instead.

CODE_SKILL_DISABLED = 300001 # skill {skill_name} is disabled, please check workflow config



_CODE_MSG_MAP = dict()
_reg = re.compile(r'^CODE.*?=\s*(\d+)\s*(?:\#\s*(.*?))?\s*$')


def _load_all():
    with open(__file__, encoding='utf8') as f:
        for line in f:
            line = line.strip()
            res = _reg.match(line)
            if not res:
                continue
            code, msg = res.groups()
            _CODE_MSG_MAP[int(code)] = (msg or '')


_load_all()


def get_msg(code):
    return _CODE_MSG_MAP.get(code, '')


if __name__ == '__main__':
    # print(_CODE_MSG_MAP)
    print(get_msg(403))
