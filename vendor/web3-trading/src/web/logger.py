import os
import time
import logging
from logging.config import dictConfig


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STANDARD_FORMAT = '%(asctime)s | %(levelname)s | %(name)s(%(lineno)d) : %(message)s'
CUSTOM_FORMAT = '%(asctime)s | %(levelname)-8s| %(process)s:%(message_uuid)s - %(name)s:%(funcName)s:%(lineno)d - %(message)s'
LOG_PATH = os.environ.get("LOG_PATH", os.environ.get("log_path", os.path.join(PROJECT_PATH, "logs")))
os.makedirs(LOG_PATH, exist_ok=True)
log_filename = os.environ.get("LOG_FILENAME")
if not log_filename:
    log_filename = os.path.join(LOG_PATH, 'common-default.log')


class RequestFormatter(logging.Formatter):
    def format(self, record):
        from web.context import context
        record.message_uuid = context.get('message_uuid')
        record.user_id = context.get('user_id')
        record.remote_addr = context.get('remote_addr')
        return super().format(record)


handlers = ['info', 'error']
if os.environ.get("serverEnv", "") == "local":
    handlers.append('console')

dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': STANDARD_FORMAT
        },
        'custom': {
            'format': CUSTOM_FORMAT,
            '()': RequestFormatter
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'custom',
        },
        'info': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'formatter': 'custom',
            'filename': log_filename,
            'when': 'MIDNIGHT',
            'interval': 1,
            'backupCount': 10,
            'encoding': 'utf-8'
        },
        'error': {
            'level': 'ERROR',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'formatter': 'custom',
            'filename': os.path.join(LOG_PATH, 'common-error.log'),
            'when': 'MIDNIGHT',
            'interval': 1,
            'backupCount': 10,
            'encoding': 'utf-8'
        },
    },
    'loggers': {
        '': {
            'handlers': handlers,
            'level': 'INFO'
        }
    }
})


def get_logger(name):
    return logging.getLogger(name)


if __name__ == "__main__":
    logger = get_logger(__name__)

    logger.info("xixiixixix")
    logger.info("hahahha")
    logger.error("系统错误，请稍后重试")
