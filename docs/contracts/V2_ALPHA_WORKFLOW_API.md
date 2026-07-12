# V2 Alpha Workflow API 契约

## 原则

- 只保留 Alpha 主链路的最小 API。
- Alpha Workflow 只能通过 Orchestrator 入口启动。
- 所有返回值都必须围绕统一 `WorkflowContext`。
- 所有用户可见错误信息使用中文。
- 默认功能关闭，不影响生产。

## API 列表

### 场景

- `GET /api/v2/alpha-workflows/scenarios`
- `GET /api/v2/alpha-workflows/scenarios/{scenario_code}`
- `POST /api/v2/alpha-workflows/scenarios`

### 工作流

- `POST /api/v2/alpha-workflows/demo`：启动 Alpha Workflow
- `GET /api/v2/alpha-workflows/runs`
- `GET /api/v2/alpha-workflows/runs/{run_id}`
- `POST /api/v2/alpha-workflows/runs/{run_id}/recover`
- `POST /api/v2/alpha-workflows/runs/{run_id}/cancel`（若实现）

### 追踪与审计

- `GET /api/v2/alpha-workflows/runs/{run_id}` 返回：
  - `workflow_context`
  - `plan`
  - `report_summary`
  - `dashboard_summary`
  - `events`
- 每条 `event` 必须包含 `event_code`、`stage`、`status`、`trace_id`、`created_at`

### Dashboard

- `GET /api/v2/alpha-workflows/dashboard`
- `GET /api/v2/alpha-workflows/health`

## 响应字段约定

### Run

- `run_id`
- `scenario_id`
- `task_id`
- `research_execution_id`
- `research_report_id`
- `knowledge_asset_id`
- `knowledge_version_id`
- `skill_id`
- `skill_version_id`
- `skill_invocation_id`
- `agent_execution_id`
- `verification_id`
- `status`
- `quality_score`
- `quality_grade`
- `risk_score`
- `risk_level`
- `failure_reason`
- `recovery_status`
- `recovered_from_run_id`
- `workflow_context`
- `plan`
- `report_summary`
- `dashboard_summary`
- `trace_id`
- `started_at`
- `finished_at`

### 错误

- 400：输入无效、功能未启用、前置依赖缺失
- 403：权限不足或 Feature Flag 关闭
- 404：Run / Scenario 不存在

## 兼容要求

- 老接口仅允许作为 Adapter，不得构成第二套主流程。
- Knowledge、Skills、Research 的旧接口如需保留，必须挂到 Alpha 主链路引用 ID 之下。
- 不允许重复创建独立正式知识副本。
