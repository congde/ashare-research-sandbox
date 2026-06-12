# --*-- conding:utf-8 --*--
# @Time : 2024/12/4
# @Author : Chris

import os
import hashlib
import random
import base64
import re
import string

from pyDes import des, PAD_PKCS5, CBC
from Cryptodome.Cipher import DES

__all__=(
    'decrypt_enc',
    'des_encrypt',
    'des_descrypt',
)


def get_derived_key(p, salt, count):
    key = p + salt
    for i in range(count):
        m = hashlib.md5(key)
        key = m.digest()
    return key[:8], key[8:]


def decrypt(msg, p):
    msg_bytes = base64.b64decode(msg)
    salt = msg_bytes[:8]
    enc_text = msg_bytes[8:]
    (dk, iv) = get_derived_key(p, salt, 1000)
    crypter = DES.new(dk, DES.MODE_CBC, iv)
    text = crypter.decrypt(enc_text)
    return re.sub(r'[\x01-\x08]', '', text.decode("utf-8"))


def decrypt_enc(msg):
    if not isinstance(msg, str):
        return msg
    p = os.environ.get('CONFIG_ENCRYPTOR_PASSWORD')
    if p is None:
        raise ValueError('Request Ops to add the (config_encryptor_password)configuration')
    match_obj = re.match(r'ENC\((.*?)\)', msg)
    if match_obj:
        result = match_obj.group(1)
        return decrypt(result, p.encode('utf-8'))
    return msg


def ensure_str(s, encoding="utf-8"):
    if isinstance(s, bytes):
        return s.decode(encoding)
    return s


def ensure_bytes(s):
    if isinstance(s, str):
        return s.encode("utf-8")
    return s


def generate_des_obj(key, random_str="", iter_times=1000):
    if not random_str:
        random_str = "".join(random.sample(string.ascii_letters + string.digits, 8))
    md = hashlib.md5()
    md.update(key.encode("utf-8"))
    md.update(ensure_bytes(random_str))

    des_key_spec = md.digest()
    for i in range(1, iter_times):
        des_key_spec = hashlib.md5(des_key_spec).digest()
    # secret_key:加密密钥，CBC:加密模式，iv:偏移, padmode:填充
    return des(des_key_spec[:-8], CBC, des_key_spec[-8:], pad=None, padmode=PAD_PKCS5)


def des_encrypt(s, key, iter_times=1000, random_str=""):
    """
     DES 加密
    :param s:
    :param key:
    :param iter_times:
    :param random_str:
    :return:
    """

    if not random_str:
        random_str = "".join(random.sample(string.ascii_letters + string.digits, 8))
    random_str = ensure_bytes(random_str)
    des_obj = generate_des_obj(key, random_str, iter_times)
    en = des_obj.encrypt(ensure_bytes(s), padmode=PAD_PKCS5)
    return str(base64.b64encode(random_str + en), "utf-8")


def des_descrypt(s, key, iter_times=1000):
    """
    DES 解密
    :param s:
    :param key:
    :param iter_times:
    :return:
    """

    bs = base64.standard_b64decode(s)
    des_obj = generate_des_obj(key, bs[:8], iter_times)
    return ensure_str(des_obj.decrypt(bs[8:]))


if __name__ == '__main__':
    content = 'P3ogkU7f3sPM'
    enc_pwd = des_encrypt(content, '')
    print(enc_pwd)
    des_pwd = des_descrypt(enc_pwd, '')
    print(des_pwd)
