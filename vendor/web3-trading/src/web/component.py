# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 17:05:51
'''


import os
import re
import inspect
import yaml
import importlib
from typing import Any


class ComponentService(object):

    def __init__(self, configs: dict):
        self.configs = configs
        self.sl_map = dict()

    def __getattr__(self, key: str):
        return self.get(key)

    def get(self, name: str, data: dict = {}, only_config: bool = False):
        if only_config:
            return self.configs.get(name)
        if not self.sl_map.get(name):
            data = data or self.configs.get(name)
            module = data.get('()')
            if module:
                self.sl_map.update({name: self._build_class(module, data)})
        elif data:
            raise Exception(f'Service {name} already exists')
        return self.sl_map.get(name)

    def config(self, name: str, default: Any = None):
        data = self.get(name, only_config=True)
        if data is None:
            return default
        return data

    def create(self, module: str, config_value: dict, single: bool = True):
        if single:
            return self.get(module, config_value)
        else:
            return self._build_class(module, config_value)

    def _build_class(self, module: str, config_value: dict) -> object:
        module, tmp_class = module.rsplit('.', 1)
        tmp_class = getattr(importlib.import_module(module), tmp_class)
        args = {}
        if hasattr(tmp_class.__init__, '__code__'):
            total_args = len(inspect.signature(tmp_class.__init__).parameters)
            default_args = len(tmp_class.__init__.__defaults__) if tmp_class.__init__.__defaults__ is not None else 0
            for i, arg in enumerate(dict(inspect.signature(tmp_class.__init__).parameters).keys()):
                if arg != 'self':
                    arg_config = config_value.get(
                        arg, tmp_class.__init__.__defaults__[i - total_args +
                                                             default_args] if default_args > 0 and i >= total_args - default_args else None)
                    args.update({
                        arg:
                        arg_config if not isinstance(arg_config, dict) or not arg_config.get('()') else self._build_class(
                            arg_config.get('()'), arg_config)
                    })
        tmp_object = tmp_class(**args)
        for p_name, p_value in config_value.items():
            if p_name == '()' or p_name in args:
                continue
            if isinstance(p_value, str) and ('config(' in p_value or 'get(' in p_value or 'env(' in p_value):
                p = re.compile(r'[(](.*?)[)]', re.S)
                items = re.findall(p, p_value).pop(0).split(',')
                name = items.pop(0).strip()
                if 'config(' in p_value:
                    p_value = self.config(name)
                    for key in items:
                        p_value = p_value.get(key.strip())
                elif 'get(' in p_value:
                    p_value = self.get(name)
                elif 'env(' in p_value:
                    p_value = os.environ.get(name)
            if hasattr(tmp_object, p_name):
                setattr(tmp_object, p_name, p_value)
            else:
                tmp_object.__dict__[p_name] = p_value
        return tmp_object


component = None
def init_component(filename):
    global component
    if not isinstance(filename, dict):
        with open(filename, encoding='utf-8') as f:
            component_conf = yaml.load(f, Loader=yaml.FullLoader)
    else:
        component_conf = filename
    component = ComponentService(component_conf)
    return component
