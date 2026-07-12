# V2 Alpha Sprint 11.1 失败证据

契约 Commit：`3fe8df6065e3ee028cbde14803a9a0020e6a0ba6`

初始全量结果：`846 passed, 6 failed, 82 warnings in 150.74s`，共 852 项。

补强后全量结果：`846 passed, 17 failed, 82 warnings in 156.24s`，共 863 项。原有 6 项失败全部保留；新增门禁将同一问题拆为独立证据，并增加 0040、入口与审批隔离检查。

最终集成 Commit `b04e872135d6c4fe47824a2b88be78943a9e0531` 后：`859 passed, 4 failed, 82 warnings in 154.13s`，共 863 项。13 项门禁已关闭，剩余 4 项如下：

1. `test_trace_has_one_root_and_all_children_attach_to_it`：Root Event 的 `parent_span_id` 等于自身 Root ID，预期为 null。最小建议：`append_event` 必须区分“未提供 parent”与“显式 None”，Root 不得回退为自指。
2. `test_module_spans_are_native_and_not_synthesized_by_one_terminal_loop`：缺少 `audit`、`feedback` 模块 Span，且模块事件 Span 未与 Context Span 全量关联。最小建议：各模块执行时生成并持久化自己的 Span，不在终态循环合成。
3. `test_installer_reviewer_and_approver_are_separate_roles`：实际仅 2 个不同身份，安装、审核、批准未形成三方分离，也无启用人追踪。最小建议：模型和服务记录独立 actor，并拒绝角色复用。
4. `test_high_risk_skill_creator_cannot_self_approve`：高风险 Skill 创建者调用 `approve_skill` 未被拒绝。最小建议：批准前比较 `skill.created_by` 与审批人，命中时返回 403。

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

## 补强失败

7. Alpha Service 可被直接调用并完成流程，缺少 Orchestrator 来源证明。
8. 模块事件 Span 与 WorkflowContext Span ID 不相交，`audit`、`feedback` 阶段也无模块原生 Span，表明 Span 在终态统一合成。
9. 删除 Run 时未拒绝操作，审计事件缺少明确的防级联删除保障。
10. Alpha 安装记录中安装人、审核人、批准人未实现三方职责分离。
11. 高风险 Skill 创建者可以批准自己创建的 Skill。
12. 重复恢复分别重复创建 Knowledge Asset、Skill Invocation 和 Alpha 审计事件。
13. 恢复创建第二个 Root Trace，而非在原 Root Trace 下创建 recovery child span。
14. 无效输入返回 422（Contract 为 400），匿名读取 Runs 返回 200（Contract 权限错误为 403）。
15. 当前不存在 `0040`，无法验证 `0039 → 0040` 单 Head 与约束链。

## 未执行项

- V1.0.1 数据库到最新 Head 的正式升级、develop-v2 Head 升级、`alembic check` 和重复升级：依任务边界只能由①执行，仍等待①提交官方证据。
