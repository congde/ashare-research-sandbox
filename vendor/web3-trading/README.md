# ai-web3-tradding-agent 服务

> 基于 Python FastAPI 构建的 AI 微服务

## 📖 项目概述

这是一个基于大模型开发的C端对话场景的AI Agent服务，遵循 KuCoin 微服务架构体系的标准部署规范。

## 🚀 快速开始

### 1. 依赖安装

```bash
# 安装 Python 依赖
pip3 install --no-cache-dir -r requirements.txt \
    -i https://nexus.kcprd.com/repository/mix-devops/simple \
    --trusted-host nexus.kcprd.com \
    --timeout 600
```

### 2. 运行服务

```bash
# 本地开发启动
python main.py

# 生产环境部署
bash run.sh
```

### 3. 接口文档

启动后访问：<http://127.0.0.1:10240/docs>

### 4. 项目配置介绍

#### 配置优先级

```text
.env文件 > APOLLO配置 > conf/default.yaml
```

#### .env 默认文件内容（新增变量名必须大写）

```bash
serverEnv = "local"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 10240
# 本地开发时用到的环境变量，该权重值最高，会覆盖conf/default.yaml里的值，注意该变量的key一定要使用大写定义
LOG_PATH = "./logs"
APOLLO_HOSTS="http://apollo-risk.kucoin:8080"
EUREKA_SERVER="https://eureka.dev.kucoin.net:443/eureka/"
ENABLE_AUTH = true
SECUREKEY = "global_password"
```

#### conf/default.yaml 默认文件内容（变量名小写）
```yaml
server_name: ai-web3-tradding-agent
server_host: 0.0.0.0
server_port: 10240

# 网关
eureka_server: http://eureka-risk.kucoin:1111/eureka/
eureka_username:
eureka_password:

# HTTP代理（只有访问公网才会被使用到）
kc_pro_http_proxy: http://sec-mwg-http9090-d29cc2af8b4c9871.elb.ap-northeast-1.amazonaws.com:9090
risk_pro_http_proxy: http://mwg-aws-ns2.kcprd.com:9090

# 白名单
white_list:

# API鉴权
enable_auth: true
securekey:
```

## 💻 开发指南

### 1. 业务接口开发

1. 在 `src/web/api/` 目录下定义业务接口
2. 参考 `demo.py` 示例文件
3. 继承 `BaseRouter` 类创建路由类
4. 所有 API 自动添加 `/api` 前缀

### 2. 应用架构说明

#### 核心组件

- **应用入口**: `main.py` - 通过 `src/web/application.py:create_app()` 创建 FastAPI 应用
- **应用工厂**: `src/web/application.py:create_app()` - 初始化 FastAPI，包含：
  - 自定义 APIRoute 类，提供请求/响应日志记录和监控
  - CORS 中间件配置
  - 基于环境的配置加载
  - 非本地环境的服务发现（Eureka）集成
- **路由系统**: `src/web/router.py` 提供：
  - `BaseRouter` 基类 - 所有 API 路由类的基类，自动添加 `/api` 前缀
  - `auto_import()` 函数 - 自动发现并注册 `src/web/api/` 下的路由类
  - 内置用户认证，通过 `user_id` 属性访问
- **自定义请求/响应处理**: `application.py` 中的 `APIRoute` 类提供：
  - 自动记录请求/响应日志，包含系统指标（内存）
  - 请求参数解析和验证
  - 自定义错误处理和 JSON 响应格式化
  - 请求耗时和性能监控

#### 配置管理

- **环境配置**:
  - `conf/default.yaml` - 默认服务配置
  - 通过 `python-dotenv` 加载环境变量
  - Apollo 配置服务集成，用于分布式配置管理
- **服务发现**:
  - `src/libs/eureka.py` 中的 Eureka 客户端集成
  - 环境特定的 Apollo 配置 URL
  - 健康检查端点：`/actuator/health`

#### 业务逻辑组织

- **API 端点**: 在 `src/web/api/` 目录下定义所有业务路由
  - 每个文件包含一个继承 `BaseRouter` 的类
  - 路由通过 `auto_import()` 自动发现和注册
  - 示例：`src/web/api/demo.py` 包含 `DemoApi` 类及演示路由
