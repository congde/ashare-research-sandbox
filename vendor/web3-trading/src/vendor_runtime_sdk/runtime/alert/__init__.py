# -*- coding: utf-8 -*-
"""
runtime.alert — AlertPolicy evaluation & dispatch (T14-3).

Runtime evaluator that matches active ``alert_policies`` against live metrics
(balance, monthly spend, fallback rate, tool error rate) and fires ``AlertEvent``
records plus optional Lark push notifications.
"""

from vendor_runtime_sdk.runtime.alert.consumer import (
    AlertPolicyConsumer,
    get_consumer,
    reset_consumer_for_tests,
)
from vendor_runtime_sdk.runtime.alert.evaluator import (
    AlertFireResult,
    AlertMetrics,
    AlertPolicyEvaluator,
)

__all__ = [
    "AlertFireResult",
    "AlertMetrics",
    "AlertPolicyConsumer",
    "AlertPolicyEvaluator",
    "get_consumer",
    "reset_consumer_for_tests",
]
