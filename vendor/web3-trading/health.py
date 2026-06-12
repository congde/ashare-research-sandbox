import os
import sys
import time
import httpx

base_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base_path, "src"))
os.environ["LOG_PATH"] = "/var/log/kucoin/ai-web3-tradding-agent"
os.environ["LOG_FILENAME"] = "/var/log/kucoin/ai-web3-tradding-agent/common-health.log"

from web.logger import get_logger

logger = get_logger(__name__)
url = f"http://127.0.0.1:10240/actuator/health"

response = None
try:
    with httpx.Client(timeout=30) as client:
        response = client.get(url)
        status_code = response.status_code
        if status_code == 200:
            logger.info(
                f"Executed health.py success: {status_code}, Response: {response.text}"
            )
        else:
            logger.error(
                f"Executed health.py failed: {status_code}, Response: {response.text}"
            )

except httpx.HTTPStatusError as http_err:
    logger.error(
        f"Executed health.py error occurred: {http_err.response.status_code}, Body: {http_err.response.text}"
    )
    sys.exit(2)
except httpx.RequestError as req_err:
    logger.error(f"Executed health.py request execution failed: {req_err}")
    sys.exit(1)
except Exception as e:
    logger.error(f"Executed health.py unexpected error occurred: {e}")
    sys.exit(1)
finally:
    logger.info("Executed health.py retrying in 10 seconds...")
