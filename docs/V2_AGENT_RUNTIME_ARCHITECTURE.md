# TIANTONG AI V2 Agent Runtime 架构说明

## 1. 架构定位

Agent Runtime 是 V2 的统一执行底座，负责把“AI 员工提出的能力调用”转换成“可校验、可审批、可执行、可审计”的标准执行任务。

它不直接让 AI 员工调用电脑、浏览器、手机或 Shell。所有执行都必须先经过：

1. 能力注册表查询
2. 权限与风险判断
3. 审批判断
4. 执行器选择
5. 审计记录
6. 结果回传

生产默认只允许 Mock Executor。真实执行器必须显式关闭后再按环境开启。

## 2. 模块边界

后端模块划分为：

- `backend/agent_runtime/models.py`：能力、执行、审计数据模型
- `backend/agent_runtime/schemas.py`：请求与响应结构
- `backend/agent_runtime/registry.py`：能力注册与查询
- `backend/agent_runtime/permission.py`：权限、风险、审批判断
- `backend/agent_runtime/executor.py`：执行器接口与 Mock Executor
- `backend/agent_runtime/service.py`：执行编排
- `backend/agent_runtime/audit.py`：审计写入与脱敏
- `backend/agent_runtime/exceptions.py`：领域异常
- `backend/routers/agent_runtime.py`：最小管理 API

## 3. 数据模型

本 Sprint 新增三张表：

- `agent_capabilities`
- `agent_executions`
- `agent_execution_audits`

核心字段覆盖：

- 能力标识、名称、类型、风险等级、启用状态、审批要求、超时、重试、输入/输出 schema
- 执行任务状态、审批状态、执行器类型、trace id、错误信息、耗时
- 审计发起人、执行人、能力、摘要、审批、结果、错误、来源、脱敏信息

## 4. 执行流

标准执行流：

1. AI 员工或 Task Center 发起执行请求
2. Agent Runtime 校验员工、能力、环境与输入
3. 风险判断决定是否需要审批
4. 通过后创建执行记录
5. 调用执行器
6. 写入审计事件
7. 回写执行结果或错误

## 5. 执行器标准

统一执行器接口：

- `validate()`
- `execute()`
- `cancel()`
- `health_check()`
- `get_metadata()`

统一输入：

- 执行上下文
- 员工上下文
- 能力上下文
- 权限上下文
- 输入载荷
- 超时
- trace id

统一输出：

- success
- output
- error code
- error message
- started time
- finished time
- duration
- metadata

## 6. 安全边界

默认安全边界：

- `AGENT_RUNTIME_ENABLED=true`
- `REAL_EXECUTOR_ENABLED=false`
- `COMPUTER_CONTROL_ENABLED=false`
- `MOBILE_CONTROL_ENABLED=false`
- `BROWSER_CONTROL_ENABLED=false`
- `SHELL_EXECUTION_ENABLED=false`

高风险能力默认拒绝。真实执行器必须显式开启，并且要经过权限、审批与审计校验。

审计日志禁止记录：

- 明文密码
- Token
- Cookie
- Secret
- 私钥

## 7. 公开 API

最小 API：

- `GET /api/v2/capabilities`
- `GET /api/v2/capabilities/{capability_id}`
- `POST /api/v2/executions`
- `GET /api/v2/executions`
- `GET /api/v2/executions/{execution_id}`
- `POST /api/v2/executions/{execution_id}/approve`
- `POST /api/v2/executions/{execution_id}/reject`
- `POST /api/v2/executions/{execution_id}/cancel`
- `GET /api/v2/executions/{execution_id}/audit`
- `GET /api/v2/agent-runtime/health`

所有用户可见信息必须使用中文。

## 8. Feature Flag 策略

Agent Runtime 采用显式开关，不依赖默认值自动开启真实执行能力。

策略要求：

- 生产环境默认关闭真实执行
- 真实执行器可按能力单独开关
- 高风险执行必须人工确认
- V1 任务流程不受影响

## 9. 未来接入方式

后续接入 OpenClaw、Browser Use、Desktop Use、Mobile Use、Shell Tool 时，必须实现同一执行器接口，并且通过 Agent Runtime 统一编排。

未来能力必须继续保持：

- 先注册
- 再鉴权
- 再审批
- 再执行
- 最后审计

任何绕过 Agent Runtime 的直连控制都属于禁止路径。
