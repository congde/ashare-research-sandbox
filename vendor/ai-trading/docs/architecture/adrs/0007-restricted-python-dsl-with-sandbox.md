# ADR-0007：受限 Python DSL + AST + Docker 沙箱三层防护

**状态**：accepted
**日期**：2026-05-08
**决策者**：CTO + 安全负责人

---

## 1. 背景与问题

PRD §3.3 / §10.1 / §10.3 强调：

- LLM 生成代码可能包含恶意调用（os.system / requests / 网络出站）
- 用户也可能手动编辑 AI 代码引入风险
- 实盘运行环境需要"绝对可信"

如何让"用户可写策略"和"系统安全"兼得？

## 2. 决策驱动力

- 错误代码 = 资金损失（PRD §10.1 极高风险）
- 不能强迫用户用纯 DSL（学习曲线高）
- Python 表达力是核心卖点（freqtrade / jesse 都用 Python）
- 必须有"机制"保证安全，不能依赖"用户自觉"

## 3. 候选方案

### 方案 A：完全自由 Python（freqtrade / jesse 风格）
- 优点：表达力强 / 用户熟悉
- 缺点：
  - LLM 生成 `os.system("rm -rf /")` 直接写入
  - 用户手写恶意代码
  - 平台无法控制
- 推荐度：⭐（v1.0 不可接受）

### 方案 B：DSL 不用 Python（自定义语法）
- 优点：100% 可控
- 缺点：
  - 学习曲线高
  - 失去 pandas / numpy / talib 等库
  - LLM 生成质量低（训练数据少）
- 推荐度：⭐⭐

### 方案 C（推荐）：受限 Python DSL + 三层防护
- 优点：
  - Python 表达力 + 安全可控
  - LLM 训练数据丰富
  - pandas / numpy / talib 可用
  - 可逐层降级
- 缺点：实现稍复杂（一次到位即可）
- 推荐度：⭐⭐⭐⭐⭐

## 4. 选定方案

**方案 C：受限 Python DSL + AST + Docker 沙箱三层防护**

### 三层防护架构

```
┌──────────────────────────────────────────────────────┐
│ 防护层 1：受限 Python DSL                              │
│   - 白名单 import（pandas/numpy/talib/decimal/...）   │
│   - 禁止 import os/sys/subprocess/socket/urllib/...   │
│   - 用户函数签名固定: on_tick(ctx, candle) -> Action  │
│   - 不允许 import 其他用户的策略                      │
│   - 受限 attribute access（无 __globals__ 等 dunder） │
└──────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────┐
│ 防护层 2：AST 静态校验（保存前 + 部署前必跑）           │
│   - ast.parse → walk → 检查 dangerous nodes           │
│   - 禁止 eval / exec / compile / __import__           │
│   - 禁止 attribute chain 反射 __globals__ / __class__ │
│   - 禁止 lambda 注入闭包逃逸                         │
│   - 禁止 try/except 屏蔽安全错误                     │
└──────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────┐
│ 防护层 3：Docker 沙箱（实盘 + 回测都走）              │
│   - 复用 WorkDAO core/sandbox/                        │
│   - CPU 0.5 / 内存 256 MB / pids 100                  │
│   - 网络出站白名单（CEX 域名）                       │
│   - 文件系统 read-only + tmpfs                       │
│   - 仅写自己状态目录 /app/state/<strategy_id>/       │
│   - seccomp + AppArmor + drop ALL capabilities       │
│   - no_new_privileges                                │
└──────────────────────────────────────────────────────┘
```

### 受限 DSL 白名单（v1.0）

```python
# domain/strategy/dsl/safelist.py
ALLOWED_IMPORTS = {
    # 数据科学
    "pandas", "numpy", "talib", "decimal", "math", "statistics",
    "datetime", "typing", "dataclasses", "json",
    # 平台 SDK
    "ai_trading.api",
}

ALLOWED_API_FROM_PLATFORM = {
    "ai_trading.api.fetch_ohlcv",
    "ai_trading.api.fetch_ticker",
    "ai_trading.api.position",
    "ai_trading.api.order_intent",   # 仅返回 OrderIntent，不直接下单
    "ai_trading.api.log",
}

DENIED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "urllib", "requests",
    "http.client", "asyncio.subprocess", "ctypes", "importlib",
    "_thread", "threading", "multiprocessing", "concurrent",
    "ast", "code", "codeop",
}

DENIED_BUILTINS = {
    "eval", "exec", "compile", "__import__", "open",
    "input", "globals", "locals", "vars", "memoryview",
}

DENIED_ATTRS = {
    # 反射逃逸
    "__globals__", "__class__", "__bases__", "__subclasses__",
    "__builtins__", "__import__", "__loader__", "__spec__",
    # 危险 API
    "system", "popen", "execvp", "spawn",
}
```

