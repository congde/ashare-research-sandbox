import os
import time
import sys
import logging

import httpx

base_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base_path, "src"))
os.environ["LOG_PATH"] = "/var/log/kucoin/ai-web3-tradding-agent"
os.environ["LOG_FILENAME"] = "/var/log/kucoin/ai-web3-tradding-agent/common-stop.log"

logger = logging.getLogger(__name__)


pid_list = os.popen("ps -ef | grep postStart|grep -v grep|awk '{print $2}'").read()
for pid in pid_list.split("\n")[0:-1]:
    logger.info("kill -9 postStart, pid: {}".format(pid))
    os.system("kill -9 %s" % pid)

time.sleep(1)

url = f"http://127.0.0.1:10240/actuator/down"

while True:
    try:
        response = httpx.post(url, timeout=3)
        response.raise_for_status()
        status_code = response.status_code
        logger.info(f"/actuator/down status={status_code}")
        break

    except Exception as e:
        logger.exception(f"/actuator/down error")
    finally:
        time.sleep(3)
