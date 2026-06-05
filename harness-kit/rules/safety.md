# 安全规则

## Sandbox

- 默认 `workspace-write`，禁止随意 `--dangerously-bypass-approvals`
- 网络访问仅用于文档指定的 MCP（GitHub / JIRA）

## 敏感文件

不得读取或提交：

- `.env` / `*.pem` / `credentials.json`
- 含 API Key 的配置

## 审批

以下操作必须等人确认后再执行：

- `git push`
- 安装全局依赖
- 修改 CI / GitHub Actions
