# --*-- conding:utf-8 --*--
# @Time : 2025/8/1
# @Author : Chris


import json
import datetime
import hashlib
import logging
import traceback

import jwt

from web.config import config


logger = logging.getLogger(__name__)


class JWTGenerator:

    def read_private_key(self):
        """

        :return:
        """
        if not config.factor_private_key:
            raise Exception("not found private key")
        return config.factor_private_key

    def get_sign(self, url, method, body=None):
        """

        :param url:
        :param method:
        :param body:
        :return:
        """
        if body:
            data = url + method + json.dumps(body, separators=(',', ':'))
        else:
            data = url + method
        md5_hash = hashlib.md5()
        md5_hash.update(data.encode('utf-8'))
        sg = md5_hash.hexdigest()
        return sg

    def get_jwt_token(self, sign):
        """

        :param sign:
        :return:
        """
        private_key = self.read_private_key()

        current_time = datetime.datetime.now() - datetime.timedelta(seconds=30)
        one_hour_later = current_time + datetime.timedelta(seconds=40)
        # 将时间转换为时间戳（秒）
        start = int(current_time.timestamp())
        end = int(one_hour_later.timestamp())
        iat = int((current_time + datetime.timedelta(seconds=5)).timestamp())
        logger.info(f'开始时间：{start}, 结束时间：{end}, 当前时间：{iat}')

        payload = {
            "nbf": start,
            "exp": end,
            "iat": iat,
            "sg": sign
        }
        headers = {
            "v": 2,
            "kid": config.factor_kid,
            "typ": "JWT",
            "alg": "RS256"
        }
        # 使用私钥和RS256算法生成JWT
        token = jwt.encode(payload, private_key, algorithm='RS256', headers=headers)
        return token

    def get_headers(self, url, method, body=None):
        """

        :param url:
        :param method:
        :param body:
        :return:
        """
        sign = self.get_sign(url, method, body)
        try:
            token = self.get_jwt_token(sign)
        except Exception as e:
            print(traceback.format_exc())
            raise e
        headers = {
            'GW-TOKEN': token,
            'Content-Type': 'application/json'
        }
        return headers


jwt_gen = JWTGenerator()

if __name__ == '__main__':
    url = 'https://platform-gateway-ssl.kcprd.com/api/ai-kia/label/hit'
    headers = jwt_gen.get_headers(url, 'GET', None)
    print(headers)
