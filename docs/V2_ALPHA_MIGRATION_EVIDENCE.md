# V2 Alpha Sprint 11.1 Migration 正式证据

## 证据结论

本证据验证冻结代码 `8d9b5f2890545f1f08d05b9b1618f71ff82d6621`。所有正式迁移操作均在两套相互独立、全新创建的 PostgreSQL 16 数据库中执行；未使用 SQLite，未使用 Drift 跳过开关，未连接生产数据库。

最终 Revision 为 `0042_v2_alpha_workflow_unique_constraints`，两条路径均满足：单一 Head、`alembic current` 正确、`alembic check` 无 Drift、重复 `upgrade head` 为安全 no-op、`0042→0041→0042` 成功。

## Path A：V1.0.1 到冻结代码

- 数据库代号：`alpha_authentic_v2_a`
- 起始 Commit：`483ebf560e1a4cfadecee4912a3ff6bca99516f6`
- 起始 Revision：`0027_v1_schema_alignment`
- 目标 Commit：`8d9b5f2890545f1f08d05b9b1618f71ff82d6621`
- 最终 Revision：`0042_v2_alpha_workflow_unique_constraints`
- 结果：通过

V1.0.1 代码先在空数据库完成 `upgrade head`，真实 `current` 输出为 `0027_v1_schema_alignment (head)`；随后使用冻结代码在同一数据库继续升级至 0042。完整命令与原始输出见 `artifacts/alpha-migration-evidence/path_a_current.log`。

## Path B：冻结可运行 0041 基线到冻结代码

- 数据库代号：`alpha_authentic_v2_b`
- 起始 Commit：`85586868bad3dd5d0fecba5f840383feccdc1c78`
- 起始 Revision：`0041_v2_alpha_migration_history_repair`
- 目标 Commit：`8d9b5f2890545f1f08d05b9b1618f71ff82d6621`
- 最终 Revision：`0042_v2_alpha_workflow_unique_constraints`
- 结果：通过

冻结可运行代码先在另一空数据库完成 `upgrade head`，真实 `current` 输出为 `0041_v2_alpha_migration_history_repair (head)`；随后使用冻结代码升级至 0042。完整命令与原始输出见 `artifacts/alpha-migration-evidence/path_b_current.log`。

KNOWN_BROKEN_HISTORICAL_BASELINE=2ca1a2579569324ce3ca82f68332fb7f96be004d

该 Commit 只记录为已知不可运行的历史基线，不作为 Path B 或任何通过路径。

## PostgreSQL Catalog 实库结果

两条路径的最终数据库均直接查询 PostgreSQL Catalog，结果一致：

- `uq_alpha_workflow_runs_trace_id` 存在。
- 五项 Required 唯一约束存在：
  - `uq_alpha_workflow_runs_workflow_id`
  - `uq_alpha_workflow_runs_root_span_id`
  - `uq_alpha_workflow_runs_orchestrator_run_id`
  - `uq_alpha_workflow_runs_research_report_id`
  - `uq_alpha_workflow_runs_skill_invocation_id`
- `knowledge_asset_id` 只有普通非唯一索引 `ix_alpha_workflow_runs_knowledge_asset_id`，不存在同名全局唯一约束或唯一索引。
- 两个 Run 写入相同 `knowledge_asset_id` 成功，回退重升后仍保留两行。
- 五项 nullable 唯一字段同时为 NULL 的两行写入成功。
- Append-only 触发器 `alpha_workflow_events_no_update` 与 `alpha_workflow_events_no_delete` 存在。
- `0042→0041→0042` 成功，回退与重升没有恢复已废弃的 Knowledge Asset 全局唯一性。

两份 RAW OUTPUT 逐条记录实际执行的 `python -m alembic ...` 命令及
stdout/stderr；每次进入基线或冻结代码 Worktree 均记录 `pwd`、Git HEAD 和
Python 版本。Catalog 验证通过真实 `docker exec ... psql -f` 执行，命令后保存
完整 SQL 文件正文与查询输出，不使用摘要文字冒充 Shell 命令。

## 0037 预发布兼容调整披露

文件：`alembic/versions/0037_v2_execution_observability_security_ops.py`

0037_baseline_commit_or_hash=9e2086a6c82b5559e17b3f2ecec52740d84d6e1a
0037_modified_hash=3a4359197ec3e632adcfb73b1078b1104fdab248b16b537a6ec6f7f034f6eb97
0037_change=Boolean server_default 从整数 1 调整为 PostgreSQL true 表达
0037_reason=PostgreSQL 不接受布尔列 DEFAULT 1，预发布链需使用原生 true 表达保证新库可执行并与模型一致
0037_production_deployed=否
0037_exception_decision=V2预发布例外，仅接受已审查的 PostgreSQL 兼容版本并自 Sprint 11.1 收口后冻结
0037_approved_role=①实施、③验收、④审查
0037_post_sprint_freeze_rule=Sprint 11.1关闭后冻结旧Migration，后续变化只能新增 forward-only Migration

`0037_baseline_commit_or_hash` 是冻结可运行版本在 Git 中现场计算得到的 Blob Hash；`0037_modified_hash` 是同一文件在冻结代码上的现场 SHA256。当前文件与冻结可运行 Commit `85586868bad3dd5d0fecba5f840383feccdc1c78` 字节一致。

## 完整性与隐私

- V1 Migration `0001—0027` 由 Gate 与 `v1.0.1` 逐文件字节比对。
- 正式日志不包含数据库密码、Token、完整连接串或生产数据。
- `checksums.sha256` 仅覆盖规定的六个文件，使用仓库相对路径且不校验自身。
- 证据文件只记录只读结果；不能触发业务执行。

## 证据索引

- `artifacts/alpha-migration-evidence/path_a_current.log`
- `artifacts/alpha-migration-evidence/path_b_current.log`
- `artifacts/alpha-migration-evidence/alembic-evidence.txt`
- `artifacts/alpha-migration-evidence/validation-manifest.json`
- `artifacts/alpha-migration-evidence/checksums.sha256`
- `docs/V2_MIGRATION_FREEZE_POLICY.md`
