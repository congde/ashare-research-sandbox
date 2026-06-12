# 评估流程说明

本文档说明如何使用评估脚本进行效果评估。

## 评估步骤

评估流程分为三个步骤，需要按顺序执行：

### 步骤 1: 获取流式结果并提取 sessionId 和 qaId

运行 `get_sse_result.py` 脚本，该脚本会：

1. 从 `../data/Kia0.7效果评估数据集.xlsx` 读取测试查询
2. 自动识别包含查询的列（支持 `query`、`Query`、`问题`、`问题内容`、`question` 等列名）
3. 使用多线程并发（最大并发数为 10）向 API 发送请求获取流式响应结果
4. 将流式结果保存到 `sse_results/` 目录，文件名格式：`{index}_{tool_name}_{query}.txt`
5. 从响应中提取 `sessionId` 和 `qaId`
6. 将映射关系保存到 `line_num_id_mapping.json`，其中 `tool_name` 来自 Excel 工作表名称

**执行命令：**

```bash
python get_sse_result.py
```

**输出文件：**

- `sse_results/`: 包含所有查询的流式响应结果文件
- `line_num_id_mapping.json`: 包含行号、查询、agentType、sessionId、qaId 和工具名称的映射关系

**注意事项：**

- 脚本会自动从 Excel 文件的所有工作表中读取查询，每个工作表名称作为该工作表下查询的 `tool_name`
- 每个查询会随机选择 `QUICK_REASONING` 或 `DEEP_THINK` 作为 agentType（7:3 比例）
- 使用多线程并发处理，无需手动添加延迟

---

### 步骤 2: 获取历史数据

运行 `get_history_result.py` 脚本，该脚本会：

1. 从 `line_num_id_mapping.json` 读取 sessionId
2. 调用历史数据 API 获取完整的对话历史
3. 将历史数据合并到映射文件中
4. 保存到 `line_num_id_mapping_with_result.json`

**执行命令：**

```bash
python get_history_result.py
```

**输入文件：**

- `line_num_id_mapping.json`: 步骤 1 生成的映射文件

**输出文件：**

- `line_num_id_mapping_with_result.json`: 包含完整历史数据的映射文件

**注意事项：**

- 脚本会为每个 sessionId 调用 API 获取历史数据
- 每处理 10 条记录会自动保存一次，避免数据丢失
- 请求之间会有 0.5 秒延迟

---

### 步骤 3: 导出数据到 Excel

运行 `dump_history_to_csv.py` 脚本，该脚本会：

1. 从 `line_num_id_mapping_with_result.json` 读取数据
2. 按 `tool_name` 分组数据，每个 `tool_name` 创建一个独立的工作表
3. 提取以下字段：
   - `query`: 查询内容
   - `agentType`: 代理类型（QUICK_REASONING 或 DEEP_THINK）
   - `sessionId`: 会话ID
   - `qaId`: 问答ID
   - `tool_name`: 使用的工具名称
   - `tool_args`: 工具参数
   - `tool_result`: 工具执行结果
   - `deep_think`: 深度思考内容
   - `answer_content`: 回答内容
   - `followup_questions`: 后续问题建议
4. 将数据导出为 Excel 文件（.xlsx 格式），每个工作表对应一个 `tool_name`

**执行命令：**

```bash
python dump_history_to_csv.py
```

**输入文件：**

- `line_num_id_mapping_with_result.json`: 步骤 2 生成的包含历史数据的文件

**输出文件：**

- `extracted_data.xlsx`: 导出的 Excel 数据文件，按 tool_name 分组到不同工作表

---

## 完整流程示例

```bash
# 1. 获取流式结果
python get_sse_result.py

# 2. 获取历史数据
python get_history_result.py

# 3. 导出到 Excel
python dump_history_to_csv.py
```

## 文件说明

### 输入文件

- `../data/Kia0.7效果评估数据集.xlsx`: 测试数据集 Excel 文件

### 中间文件

- `line_num_id_mapping.json`: 行号与 ID 的映射关系（步骤 1 输出，步骤 2 输入）
- `line_num_id_mapping_with_result.json`: 包含完整历史数据的映射文件（步骤 2 输出，步骤 3 输入）
- `sse_results/`: 流式响应结果目录（步骤 1 输出）

### 输出文件

- `extracted_data.xlsx`: 最终导出的评估数据 Excel 文件（步骤 3 输出），按 tool_name 分组到不同工作表

## 注意事项

1. **执行顺序**：必须按照步骤 1 → 步骤 2 → 步骤 3 的顺序执行
2. **API 配置**：脚本中的 API URL 和 Cookie 可能需要根据实际情况更新
3. **数据文件路径**：确保 Excel 文件路径正确（`../data/Kia0.7效果评估数据集.xlsx`）
4. **网络连接**：所有步骤都需要网络连接以调用 API
5. **执行时间**：根据数据量大小，整个过程可能需要较长时间，请耐心等待