### 用户策略示例（合规）

```python
# strategies/my_grid.py
from ai_trading.api import fetch_ohlcv, position, order_intent, log
import pandas as pd
import numpy as np

def on_tick(ctx, candle):
    """每个 tick 调用一次"""
    df = fetch_ohlcv(ctx.symbol, "1h", limit=200)
    sma_20 = df["close"].rolling(20).mean().iloc[-1]
    sma_50 = df["close"].rolling(50).mean().iloc[-1]

    pos = position(ctx.symbol)

    if sma_20 > sma_50 and pos.qty == 0:
        return order_intent(side="buy", qty=0.01, type="market")
    elif sma_20 < sma_50 and pos.qty > 0:
        return order_intent(side="sell", qty=pos.qty, type="market")

    return None
```

### 用户策略示例（拦截）

```python
# 防护层 1 拦截：禁止 import os
import os                           # ❌ AST 拒绝

# 防护层 2 拦截：禁止 eval
eval("1 + 1")                       # ❌ AST 拒绝

# 防护层 2 拦截：__class__ 反射逃逸
().__class__.__bases__              # ❌ AST 拒绝

# 防护层 3 拦截：sandbox 网络出站
import urllib.request               # 防护层 1 已拒绝；即使绕过，sandbox 也 deny
urllib.request.urlopen("https://evil.com")
```

## 5. 后果

### 正面

- LLM 生成代码即使有"幻觉" `os.system`，也被三层拦截
- 用户手动编辑后必经 AST 校验，篡改难
- Docker 沙箱即使前两层都被绕过也兜底
- 复用 WorkDAO `core/sandbox` 减少新建工作

### 负面

- 用户可能抱怨"不能用某些库"（白名单逐步扩展机制 + 提交 RFC 流程）
- AST 校验性能开销（每次保存 / 部署前跑一次，~50ms）
- Docker 启动延迟（~1-2 s 首次冷启动）—— 用 prewarm pool 缓解

### 中性 / 待观察

- v1.5 是否引入 gVisor / Firecracker？取决于性能
- 是否允许部分用户"高级模式"绕过白名单？暂不允许

### 触发的后续工作

- 实现 `domain/strategy/dsl/{safelist,ast_checker,validator}.py`
- 集成 `core/sandbox` Docker 模式（已有，仅增加交易特化网络白名单）
- AntiGuide：用户提交策略 → AST fail → 返回友好错误
- LLM Prompt：在 system prompt 中明示 DSL 边界（减少幻觉）
- Eval 集：抗 LLM 幻觉 Eval（20+ 用例，故意诱导生成 os/socket/eval）

## 6. 关联

- 相关 ADR：[ADR-0001 Fork](0001-fork-workdao-baseline.md), [ADR-0008 Risk Agent](0008-risk-agent-independent.md)
- PRD 章节：[PRD §3.3](../../prd.md#33-自然语言--可执行策略-的工作流), [PRD §10.1/§10.3](../../prd.md#10-风险与缓解), [PRD §4.1 F-SE-01](../../prd.md#41-p0--mvp-必备6-个月发布的最小集合)
- 架构文档：[ADD §06.2 沙箱](../06-security-compliance.md#62-沙箱执行sandbox-三层防护), [ADD §03 Multi-Agent](../03-multi-agent-collaboration.md)
- 详细设计：[SDLC §03-detailed-design/04 strategy-runtime-sandbox](../../implementation/03-detailed-design/04-strategy-runtime-sandbox.md), [§11 strategy-dsl](../../implementation/03-detailed-design/11-strategy-dsl.md)

## 7. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| 1.0 | 2026-05-08 | 初版 | CTO |
