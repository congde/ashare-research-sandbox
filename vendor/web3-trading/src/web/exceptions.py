
from web import code_msg


class HttpException(Exception):

    def __init__(self, code, msg=None, extra=None, raise_user=False):
        self.code = code
        if msg is None:
            msg = code_msg.get_msg(code)
        self.msg = msg
        self.extra = extra
        self.raise_user = raise_user

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}(code={self.code}, msg={self.msg}, extra={self.extra}, raise_user={self.raise_user})>"

    def __str__(self):
        return self.__repr__()


class AuthException(HttpException):
    pass


class RiskException(HttpException):
    pass