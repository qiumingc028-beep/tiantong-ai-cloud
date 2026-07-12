# V2 Alpha Workflow Context 契约

## 目标

Alpha Workflow 只允许通过一个统一上下文在 Orchestrator、Research、Knowledge、Skills、Agent Runtime、Verification、Audit、Dashboard 之间传递状态。

## 唯一上下文结构

`WorkflowContext` 是 Alpha 全链路唯一上下文对象，字段固定如下：

- `workflow_id`
- `tenant_id`
- `user_id`
- `task_id`
- `orchestrator_run_id`
- `research_execution_id`
- `research_report_id`
- `knowledge_asset_id`
- `knowledge_version_id`
- `skill_id`
- `skill_version_id`
- `skill_invocation_id`
- `agent_execution_id`
- `verification_id`
- `trace_id`
- `root_span_id`
- `approval_ids`
- `risk_score`
- `quality_score`
- `current_stage`
- `status`
- `created_at`
- `updated_at`

## 约束

1. 全链路只允许这一份上下文，不得创建同义不同结构的上下文。
2. 上下文只保存引用 ID 与运行态摘要，不保存 Secret、Cookie、Token、密码。
3. 上下文更新必须留下审计记录。
4. 上下文中的 `trace_id` 是 Root Trace ID，模块级 Span 必须挂在其下。
5. `status` 只能使用以下枚举：
   - `草稿`
   - `待校验`
   - `运行中`
   - `已暂停`
   - `等待恢复`
   - `已完成`
   - `已失败`
   - `已取消`
   - `已终止`

## Stage 约定

`current_stage` 只能取以下值：

- `orchestrator`
- `research`
- `knowledge`
- `skills`
- `execution`
- `verification`
- `audit`
- `feedback`
- `dashboard`

## Trace 约定

- `root_span_id` 表示 Alpha Workflow 根节点。
- 每个模块产生自己的 child span。
- child span 必须携带 `workflow_id`、`task_id`、`trace_id`、`current_stage`。
- 审计时间线必须可以从 Root Trace 反查所有 child span。

## 失败与恢复

- 失败状态必须保留失败原因。
- 恢复必须创建新的 child span。
- 恢复不得重复生成正式知识资产。
- 恢复不得重复调用同一技能版本，除非显式标记为“重试”。
