# TIANTONG AI V2 Sprint 1 实现报告

## 1. Sprint 目标

本 Sprint 完成 V2 最核心的执行底座：

- Agent Runtime
- 统一能力中心
- 能力注册表
- 执行任务模型
- 权限与审批判断
- 执行日志与审计
- 执行器适配器标准
- 安全的模拟执行器
- 最小管理 API
- 最小能力中心页面

本 Sprint 不接入真实 OpenClaw，不控制真实电脑、手机或生产浏览器。

## 2. 实现内容

后端新增：

- `backend/agent_runtime/`
- `backend/routers/agent_runtime.py`
- `alembic/versions/0028_v2_agent_runtime_foundation.py`

前端新增：

- `frontend/agent-runtime.html`
- `frontend/capability-center.html`
- `frontend/execution-records.html`

测试新增：

- `tests/test_agent_runtime.py`
- `tests/test_agent_runtime_pages.py`

## 3. 关键设计

### Agent Runtime

负责接收执行请求、校验员工和能力、判断权限和风险、决定审批、调用执行器、保存结果与审计。

### 能力注册表

统一管理能力元数据，包含能力类型、执行器类型、风险等级、启用状态、审批要求、超时、重试与 schema。

### 执行任务模型

统一记录：

- execution_id
- task_id
- employee_id
- capability_id
- status
- risk_level
- approval_status
- executor_type
- input_payload
- output_payload
- error_code
- error_message
- retry_count
- started_at
- finished_at
- duration_ms
- trace_id

### 审计模型

记录执行发起、审批、风险、结果、错误、重试、执行器、trace id、来源信息，并对敏感数据进行脱敏。

## 4. Feature Flag

运行时默认配置：

- `AGENT_RUNTIME_ENABLED=true`
- `REAL_EXECUTOR_ENABLED=false`
- `COMPUTER_CONTROL_ENABLED=false`
- `MOBILE_CONTROL_ENABLED=false`
- `BROWSER_CONTROL_ENABLED=false`
- `SHELL_EXECUTION_ENABLED=false`

生产默认不打开真实执行器。

## 5. 迁移结果

新增迁移：

- `0028_v2_agent_runtime_foundation`

迁移验证：

- `alembic upgrade head`：通过
- `alembic check`：通过

验证数据库使用临时 PostgreSQL 副本完成，不影响 V1 生产数据库。

## 6. 测试结果

本 Sprint 完成验证：

- Backend Tests：779 passed，82 warnings
- Frontend Validation：通过（前端页面验证已纳入 pytest）
- Python Import：通过
- Config Validation：通过
- Migration Upgrade：通过
- Alembic Check：通过
- Static Security：通过
- V1 Regression：通过
- Agent Runtime 专项测试：通过
- API Smoke Test：通过
- Feature Flag Test：通过

## 7. 安全结果

已确认：

- 真实执行器默认关闭
- 电脑控制关闭
- 手机控制关闭
- 浏览器控制关闭
- Shell 执行关闭
- 审计日志不写入明文 Secret
- 敏感输入会被脱敏
- 不存在绕过审批的默认路径

## 8. 未接入内容

本 Sprint 未接入：

- OpenClaw
- Browser Use
- Desktop Use
- Mobile Use
- 真实 Shell
- 真实 Docker 控制

这些能力保留为后续扩展点。

## 9. 后续建议

下一步应继续完善：

- 更完整的能力分层
- 更细的审批流程
- 更丰富的 executor adapter
- 更严格的审计回放
- Browser/Desktop/Mobile 适配层

在此之前，应继续保持真实执行能力默认关闭。
