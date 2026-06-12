# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 17:11:25
'''

import asyncio
import yaml
import os
import logging
import ast
from typing import Any

from pydantic import BaseModel, ConfigDict
from kc_apollo import ApolloClient

logger = logging.getLogger(__name__)
config = None
workflow_config = None


class AttrDict(BaseModel):
    model_config = ConfigDict(extra="allow")

    def __getitem__(self, key):
        return self.__getattr__(key)

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def get(self, name):
        return self.__getattr__(name)

    def set(self, name, value):
        self.__setattr__(name, value)

    def remove(self, name):
        self.__delattr__(name)


def _flatten_dict(d, parent_key='', sep='.'):
    """将嵌套字典转换为拉平的点号格式"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _set_nested_attr(obj, key_path, value):
    """设置嵌套属性值，如 config.a.b.c = value"""
    keys = key_path.split('.')
    current = obj

    for key in keys[:-1]:
        if not hasattr(current, key) or getattr(current, key) is None:
            setattr(current, key, AttrDict())
        current = getattr(current, key)

    setattr(current, keys[-1], value)


def _parse_apollo_value(value_str):
    """解析Apollo值，支持布尔类型转换"""
    lower_value = value_str.lower()
    if lower_value == 'false':
        return False
    elif lower_value == 'true':
        return True

    try:
        value_str = ast.literal_eval(value_str)
    except (ValueError, SyntaxError):
        pass

    return value_str


def init_apollo(config):
    """从Apollo配置中心获取配置"""
    if os.getenv("serverEnv", "") == "local":
        logger.info("Local environment, skipping Apollo configuration")
        return

    apollo_hosts = os.environ.get("APOLLO_HOSTS")
    if apollo_hosts is None:
        logger.warning("APOLLO_HOSTS environment variable not found, using local configuration")
        return

    appollo_id = config.apollo_id.upper()
    logger.info(f"APOLLO_HOSTS={apollo_hosts}, APPOLLO_ID={appollo_id}")

    try:
        with ApolloClient(
            app_id=appollo_id,
            business_line=config.business_line,
            max_retries=5
        ) as client:
            config_dict = config.model_dump()
            flattened_keys = _flatten_dict(config_dict)

            loaded_keys = 0
            for flat_key in flattened_keys.keys():
                try:
                    apollo_value = client.get_value(flat_key, priority_source="apollo")
                    if apollo_value is None:
                        continue

                    # msg = f"Loading config: {flat_key}={apollo_value}"
                    # print(msg)
                    # logger.info(msg)
                    parsed_value = _parse_apollo_value(apollo_value)

                    _set_nested_attr(config, flat_key, parsed_value)
                    os.environ[str(flat_key).upper()] = str(parsed_value)
                    loaded_keys += 1
                except Exception as e:
                    logger.warning(f"Failed to load Apollo config for {flat_key}: {e}")

            logger.info(f"Successfully loaded {loaded_keys} configuration keys from Apollo")

    except Exception as e:
        logger.exception(f"Failed to initialize Apollo configuration: {e}")
        logger.warning("Continuing with local configuration only")


def _dict_to_attrdict(data):
    """递归将字典转换为AttrDict"""
    if isinstance(data, dict):
        return AttrDict(**{k: _dict_to_attrdict(v) for k, v in data.items()})
    elif isinstance(data, list):
        return [_dict_to_attrdict(item) for item in data]
    else:
        return data


def _update_config_from_env(config_obj, parent_key=''):
    """从环境变量更新配置"""
    if not isinstance(config_obj, AttrDict):
        return

    for k in config_obj.model_dump().keys():
        v = config_obj[k]
        env_key = f"{parent_key}_{k}".upper() if parent_key else k.upper()
        env_value = os.environ.get(env_key, "")

        if env_value:
            parsed_value = _parse_apollo_value(env_value)
            config_obj[k] = parsed_value
        elif isinstance(v, AttrDict):
            _update_config_from_env(v, f"{parent_key}_{k}" if parent_key else k)
        elif v is not None:
            os.environ[env_key] = str(v)


def init_config(filename):
    """初始化配置，从YAML加载并支持环境变量和Apollo覆盖"""
    global config

    with open(filename, encoding='utf-8') as f:
        yaml_data = yaml.load(f, Loader=yaml.FullLoader)

    config = _dict_to_attrdict(yaml_data)
    _update_config_from_env(config)

    server_env = os.environ.get('serverEnv', 'local')
    config['server_env'] = server_env

    init_apollo(config)

    from web.component import init_component
    init_component(config.component.model_dump(mode="json"))

    return config


def is_risk_control_enabled() -> bool:
    """
    风控总开关。为 False 时不做 query/流式/欢迎语/客服入口等任何风控与 URL 检测。
    默认 True 以保持旧环境行为；本仓库 default.yaml 中设为 false。
    """
    global config
    if config is None:
        return True
    return bool(getattr(config, "risk_control_enabled", True))


def init_workflow_config(path):
    """加载工作流配置，递归搜索yaml文件"""
    global workflow_config
    workflow_config = {}
    
    for root, _, files in os.walk(path):
        for filename in files:
            if filename.endswith('.yaml'):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, path)
                config_name = os.path.splitext(rel_path)[0].replace(os.sep, '/')  # 去掉扩展名，统一路径分隔符
                with open(filepath, encoding='utf-8') as f:
                    workflow_config[config_name] = yaml.load(f, Loader=yaml.FullLoader)
    
    return workflow_config
