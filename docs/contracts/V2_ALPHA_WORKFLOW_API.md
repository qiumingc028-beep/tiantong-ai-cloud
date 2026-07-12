# V2 Alpha Workflow API 契约

## 原则

- 只保留 Alpha 主链路的最小 API。
- Alpha Workflow 只能通过 Orchestrator 入口启动。
- Alpha Service 只能作为内部执行服务；缺少 Orchestrator 证明的直接调用必须拒绝。
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
  - 该入口必须由 Orchestrator 先生成计划证明，再调用内部执行服务。
  - 若请求未显式提供 `trace_id`，应回退为 Orchestrator 计划的 `graph_id` 作为稳定幂等键。
  - 相同 `trace_id` 的重复启动必须返回既有运行或明确拒绝，不能创建第二套正式流程。
- `GET /api/v2/alpha-workflows/runs`
- `GET /api/v2/alpha-workflows/runs/{run_id}`
- `GET /api/v2/alpha-workflows/runs/{run_id}/trace`
- `GET /api/v2/alpha-workflows/runs/{run_id}/audit`
- `GET /api/v2/alpha-workflows/runs/{run_id}/report`
- `GET /api/v2/alpha-workflows/runs/{run_id}/stages`
- `POST /api/v2/alpha-workflows/runs/{run_id}/recover`
- `POST /api/v2/alpha-workflows/runs/{run_id}/cancel`（若实现）

### 追踪与审计

- `GET /api/v2/alpha-workflows/runs/{run_id}` 返回：
  - `workflow_context`
  - `plan`
  - `report_summary`
  - `dashboard_summary`
- `events`
- `spans`
- 每条 `event` 必须包含 `event_code`、`stage`、`status`、`trace_id`、`span_id`、`parent_span_id`、`span_kind`、`created_at`
- `spans` 必须包含 `span_id`、`parent_span_id`、`span_name`、`stage`、`status`、`started_at`、`finished_at`

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
- 409：重复启动命中同一幂等键或恢复请求已处理

## 兼容要求

- 老接口仅允许作为 Adapter，不得构成第二套主流程。
- Knowledge、Skills、Research 的旧接口如需保留，必须挂到 Alpha 主链路引用 ID 之下。
- 不允许重复创建独立正式知识副本。
