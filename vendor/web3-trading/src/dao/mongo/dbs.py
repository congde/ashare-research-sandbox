# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:44:07
'''

import os

from dao.mongo.base import BaseDAO as MongoBaseDAO


ai_assistant_db = MongoBaseDAO(os.environ.get('MONGO_DB_NAME') or 'ai-assistant')
web3_trading_db = MongoBaseDAO(os.environ.get('MONGO_DB_TRADING_NAME') or 'web3-trading')
