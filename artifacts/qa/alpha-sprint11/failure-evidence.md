# V2 Alpha Sprint 11.1 失败证据

契约 Commit：`3fe8df6065e3ee028cbde14803a9a0020e6a0ba6`

全量结果：`846 passed, 6 failed, 82 warnings in 150.74s`，共 852 项。

## 阻塞失败

1. `test_duplicate_start_is_idempotent_or_explicitly_rejected`
   - 证据：相同 `trace_id` 第二次启动触发 `UNIQUE constraint failed: alpha_workflow_runs.trace_id`，异常穿透 API。
   - 最小建议：在 `backend/alpha_workflow/service.py:start_alpha_workflow` 创建任何 Task/Run 前按幂等键查询；返回既有 Run，或在 Router 映射为明确 409。
2. `test_trace_has_one_root_and_all_children_attach_to_it`
   - 证据：`GET .../trace` 的 `events` 项缺少契约要求的 `trace_id`。
   - 最小建议：在 `backend/alpha_workflow/service.py:get_trace` 的事件序列化中补回 `trace_id`。
3. `test_audit_timeline_is_ordered_and_append_only`
   - 证据：`alpha_workflow_events` 可通过 ORM 原地 UPDATE，审计时间线内容被覆盖。
   - 最小建议：由①设计 DB 级 append-only 约束/权限与应用层禁止 UPDATE；测试需覆盖数据库直接更新路径。
4. `test_stage_failures_are_recorded_and_recoverable[...write_audit_log...]`
   - 证据：初始 Task 审计写入失败发生在 Run/统一异常边界建立前，RuntimeError 穿透，未形成可恢复 Run。
   - 最小建议：调整启动事务边界，使入口审计失败也能返回结构化失败状态；不得吞掉审计失败。
5. `test_recovery_is_idempotent_and_does_not_duplicate_formal_results`
   - 证据：同一失败 Run 连续恢复两次均返回 200，并重新创建正式结果。
   - 最小建议：恢复前原子检查 `recovery_status`，按安全检查点复用 Knowledge/Skill/Audit 引用，并增加唯一约束或幂等键。
6. `test_migration_graph_is_single_head_and_core_tables_are_not_duplicated`
   - 证据：`knowledge_files`、`knowledge_articles` 同时在 `0005_knowledge_center_tables.py` 与 `0005_tiancang_knowledge_tables.py` 中创建。
   - 最小建议：由①核对历史 merge migration 与实际 V1.0.1 升级路径，提供官方执行结果；③不修改 Migration。

## 未执行项

- V1.0.1 数据库到最新 Head 的正式升级、develop-v2 Head 升级、`alembic check` 和重复升级：依任务边界只能由①执行，等待官方证据。