- **API 自带组件**: `src/web/` 包含：
  - `authenticator.py` - 内部服务调用，自带API鉴权token生成，使用get、post、stream、delete发送HTTP请求
- **共享库**: `src/libs/` 包含：
  - `apollo.py` - Apollo 配置服务客户端
  - `eureka.py` - 服务发现客户端
  - `http.py` - HTTP 客户端工具
  - `prometheus.py` - 指标收集
  - `wrapper.py` - 通用装饰器和工具
  - `run_sync.py` - 同步代码转异步代码，如：大模型推理

#### 监控和日志

- **请求生命周期监控**:
  - 记录所有请求的详细参数信息
  - 每个请求跟踪内存使用情况
  - 响应时间计算和记录
  - `src/web/middlewares.py` 中的自定义中间件
- **健康检查**:
  - `health.py` - 服务健康检查脚本
  - `postStart.py` - 部署后健康验证
  - `preStop.py` - 优雅关闭处理

## 📁 工程目录结构

```text
.
├── README.md
├── ci
│   └── ai-web3-tradding-agent
│       └── Dockerfile
├── conf
│   └── default.yaml
├── health.py
├── install.sh
├── main.py
├── postStart.py
├── preStop.py
├── requirements.txt
├── run.sh
└── src
    ├── libs
    │   ├── apollo.py
    │   ├── eureka.py
    │   ├── http.py
    │   ├── prometheus.py
    │   ├── run_sync.py
    │   └── wrapper.py
    └── web
        ├── api
        │   ├── demo.py
        │   └── monitor.py
        ├── application.py
        ├── authenticator.py
        ├── code_msg.py
        ├── config.py
        ├── context.py
        ├── exceptions.py
        ├── logger.py
        ├── middlewares.py
        ├── response.py
        └── router.py
```

## ⚠️ 开发注意事项

- 服务默认运行在 **10240** 端口
- 所有业务 API 自动添加 `/api` 前缀

---

## 🤖 量化交易 / Arena 本地开发

### .env 必须配置的变量

```bash
serverEnv = "local"
SERVER_PORT = 10240

# LLM 网关（LiteLLM 代理，支持 Qwen 系列模型）
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE="https://litellm-ali.sit.kucoin.net"
LLM_MODEL_NAME="Qwen3.5-27B"

# Arena Agent 模型配置
QUANT_ARENA_DEEPSEEK_MODEL=Qwen3.5-27B
QUANT_ARENA_DEEPSEEK_FALLBACK_MODEL=Qwen3-32B

# 多账户配置（JSON，account_id 对应 KUCOIN_API_KEY_{ID} 后缀）
QUANT_ARENA_AGENT_CONFIGS='{"technical_signal":{"account_id":"technical_signal","mode":"rule"},"claude_agent":{"account_id":"claude","model":"deepseek-chat"}}'

# KuCoin 交易凭据（按 account_id 后缀区分）
KUCOIN_API_KEY_TECHNICAL_SIGNAL=xxx
KUCOIN_API_SECRET_TECHNICAL_SIGNAL=xxx
KUCOIN_API_PASSPHRASE_TECHNICAL_SIGNAL=xxx
KUCOIN_API_KEY_CLAUDE=xxx
KUCOIN_API_SECRET_CLAUDE=xxx
KUCOIN_API_PASSPHRASE_CLAUDE=xxx

# 风控参数
QUANT_LIVE_MAX_ORDER_USD=10
QUANT_MAX_QUANTITY_USD=10
QUANT_MAX_TOTAL_EXPOSURE=0.5
QUANT_MIN_CONFIDENCE=0.60

# ValueScan 因子库（可选，对接因子数据源）
VS_OPEN_API_KEY=ak_xxx
VS_OPEN_SECRET_KEY=sk_xxx
```

### 本地启动命令

```bash
source /path/to/.venv/bin/activate
serverEnv=local SERVER_PORT=10240 PYTHONPATH=src \
  EUREKA_ENABLED=false QUANT_SCHEDULER_ENABLED=false \
  python -m uvicorn main:app --host 127.0.0.1 --port 10240 --workers 1
```

启动后访问：http://127.0.0.1:10240/live-trading
