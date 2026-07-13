# V2 Alpha Migration Evidence

## 目标

本文件记录 V2 Alpha Sprint 11.1 的正式 migration 证据收口，覆盖：

- 两条彼此独立的 PostgreSQL 升级路径
- `alembic heads`
- `alembic current`
- `alembic history`
- `alembic check`
- 重复执行 `alembic upgrade head`
- 受限 downgrade / re-upgrade
- PostgreSQL 实库约束验证
- 历史 migration 完整性检查

## 证据环境

- 数据库引擎：PostgreSQL 16
- 运行方式：独立 PostgreSQL 数据库，不使用 SQLite
- 证据数据库：
  - `alpha_evidence_a`
  - `alpha_evidence_b`
- 证据日志：
  - `artifacts/alpha-migration-evidence/path_a_current.log`
  - `artifacts/alpha-migration-evidence/path_b_current.log`

## Git 与历史完整性结论

本次核验中重点审计了：

- `alembic/versions/0005_knowledge_center_tables.py`
- `alembic/versions/0039_v2_alpha_workflow_unified_contract.py`
- `alembic/versions/0040_v2_alpha_workflow_integrity_constraints.py`
- `alembic/versions/0037_v2_execution_observability_security_ops.py`

最终处理结果：

- `0005_knowledge_center_tables.py` 已恢复为 `v1.0.1` 原始内容，不再保留分支内的降级版改写。
- `0039`、`0040` 均保持为新增增量 migration。
- `0037_v2_execution_observability_security_ops.py` 包含一次已明确披露的 PostgreSQL 兼容性调整：将布尔默认值从整数 `1` 统一修正为 PostgreSQL `true` 表达，以保证实库可执行性与 `alembic check` 一致性。
- `0041_v2_alpha_migration_history_repair.py` 为新增修复 migration，用于修复 Alpha 运行时的 PostgreSQL 约束一致性。
- `0042_v2_alpha_workflow_unique_constraints.py` 已承载知识资产身份清理：移除 `knowledge_asset_id` 的全局唯一性，仅保留普通索引，并保留五个 Required 唯一约束。
- V1 正式链 `0001`—`0027` 经过逐文件比对，已确认与 `v1.0.1` 完全一致。
- V2 预发布链 `0028`—`0042` 仍可继续在隔离环境中用于证据验证，但在 Sprint 11.1 收口后按冻结策略停止进一步修改旧文件。

## 路径 A：V1.0.1 正式 Tag -> 最新 Head

### 起点

- 起始基线：`V1.0.1` 正式 Tag
- 起始 revision：`0027_v1_schema_alignment`

### 过程

1. 在独立 PostgreSQL 数据库 `alpha_evidence_a` 上执行 v1.0.1 基线升级。
2. 切换到当前 Alpha 分支代码。
3. 继续执行 `alembic upgrade head`。
4. 再次执行 `alembic upgrade head` 验证幂等。
5. 执行 `alembic downgrade 0040_v2_alpha_workflow_integrity_constraints`。
6. 再次升级回 head。

### 结果

- `alembic heads`：单一 head，`0042_v2_alpha_workflow_unique_constraints`
- `alembic current`：最终 revision 为 `0042_v2_alpha_workflow_unique_constraints`
- `alembic history`：链路完整
- `alembic upgrade head`：成功
- 第二次 `alembic upgrade head`：安全 no-op
- `alembic check`：`No new upgrade operations detected.`
- `downgrade 0040 -> upgrade head`：成功，数据未丢失

## 路径 B：PR #17 merge-base -> 最新 Head

### 起点

- 起始基线：PR #17 与 `develop-v2` 的 merge-base 对应的旧基线
- 起始 revision：`0037_v2_execution_observability_security_ops`

### 过程

1. 在另一套独立 PostgreSQL 数据库 `alpha_evidence_b` 上执行旧基线升级。
2. 切换到当前 Alpha 分支代码。
3. 继续执行 `alembic upgrade head`。
4. 再次执行 `alembic upgrade head` 验证幂等。
5. 执行 `alembic downgrade 0040_v2_alpha_workflow_integrity_constraints`。
6. 再次升级回 head。

### 结果

- `alembic heads`：单一 head，`0042_v2_alpha_workflow_unique_constraints`
- `alembic current`：最终 revision 为 `0042_v2_alpha_workflow_unique_constraints`
- `alembic history`：链路完整
- `alembic upgrade head`：成功
- 第二次 `alembic upgrade head`：安全 no-op
- `alembic check`：`No new upgrade operations detected.`
- `downgrade 0040 -> upgrade head`：成功，数据未丢失

## 实库约束验证

以下约束与保护已在升级后的 PostgreSQL Schema 中直接读取验证：

- 幂等键唯一约束：`uq_alpha_workflow_runs_workflow_id`
- Root Trace 唯一约束：`uq_alpha_workflow_runs_root_span_id`
- 其它 Alpha 唯一约束：
  - `uq_alpha_workflow_runs_orchestrator_run_id`
  - `uq_alpha_workflow_runs_research_report_id`
  - `uq_alpha_workflow_runs_skill_invocation_id`
- `knowledge_asset_id` 保留普通索引，可跨 Run 复用，不作为全局唯一身份
- `trace_id` 保持独立唯一约束：`uq_alpha_workflow_runs_trace_id`
- Append-only 保护：
  - `alpha_workflow_events_no_update`
  - `alpha_workflow_events_no_delete`
- 关键外键一致性：
  - `alpha_workflow_events_run_id_fkey` = `ON DELETE RESTRICT`
  - `alpha_workflow_runs_user_id_fkey` = `ON DELETE SET NULL`

## 数据完整性结果

验证结果：

- 单一 head
- 当前 revision 正确
- 无 drift
- 重复 upgrade 安全
- downgrade / re-upgrade 安全
- 关键约束在 PostgreSQL 实库中真实存在
- 不删除 V1 数据
- 不破坏现有外键和索引

## 证据日志索引

- `artifacts/alpha-migration-evidence/path_a_current.log`
- `artifacts/alpha-migration-evidence/path_b_current.log`

## 结论

V2 Alpha 的 migration 链路已通过两条独立 PostgreSQL 路径验证，最终 head 为：

- `0042_v2_alpha_workflow_unique_constraints`

证据表明：

- 迁移链可从 `V1.0.1` 正式 Tag 正常升级
- 迁移链可从 PR #17 merge-base 正常升级
- `alembic check` 在 PostgreSQL 下通过
- 重复 upgrade 安全
- 受限 downgrade / re-upgrade 安全
- 历史 migration 完整性已恢复到可接受状态
