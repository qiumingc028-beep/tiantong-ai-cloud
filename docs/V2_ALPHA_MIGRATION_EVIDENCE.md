# V2 Alpha Migration Evidence

## 目的

本文记录 0039 与 0040 的正式迁移证据，覆盖：

- 从 0039 升级到最新 Head
- `alembic heads`
- `alembic current`
- `alembic check`
- 重复执行 `alembic upgrade head`
- 0040 受限回退能力
- 历史 Migration 未被修改

## 证据环境

- 数据库：临时 SQLite 文件 `/tmp/alpha-migration-evidence.db`
- 运行方式：`PYTHONPATH=/private/tmp/tiantong-v2-sprint10-observability`
- 迁移检查额外开关：`ALEMBIC_SKIP_SQLITE_DRIFT=1`

## 证据摘要

### 1) 迁移头检查

- `alembic heads`
- 结果：`0040_v2_alpha_workflow_integrity_constraints (head)`

### 2) 从 0039 升级到 Head

- `alembic upgrade 0039_v2_alpha_workflow_unified_contract`
- `alembic current`
- 结果：`0039_v2_alpha_workflow_unified_contract`

- `alembic upgrade head`
- `alembic current`
- 结果：`0040_v2_alpha_workflow_integrity_constraints (head)`

### 3) 重复执行 head 升级

- 第二次执行 `alembic upgrade head`
- 结果：安全通过，无额外变更

### 4) Drift 检查

- `ALEMBIC_SKIP_SQLITE_DRIFT=1 alembic check`
- 结果：`No new upgrade operations detected.`

### 5) 受限回退

`0040_v2_alpha_workflow_integrity_constraints` 的 downgrade 仅包含：

- 删除 `alpha_workflow_events` 的 append-only triggers
- 删除 0040 新增的 unique indexes

不删除历史数据，不回滚 0039 之前的表结构。

### 6) 重新升级

- `alembic downgrade 0039_v2_alpha_workflow_unified_contract`
- `alembic upgrade head`
- 结果：再次回到 `0040_v2_alpha_workflow_integrity_constraints (head)`

## 0040 关键约束

已确认存在以下约束/保护：

- `uq_alpha_workflow_runs_root_span_id`
- `uq_alpha_workflow_runs_workflow_id`
- `uq_alpha_workflow_runs_orchestrator_run_id`
- `uq_alpha_workflow_runs_research_report_id`
- `uq_alpha_workflow_runs_knowledge_asset_id`
- `uq_alpha_workflow_runs_skill_invocation_id`
- `alpha_workflow_events` append-only triggers

## 历史 Migration 完整性

- 未修改 `0039_v2_alpha_workflow_unified_contract`
- 未修改更早历史 Migration
- 本次仅新增 `0040_v2_alpha_workflow_integrity_constraints`

