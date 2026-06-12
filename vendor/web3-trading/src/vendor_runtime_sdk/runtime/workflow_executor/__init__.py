# -*- coding: utf-8 -*-
"""
runtime.workflow_executor — DAG-based workflow execution engine.

Refactored from a single 1874-line file into handler-based modules.
External import paths are preserved:
    from vendor_runtime_sdk.runtime.workflow_executor import WorkflowExecutor
"""

from vendor_runtime_sdk.runtime.workflow_executor._helpers import (  # noqa: F401
    _ACTIVE_EXECUTORS,
    _MAX_SUBWORKFLOW_DEPTH,
    _WorkflowRuntimeFacade,
)
from vendor_runtime_sdk.runtime.workflow_executor._core import WorkflowExecutorCore
from vendor_runtime_sdk.runtime.workflow_executor._handlers_agent import HandlersAgentMixin
from vendor_runtime_sdk.runtime.workflow_executor._handlers_basic import HandlersBasicMixin
from vendor_runtime_sdk.runtime.workflow_executor._handlers_io import HandlersIoMixin
from vendor_runtime_sdk.runtime.workflow_executor._handlers_code import HandlersCodeMixin
from vendor_runtime_sdk.runtime.workflow_executor._handlers_task import HandlersTaskMixin
from vendor_runtime_sdk.runtime.workflow_executor._persistence import PersistenceMixin
from vendor_runtime_sdk.runtime.workflow_executor._lifecycle import LifecycleMixin
from vendor_runtime_sdk.runtime.workflow_executor._review import ReviewMixin
from vendor_runtime_sdk.runtime.workflow_executor._generators import GeneratorsMixin


class WorkflowExecutor(
    WorkflowExecutorCore,
    HandlersAgentMixin,
    HandlersBasicMixin,
    HandlersIoMixin,
    HandlersCodeMixin,
    HandlersTaskMixin,
    PersistenceMixin,
    LifecycleMixin,
    ReviewMixin,
    GeneratorsMixin,
):
    """
    DAG-based workflow execution engine.

    Composes all handler mixins via multiple inheritance.
    The __init__ and core orchestration logic live in WorkflowExecutorCore.
    """
    pass
