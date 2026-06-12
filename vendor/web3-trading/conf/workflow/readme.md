# WorkFlow 说明文档

本文档用于说明 workflow 配置含义、执行流程与维护方式，便于产品、运营和开发协同使用该工作流。

## 1. 工作流目标

- 对用户问句做结构化解析，提炼核心问题；
- 自动选择并调用合适工具获取事实与数据；
- 生成专业、准确的内容。

## 2. 配置文件位置

- 主配置文件：`conf/workflow`

## 3. 顶层配置说明

### 3.1 `enable`

- 类型：`bool`
- 当前值：`true`
- 作用：控制该工作流是否启用。

### 3.2 `enable_tools`

- 类型：`bool`
- 当前值：`true`
- 作用：是否启用工具调用阶段。

### 3.3 `available_tools`

- 类型：`list[str]`
- 当前工具列表：
	- `retrieve_fundamental_events`
	- `get_crypto_investment_outlook`
	- `coin_screener`
	- `web_search`
    - ......
- 作用：限定该工作流在规划阶段可被选择的工具范围。
- 备注：不填写available_tools值，表示“默认选择所有工具”。

### 3.4 `skill_config`

- 类型：`dict`
- 是否必填：否（可选）
- 作用：承载流程各阶段的配置（如 `query_parse_prompt`、`plan_prompt`、`synthesize_prompt` 等）。
- 备注：不配置时流程使用默认行为（跳过未配置阶段或按默认参数执行）。

### 3.5 `enable_memory`

- 类型：`bool`
- 默认值：`true`
- 作用：控制该 workflow 是否启用长期记忆能力（召回 + 写入）。
- 备注：
  - `true`：在 `plan` 阶段召回记忆，在 `synthesize` 阶段写入记忆。
  - `false`：完全跳过记忆召回和记忆写入，适合一次性任务（如币种洞察类场景）。

## 4. 三阶段执行链路

该工作流按以下顺序执行：

1. 问句解析（`query_parse_prompt`）
2. 工具规划与调用（`plan_prompt`）
3. 结果综合输出（`synthesize_prompt`）

---

### 4.1 问句解析：`query_parse_prompt`

- 是否必填：否（可选）
- 不配置时：跳过“问句解析”阶段，直接使用原始用户问句进入后续流程。

配置项：

- `name`: `seo_faq_generator_query_parse_prompt`，模版名称，搜索优先级：linku -> src/agent/prompt -> 下方默认模版template
- `template`: 将用户问句整理为清晰、简洁、便于工具调用的查询语句
- `before_callback`:
    - 该配置为可选项
    - 作用：在调用LLM前执行预处理
    - 示例：`src.agent.tools.kcbot.before_example`，before_example为协程，接收参数state
        ```python
        async def before_example(state):
            # 在LLM调用前修改state或添加日志
            pass
        ```
- `after_callback`:
    - 该配置为可选项
    - 作用：在调用LLM后执行后处理，可访问LLM响应
    - 示例：`src.agent.tools.kcbot.after_example`，after_example为协程，接收参数state, response
        ```python
        async def after_example(state, response):
            # 在LLM调用后处理response或记录结果
            pass
        ```

职责：

- 提炼用户的核心查询内容；
- 识别用户意图，减少歧义；
- 为后续规划阶段提供标准化输入。

---

### 4.2 工具规划：`plan_prompt`

- 是否必填：否（可选）
- 不配置时：跳过“工具规划”阶段，直接进入后续流程。

配置项：

- `name`: `seo_faq_generator_plan_prompt`，模版名称，搜索优先级：linku -> src/agent/prompt -> 下方默认模版template
- `template`: 让模型扮演任务规划师，筛选适配工具并给出调用参数
- `before_callback`:
    - 该配置为可选项
    - 作用：在调用LLM前执行预处理，可动态修改工具列表
    - 示例：`src.agent.tools.kcbot.before_add_tools`，before_add_tools为协程，接收参数tools, state
        ```python
        async def before_add_tools(tools, state):
            # 在LLM调用前修改工具列表或添加自定义工具
            pass
        ```
- `after_callback`:
    - 该配置为可选项
    - 作用：在调用LLM后执行后处理，可访问LLM响应和工具调用决策
    - 示例：`src.agent.tools.kcbot.after_plan`，after_plan为协程，接收参数tools, state, response
        ```python
        async def after_plan(tools, state, response):
            # 在LLM调用后记录规划结果或修改工具调用
            pass
        ```

职责：

- 基于解析后的问句选择最合适的工具；
- 输出工具调用参数；
- 在回调中动态补充/加工工具信息（支持参数 `tools`、`state`）。

---

### 4.3 内容总结：`synthesize_prompt`

- 是否必填：是

配置项：

- `name`: `seo_faq_generator_synthesize_prompt`，模版名称，搜索优先级：linku -> src/agent/prompt -> 下方默认模版template
- `template`: 根据工具返回结果生成专业、准确、有深度且 SEO 友好的 FAQ
- `response_format`: 
    - 该配置为可选项
    - 作用：指定合成阶段的结构化输出模型，确保LLM返回结果符合预定义格式
    - 示例：`workflow.process.FaqModel`，对应模型定义如下：
        ```python
        from pydantic import BaseModel

        
        class FaqModel(BaseModel):
            """FAQ 内容模型"""
            title: str  # FAQ 标题
            questions: list[str]  # 常见问题列表
            answers: list[str]  # 对应答案列表
            keywords: list[str]  # SEO 关键词
            summary: str  # 内容摘要
        ```
    - 备注：response_format 确保输出可直接序列化为指定模型，便于后续系统处理
- `before_callback`:
    - 该配置为可选项
    - 作用：在调用LLM前执行预处理，可准备数据或修改状态
    - 示例：`src.agent.tools.kcbot.before_synthesize`，before_synthesize为协程，接收参数state
        ```python
        async def before_synthesize(state):
            # 在LLM调用前准备数据或修改状态
            pass
        ```
- `after_callback`:
    - 该配置为可选项
    - 作用：在调用LLM后执行后处理，可访问LLM响应和最终结果
    - 示例：`src.agent.tools.kcbot.after_synthesize`，after_synthesize为协程，接收参数state, response
        ```python
        async def after_synthesize(state, response):
            # 在LLM调用后处理结果或记录日志
            pass
        ```

职责：

- 汇总工具数据并完成回答；
- 输出可直接用于 FAQ 场景的内容；
- 保持内容质量与可读性。

## 5. Prompt 字段通用规范

每个 Prompt 节点均包含以下字段：

- `name`：Prompt 唯一标识，便于日志与排障；
- `template`：给大模型的指令模板；
- `before_callback`：LLM调用前处理函数（可选）。
- `after_callback`：LLM调用后处理函数（可选）。

