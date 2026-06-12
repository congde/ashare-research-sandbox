# -*- coding: utf-8 -*-
"""
DAG Executor - 工具调用的 DAG 执行引擎

支持基于有向无环图(DAG)的工具编排，实现串行和并行调用。
与 BaseAgent 集成，用于复杂多任务场景。
"""
import uuid
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Any
from collections import defaultdict
from pydantic import BaseModel, Field

from agent.plan.task_graph import TaskStatus
from agent.utils import truncate_web_search_query

logger = logging.getLogger(__name__)


class DAGTask(BaseModel):
    """DAG 任务节点定义"""
    id: str = Field(..., description="任务ID")
    name: str = Field(..., description="任务名称")
    tool: str = Field(..., description="工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="工具参数")
    depends_on: List[str] = Field(default_factory=list, description="依赖的任务ID列表")
    output_key: str = Field(..., description="输出结果的key")
    description: str = Field("", description="任务描述")
    criticality: str = Field("normal", description="关键性: critical / normal / low")
    result: Optional[Any] = None
    status: TaskStatus = TaskStatus.PENDING
    error: str = Field("", description="错误信息")
    _tool_call_id: Optional[str] = None

    @property
    def tool_name(self) -> str:
        return self.tool

    @property
    def raw_result(self) -> Any:
        if self.result is not None:
            try:
                return json.loads(self.result)
            except Exception:
                return self.result
            
    @property
    def enable_reply(self) -> bool:
        if isinstance(self.raw_result, dict) and self.raw_result.get("disable_llm"):
            return True
        return False

    @property
    def tool_call_id(self) -> Optional[str]:
        if self.tool is None:
            return None
        if self._tool_call_id is None:
            self._tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        return self._tool_call_id

    @property
    def is_tool_node(self) -> bool:
        return self.tool is not None


class DAGPlan(BaseModel):
    """DAG 执行计划"""
    _CARD_TOOLS = ('coin_screener', 'recharge_and_withdraw')

    dag_id: str = Field("", description="DAG ID")
    description: str = Field("", description="DAG描述")
    tasks: List[DAGTask] = Field([], description="任务列表")
    max_parallel: int = Field(10, description="最大并行数")
    resource_references: List[Dict[str, Any]] = Field(default_factory=list, description="资源引用列表")

    def has_resource_references(self) -> bool:
        return bool(self.resource_references)
        # from agent.schema import ReferenceType, ResourceReference,
        # ResourceReference(
        #     eventId=ref["tool_call_id"],
        #     name=ref["tool_name"],
        #     type=ReferenceType(ref["ref_type"]),
        #     style={},
        #     data=ref["data"],
        # ).model_dump(mode="json")


class DAGExecutionResult(BaseModel):
    """DAG 执行结果"""
    dag_id: str
    success: bool
    context: Dict[str, Any] = Field(default_factory=dict, description="所有任务输出的上下文")
    completed_tasks: List[str] = Field(default_factory=list, description="已完成的任务ID")
    failed_tasks: List[str] = Field(default_factory=list, description="失败的任务ID")
    total_elapsed_ms: int = 0
    error: Optional[str] = None


class DAGExecutor:
    """
    DAG 执行器
    
    基于入度(in-degree)算法实现任务的并行/串行调度。
    - 入度为0的任务可以并行执行
    - 任务完成后，更新下游任务的入度
    - 重复直到所有任务完成
    """

    _GRACEFUL_FAIL_TOOLS = {"recharge_and_withdraw"}

    def __init__(self, tool_registry, max_parallel: int = 10,
                 critical_max_retries: int = 0, critical_retry_delay: float = 0.5):
        """
        Args:
            tool_registry: ToolRegistry 实例，用于工具调用
            max_parallel: 最大并行任务数
            critical_max_retries: 关键任务（criticality="critical"）失败后的额外重试次数，0=不重试
            critical_retry_delay: 关键任务重试间隔（秒）
        """
        self.tool_registry = tool_registry
        self.max_parallel = max_parallel
        self.critical_max_retries = critical_max_retries
        self.critical_retry_delay = critical_retry_delay
        self._last_result: Optional[DAGExecutionResult] = None
        self._tasks_dict: Dict[str, DAGTask] = {}
    
    async def execute(self, plan: DAGPlan) -> DAGExecutionResult:
        """
        执行 DAG 计划
        
        Args:
            plan: DAG执行计划
            
        Returns:
            DAGExecutionResult: 执行结果
        """
        start_time = time.time()
        dag_id = plan.dag_id
        tasks_dict = {task.id: task for task in plan.tasks}
        self._tasks_dict = tasks_dict
        context = {}  # 存储所有任务的输出
        completed = set()  # 已完成的任务ID
        failed = set()  # 失败的任务ID
        
        # 初始化入度
        in_degree = {
            task_id: len(task.depends_on)
            for task_id, task in tasks_dict.items()
        }
        
        logger.info(f"[DAG-{dag_id}] Starting execution with {len(plan.tasks)} tasks")
        logger.info(f"[DAG-{dag_id}] Initial in_degree: {in_degree}")
        
        # 寻找第一批可执行任务（入度为0）
        ready = [task_id for task_id, deg in in_degree.items() if deg == 0]
        
        if not ready:
            error_msg = f"No executable tasks found (all tasks have dependencies). Possible circular dependency."
            logger.error(f"[DAG-{dag_id}] {error_msg}")
            return DAGExecutionResult(
                dag_id=dag_id,
                success=False,
                error=error_msg,
                total_elapsed_ms=int((time.time() - start_time) * 1000)
            )
        
        layer = 0
        
        # 迭代执行各层任务
        while ready:
            layer += 1
            logger.info(f"[DAG-{dag_id}] Layer {layer} - Executing {len(ready)} tasks in parallel: {ready}")
            
            tasks_to_execute = [
                self._execute_task_with_retry(tasks_dict[task_id], context)
                for task_id in ready
            ]
            results = await asyncio.gather(*tasks_to_execute, return_exceptions=True)
            
            # 处理结果
            newly_completed = []
            for task_id, result in zip(ready, results):
                task = tasks_dict[task_id]
                
                if isinstance(result, Exception):
                    logger.error(f"[DAG-{dag_id}] Task [{task_id}] failed: {result}")
                    failed.add(task_id)
                    # 将错误信息也存入context，供下游任务感知
                    context[task.output_key] = {"error": str(result), "success": False}
                else:
                    logger.info(f"[DAG-{dag_id}] Task [{task_id}] completed -> {task.output_key}")
                    completed.add(task_id)
                    newly_completed.append(task_id)
                    # 存储任务输出
                    context[task.output_key] = result
            
            # 更新下游任务的入度
            for finished_id in newly_completed:
                for other_id, other_task in tasks_dict.items():
                    if finished_id in other_task.depends_on:
                        in_degree[other_id] -= 1
                        logger.debug(f"[DAG-{dag_id}] Task [{other_id}] in_degree: {in_degree[other_id] + 1} → {in_degree[other_id]}")
            
            # 寻找下一批可执行任务
            ready = [
                task_id for task_id, deg in in_degree.items()
                if deg == 0 and task_id not in completed and task_id not in failed
            ]
            
            logger.info(f"[DAG-{dag_id}] Next ready queue: {ready if ready else '[]'}")
        
        # 检查是否所有任务都完成
        total_elapsed_ms = int((time.time() - start_time) * 1000)
        all_completed = len(completed) + len(failed) == len(plan.tasks)
        success = len(failed) == 0 and all_completed
        
        if not all_completed:
            unfinished = set(tasks_dict.keys()) - completed - failed
            error_msg = f"DAG execution incomplete. Unfinished tasks: {list(unfinished)}. Possible circular dependency."
            logger.error(f"[DAG-{dag_id}] {error_msg}")
        else:
            logger.info(f"[DAG-{dag_id}] Execution completed in {total_elapsed_ms}ms. Success: {len(completed)}, Failed: {len(failed)}")
        
        return DAGExecutionResult(
            dag_id=dag_id,
            success=success,
            context=context,
            completed_tasks=list(completed),
            failed_tasks=list(failed),
            total_elapsed_ms=total_elapsed_ms,
            error=error_msg if not all_completed else None
        )
    
    async def execute_with_progress(self, plan: DAGPlan, progress_callback=None):
        """
        执行 DAG 计划，并通过回调函数报告进度
        
        Args:
            plan: DAG执行计划
            progress_callback: 异步回调函数，签名为 async def callback(event_type, task_id, task_name, **kwargs)
                事件类型：
                - "layer_start": 开始执行某层
                - "task_start": 开始执行某个任务
                - "task_complete": 任务执行完成
                - "task_failed": 任务执行失败
                - "layer_complete": 某层执行完成
            
        Yields:
            来自progress_callback的流式输出（如果callback是generator）
        """
        start_time = time.time()
        dag_id = plan.dag_id
        tasks_dict = {task.id: task for task in plan.tasks}
        self._tasks_dict = tasks_dict
        context = {}
        completed = set()
        failed = set()
        
        # 初始化入度
        in_degree = {
            task_id: len(task.depends_on)
            for task_id, task in tasks_dict.items()
        }
        
        logger.info(f"[DAG-{dag_id}] Starting execution with progress tracking")
        
        # 寻找第一批可执行任务
        ready = [task_id for task_id, deg in in_degree.items() if deg == 0]
        
        if not ready:
            error_msg = f"No executable tasks found. Possible circular dependency."
            logger.error(f"[DAG-{dag_id}] {error_msg}")
            self._last_result = DAGExecutionResult(
                dag_id=dag_id,
                success=False,
                error=error_msg,
                total_elapsed_ms=int((time.time() - start_time) * 1000)
            )
            return
        
        layer = 0
        
        # 迭代执行各层任务
        while ready:
            layer += 1
            layer_start = time.time()
            
            # 触发 layer_start 事件
            if progress_callback:
                async for event in progress_callback("layer_start", "", "", layer=layer, task_count=len(ready)):
                    yield event
            
            logger.info(f"[DAG-{dag_id}] Layer {layer} - Executing {len(ready)} tasks: {ready}")

            # Emit task_start events for all tasks in this layer
            for idx, task_id in enumerate(ready):
                task = tasks_dict[task_id]
                if progress_callback:
                    async for event in progress_callback(
                        "task_start", task_id, task.name,
                        layer=layer, index=idx, total_in_layer=len(ready)
                    ):
                        yield event

            # Run all same-layer tasks in parallel
            task_starts = {tid: time.time() for tid in ready}
            gather_results = await asyncio.gather(
                *(self._execute_task_with_retry(tasks_dict[tid], context) for tid in ready),
                return_exceptions=True,
            )

            # Process results and emit progress events
            for task_id, result in zip(ready, gather_results):
                task = tasks_dict[task_id]
                task_elapsed = int((time.time() - task_starts[task_id]) * 1000)

                if isinstance(result, Exception):
                    logger.error(
                        f"[DAG-{dag_id}] Task [{task_id}] failed "
                        f"(criticality={task.criticality}): {result}"
                    )
                    failed.add(task_id)
                    context[task.output_key] = {"error": str(result), "success": False}
                    if progress_callback:
                        async for event in progress_callback(
                            "task_failed", task_id, task.name,
                            error=str(result), elapsed_ms=task_elapsed
                        ):
                            yield event
                else:
                    completed.add(task_id)
                    context[task.output_key] = result
                    if progress_callback:
                        async for event in progress_callback(
                            "task_complete", task_id, task.name,
                            elapsed_ms=task_elapsed
                        ):
                            yield event
            
            layer_elapsed = int((time.time() - layer_start) * 1000)
            
            # 触发 layer_complete 事件
            if progress_callback:
                async for event in progress_callback(
                    "layer_complete", "", "", 
                    layer=layer, elapsed_ms=layer_elapsed
                ):
                    yield event
            
            # 更新下游任务的入度
            for finished_id in ready:
                if finished_id in completed:  # 只处理成功的任务
                    for other_id, other_task in tasks_dict.items():
                        if finished_id in other_task.depends_on:
                            in_degree[other_id] -= 1
            
            # 寻找下一批可执行任务
            ready = [
                task_id for task_id, deg in in_degree.items()
                if deg == 0 and task_id not in completed and task_id not in failed
            ]
        

        # 构建最终结果
        total_elapsed_ms = int((time.time() - start_time) * 1000)
        all_completed = len(completed) + len(failed) == len(plan.tasks)
        success = len(failed) == 0 and all_completed
        
        if not all_completed:
            unfinished = set(tasks_dict.keys()) - completed - failed
            error_msg = f"DAG incomplete. Unfinished: {list(unfinished)}"
            logger.error(f"[DAG-{dag_id}] {error_msg}")
        else:
            logger.info(f"[DAG-{dag_id}] Completed. Success: {len(completed)}, Failed: {len(failed)}")
        
        self._last_result = DAGExecutionResult(
            dag_id=dag_id,
            success=success,
            context=context,
            completed_tasks=list(completed),
            failed_tasks=list(failed),
            total_elapsed_ms=total_elapsed_ms,
            error=error_msg if not all_completed else None
        )
    
    def get_last_result(self) -> Optional[DAGExecutionResult]:
        """获取最后一次执行的结果"""
        return self._last_result
    
    async def _execute_task(self, task: DAGTask, context: Dict[str, Any]) -> Any:
        """
        执行单个任务
        
        Args:
            task: 任务定义
            context: 共享上下文，包含前置任务的输出
            
        Returns:
            任务执行结果
        """
        logger.info(f"[Task-{task.id}] Executing: {task.name} (tool: {task.tool})")
        
        # 检查依赖任务是否都成功
        for dep_id in task.depends_on:
            dep_task = self._tasks_dict.get(dep_id)
            if dep_task is None:
                continue
            dep_output_key = dep_task.output_key
            if dep_output_key in context:
                dep_result = context[dep_output_key]
                if isinstance(dep_result, dict) and not dep_result.get("success", True):
                    raise RuntimeError(f"Dependency task failed: {dep_id}")
        
        # 解析参数中的引用（如 {{btc_rsi_raw}}）
        resolved_args = self._resolve_arguments(task.arguments, context)
        if task.tool == "web_search" and "query" in resolved_args:
            resolved_args = {**resolved_args, "query": truncate_web_search_query(resolved_args["query"])}

        # 调用工具
        try:
            tool_wrapper = self.tool_registry.get_tool(task.tool)
            if not tool_wrapper:
                raise RuntimeError(f"Tool not found: {task.tool}")

            
            # 执行工具
            result = await tool_wrapper.execute(**resolved_args)
            
            # 检查工具级软失败（工具未抛异常但返回 success=False）
            if hasattr(result, 'success') and result.success is False:
                error_msg = getattr(result, 'error', '') or f"Tool '{task.tool}' returned failure"
                logger.warning(f"[Task-{task.id}] Tool returned soft failure: {error_msg}")
                if task.tool in self._GRACEFUL_FAIL_TOOLS:
                    fallback = self._build_graceful_fallback(task.tool, resolved_args)
                    logger.info(f"[Task-{task.id}] Tool '{task.tool}' is in graceful-fail list, using fallback payload")
                    return {
                        "success": True,
                        "content": fallback,
                        "data": json.loads(fallback),
                        "metadata": {"graceful_fallback": True},
                        "error": "" 
                    }
                return {
                    "success": False,
                    "content": None,
                    "data": None,
                    "metadata": {},
                    "error": error_msg,
                }
            
            logger.info(f"[Task-{task.id}] Completed successfully")
            return {
                "success": True,
                "content": result.content if hasattr(result, 'content') else str(result),
                "data": result.data if hasattr(result, 'data') else result,
                "metadata": result.metadata if hasattr(result, 'metadata') else {},
                "error": ""
            }
            
        except Exception as e:
            logger.exception(f"[Task-{task.id}] Execution failed")
            raise RuntimeError(f"Task execution failed: {str(e)}") from e

    async def _execute_task_with_retry(
        self, task: "DAGTask", context: Dict[str, Any]
    ) -> Any:
        """对关键任务自动重试，非关键任务直接执行（零开销）。"""
        max_retries = (
            self.critical_max_retries if task.criticality == "critical" else 0
        )
        last_err: Optional[Exception] = None
        for attempt in range(1 + max_retries):
            try:
                result = await self._execute_task(task, context)
                task.result = result.get("content", "")
                if result.get("success"):
                    task.status = TaskStatus.COMPLETED
                else:
                    task.status = TaskStatus.FAILED
                    task.error = result.get("error", "Unknown error")
                return result
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    logger.warning(
                        f"[Task-{task.id}] critical task attempt {attempt + 1} failed, "
                        f"retrying in {self.critical_retry_delay}s: {e}"
                    )
                    await asyncio.sleep(self.critical_retry_delay)
        raise last_err  # type: ignore[misc]

    @staticmethod
    def _build_graceful_fallback(tool_name: str, arguments: Dict[str, Any]) -> str:
        """Build a minimal valid response for tools that should not hard-fail.
        Note: This payload is only used to avoid pipeline crash; cards are NOT rendered
        when graceful_fallback is True (see dag_execution: skip adding card refs).
        recharge_and_withdraw 调用参数应由 DAG 规划生成：tradeType(RECHARGE/WITHDRAW)、
        paymentMethodCode(充值 FAST_BUY / 提现 FAST_SELL、WITHDRAW、OTC_SELL、CRYPTO_WITHDRAW)、
        siteType、lang、query 等，以 MCP 工具 schema 为准。
        """
        if tool_name == "recharge_and_withdraw":
            return json.dumps({
                "tradeType": arguments.get("tradeType", "WITHDRAW"),
                "siteType": arguments.get("siteType", "global"),
                "paymentMethodList": [
                    {"paymentMethodCode": arguments.get("paymentMethodCode", "FAST_SELL")}
                ],
            }, ensure_ascii=False)
        return json.dumps(arguments, ensure_ascii=False)

    def _resolve_arguments(self, arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析参数中的上下文引用（递归处理嵌套 dict / list）
        
        支持的格式：
        - "{{output_key}}" - 引用其他任务的完整输出
        - "{{output_key.field}}" - 引用其他任务输出的特定字段
        
        Args:
            arguments: 原始参数
            context: 上下文数据
            
        Returns:
            解析后的参数
        """
        return self._resolve_value(arguments, context)

    def _resolve_value(self, value: Any, context: Dict[str, Any]) -> Any:
        """Recursively resolve {{...}} references in any value type."""
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            ref_path = value[2:-2].strip()
            ref_parts = ref_path.split(".")
            ref_value = context
            try:
                for part in ref_parts:
                    if isinstance(ref_value, dict):
                        ref_value = ref_value[part]
                    else:
                        ref_value = getattr(ref_value, part)
                return ref_value
            except (KeyError, AttributeError) as e:
                logger.warning(f"Failed to resolve reference '{ref_path}': {e}. Using raw value.")
                return value
        elif isinstance(value, dict):
            return {k: self._resolve_value(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_value(item, context) for item in value]
        return value
    
    @staticmethod
    def validate_dag(plan: DAGPlan) -> tuple[bool, Optional[str]]:
        """
        验证 DAG 的有效性
        
        检查：
        1. 是否有循环依赖
        2. 依赖的任务是否存在
        3. output_key 是否唯一
        
        Returns:
            (is_valid, error_message)
        """
        task_ids = {task.id for task in plan.tasks}
        output_keys = [task.output_key for task in plan.tasks]
        
        # 检查output_key唯一性
        if len(output_keys) != len(set(output_keys)):
            duplicates = [key for key in output_keys if output_keys.count(key) > 1]
            return False, f"Duplicate output_keys found: {set(duplicates)}"
        
        # 检查依赖任务是否存在
        for task in plan.tasks:
            for dep_id in task.depends_on:
                if dep_id not in task_ids:
                    return False, f"Task [{task.id}] depends on non-existent task: {dep_id}"
        
        # 检查循环依赖（使用拓扑排序）
        in_degree = defaultdict(int)
        for task in plan.tasks:
            in_degree[task.id] = len(task.depends_on)
        
        queue = [task_id for task_id in task_ids if in_degree[task_id] == 0]
        processed = 0
        
        while queue:
            current = queue.pop(0)
            processed += 1
            
            # 找到所有依赖当前任务的任务
            for task in plan.tasks:
                if current in task.depends_on:
                    in_degree[task.id] -= 1
                    if in_degree[task.id] == 0:
                        queue.append(task.id)
        
        if processed != len(task_ids):
            return False, "Circular dependency detected in DAG"
        
        return True, None


__all__ = ["DAGTask", "DAGPlan", "DAGExecutionResult", "DAGExecutor"]
