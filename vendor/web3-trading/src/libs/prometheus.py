# --*-- conding:utf-8 --*--
# @Time : 2024/11/21
# @Author : Chris

import os
import time

from prometheus_client import Counter, Histogram, Gauge


class BaseMetrics:

    def __init__(self, server_name: str):
        self.server_name = server_name

    def get_label(self, *args, **kwargs):
        """子类实现具体的指标更新逻辑"""
        raise NotImplementedError


#
class HttpRequestsTotalMetrics(BaseMetrics):
    metrics_type = "http_requests_total"
    metric = Counter(
        'http_requests_total', 'Total HTTP requests',
        ['method', 'endpoint', 'status', 'application']
    )

    def get_label(self, method, endpoint, status, *args, **kwargs):
        """

        :param method:
        :param endpoint:
        :param status:
        :return:
        """
        metric = getattr(self, 'metric', None)
        if metric is None:
            raise AttributeError("子类必须定义metric指标。")
        metric.labels(method=method, endpoint=endpoint, application=self.server_name, status=status).inc()


class HttpRequestLatencySecondsMetrics(BaseMetrics):
    metrics_type = "http_request_latency_seconds"
    metric = Histogram(
        'http_request_latency_seconds', 'Request latency',
        ['endpoint', 'method', 'application']
    )

    def get_label(self, method, endpoint, *args, **kwargs):
        """

        :param method:
        :param endpoint:
        :param start_time:
        :return:
        """
        metric = getattr(self, 'metric', None)
        if metric is None:
            raise AttributeError("子类必须定义metric指标。")
        start_time = kwargs.get('start_time', time.time())
        resp_time = int((time.time() - start_time) * 1000)
        metric.labels(endpoint=endpoint, method=method, application=self.server_name).observe(resp_time)


metric_cls_dict = {
    'http_requests_total': HttpRequestsTotalMetrics,
    'http_request_latency_seconds': HttpRequestLatencySecondsMetrics,
}
