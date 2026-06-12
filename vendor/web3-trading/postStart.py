import os
import sys
import time
import httpx

base_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base_path, "src"))
os.environ["LOG_PATH"] = "/var/log/kucoin/ai-web3-tradding-agent"
os.environ["LOG_FILENAME"] = "/var/log/kucoin/ai-web3-tradding-agent/common-start.log"

from web.logger import get_logger

logger = get_logger(__name__)

url = f"http://127.0.0.1:10240/actuator/up"
time.sleep(30)
while True:
    try:
        response = httpx.post(url, timeout=3)
        response.raise_for_status()
        status_code = response.status_code
        logger.info(f"/actuator/up status={status_code}")
        break

    except Exception as e:
        logger.exception(f"/actuator/up error")
    finally:
        time.sleep(5)