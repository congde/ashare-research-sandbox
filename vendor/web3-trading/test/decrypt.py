import os
import hashlib
import base64
import re
import logging

from Cryptodome.Cipher import DES


logger = logging.getLogger(__name__)


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


if __name__ == '__main__':
    os.environ['CONFIG_ENCRYPTOR_PASSWORD'] = 'kptest'
    print(decrypt_enc('ENC(W0g7l1HaUdhl8WKTcTQ+qWsqSp+MCJUUMPwTB0Kp0shboyfeTKQyfw==)'))
    print(decrypt_enc('ENC(3c1eviccAffz2dmGptMqjA==)'))

    # DC-KIA-QINGNIAO-SERVER|xe3PCY
    # xe3PCY
    print()
    print(decrypt_enc("ENC(HHbMvPi2XqvQpnbBnAZj3T5EYIwvHCaEAe4Ycp9KC/M=)"))
    print(decrypt_enc("ENC(xexUo6+Yc1M6ZzH8u9zcAw==)"))