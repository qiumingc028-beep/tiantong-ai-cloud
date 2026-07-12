# V2 Alpha Sprint 11.1 失败证据

## PR #17 fa9067 新证据审计

只读审计 PR #17 Head：`fa9067fac27ac44264bf4c4df706ccb23366f987`。

当前新增阻塞证据：

1. PR描述与旧证据矛盾：描述称最终Head为 `0041_v2_alpha_migration_history_repair`，但远程 `artifacts/alpha-migration-evidence/alembic-evidence.txt` 内容仍以0040为Head。
2. PR #17远程Changed Files中不存在 `path_a_current.log`。
3. PR #17远程Changed Files中不存在 `path_b_current.log`。
4. PR #17远程Changed Files中不存在 `checksums.sha256`，无法复算证据Hash。
5. PR #17远程Changed Files中不存在独立Migration Freeze Policy文件。
6. `alembic/versions/0037_v2_execution_observability_security_ops.py` 被直接修改：3处Boolean server default从 `1` 改为 `true`；必须由冻结政策确认0037尚未冻结，并如实披露。
7. 0001—0027尚无逐文件Hash清单；0005是否与V1.0.1完全一致未获远程证据证明。
8. PR描述声称两套独立PostgreSQL升级路径通过，但缺少两套数据库的原始 `current/heads/check/upgrade/downgrade/re-upgrade/schema` 日志。
9. `fa9067` GitHub combined status的 `statuses` 为空，没有CI Run/Status证据。

结论：等待 `MIGRATION_EVIDENCE_FINAL_COMMIT`。在证据文件真实存在、Checksums可复算、历史Hash一致、双PostgreSQL路径可核验且fa9067后完整回归零失败前，PR #19保持Draft/BLOCK。

契约 Commit：`3fe8df6065e3ee028cbde14803a9a0020e6a0ba6`

初始全量结果：`846 passed, 6 failed, 82 warnings in 150.74s`，共 852 项。

补强后全量结果：`846 passed, 17 failed, 82 warnings in 156.24s`，共 863 项。原有 6 项失败全部保留；新增门禁将同一问题拆为独立证据，并增加 0040、入口与审批隔离检查。

最终集成 Commit `b04e872135d6c4fe47824a2b88be78943a9e0531` 后：`859 passed, 4 failed, 82 warnings in 154.13s`，共 863 项。13 项门禁已关闭，剩余 4 项如下：

1. `test_trace_has_one_root_and_all_children_attach_to_it`：Root Event 的 `parent_span_id` 等于自身 Root ID，预期为 null。最小建议：`append_event` 必须区分“未提供 parent”与“显式 None”，Root 不得回退为自指。
2. `test_module_spans_are_native_and_not_synthesized_by_one_terminal_loop`：缺少 `audit`、`feedback` 模块 Span，且模块事件 Span 未与 Context Span 全量关联。最小建议：各模块执行时生成并持久化自己的 Span，不在终态循环合成。
3. `test_installer_reviewer_and_approver_are_separate_roles`：实际仅 2 个不同身份，安装、审核、批准未形成三方分离，也无启用人追踪。最小建议：模型和服务记录独立 actor，并拒绝角色复用。
4. `test_high_risk_skill_creator_cannot_self_approve`：高风险 Skill 创建者调用 `approve_skill` 未被拒绝。最小建议：批准前比较 `skill.created_by` 与审批人，命中时返回 403。

## 最终修复回归

最终 Commit `eef1ed66638011503c7377d52104258b72ee80d0` 同步后：

- Alpha/Trace/Audit/Approval/Recovery 专项：`31 passed`。
- Backend 全量：`863 passed, 0 failed, 82 warnings in 158.92s`。
- 上述全部代码失败均已关闭，没有 skip、xfail、删除或降低断言。

## 尚未关闭的非测试阻塞

Migration 正式证据未通过真实性/完整性验收：

1. `docs/V2_ALPHA_MIGRATION_EVIDENCE.md` 声明“未修改更早历史 Migration”，但 `git diff 3fe8df6..eef1ed6 -- alembic/versions` 明确显示 `M alembic/versions/0005_knowledge_center_tables.py`。
2. Drift 证据使用 `ALEMBIC_SKIP_SQLITE_DRIFT=1 alembic check`，不能证明未绕过 Drift。
3. 证据只描述临时 SQLite 从0039升级，没有分别给出V1.0.1基线和develop-v2前一Head的可核验命令、日志、数据库结构快照与校验和。

因此代码测试为零失败，但发布建议仍为 BLOCK，等待①补交自洽且可复核的Migration正式证据。

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
## cc8c779 Migration Evidence Gate

评估基线：`cc8c77914dbc79a6821d8781f626b77a003b4f7f`。自动门禁：`2 passed, 7 failed`。

已关闭：V1 0001—0027 全部与 `v1.0.1` 字节一致；0005、0025、0026、0027 分别复核通过。旧的0005不一致结论已撤销。

仍阻塞：

1. `path_a_current.log` 不存在。
2. `path_b_current.log` 不存在。
3. `docs/V2_MIGRATION_FREEZE_POLICY.md` 不存在。
4. `checksums.sha256` 使用 `/private/tmp/tiantong-v2-sprint10-observability/...` 绝对路径，并引用当前分支不存在的 Path A/B 文件，不能按仓库相对路径完整复算。
5. 0037缺少冻结政策中的明确披露。
6. 0041只有摘要/文档声明，缺少两条原始路径日志支撑全链路一致性。
7. 缺失文件导致 Secret、SQLite正式证据及 Drift skip 的全量扫描无法完成。

等待①提交 `MIGRATION_EVIDENCE_FINAL_COMMIT`。Gate通过前不进入完整863项回归，PR #19保持Draft/BLOCK。
## Gate Implementation Fixes

Gate实现整改完成，但当前证据包仍为BLOCK：

- Checksum绝对路径直接失败；basename回退已删除；`..`与ROOT外路径被拒绝。
- Path A/B必须为结构化元数据加RAW OUTPUT，不再以关键词摘要代替数据库执行证据。
- 引入 `validated_code_commit` / Evidence Bundle分离模型；验证Git Commit、祖先关系和evidence-only区间，出现Backend/Alembic变化必须重测。
- 0037必须在政策和证据文档中完成八项一致披露。
- 当前旧证据运行结果为 `2 passed, 9 failed`：Path A/B及Freeze Policy仍缺失，旧Checksum绝对路径被严格拒绝。
- 前端Gate复验 `10 passed, 0 failed`。

等待 `MIGRATION_EVIDENCE_FINAL_COMMIT`，不进入全量回归，不修改业务代码。
## 85586868 Final Gate 预检阻塞

- Migration Gate：`5 passed, 8 failed`。
- Path A格式：缺少规定的结构字段和 `--- RAW OUTPUT ---`；起点Commit `483ebf5` 不等于 `v1.0.1^{commit}` 的 `60335cd`，且所谓V1阶段结束时已显示0041。
- Path B格式：缺少规定的结构字段和RAW OUTPUT；起点Commit错误使用 `cc8c779`，真实develop-v2 merge-base为 `2ca1a2579569324ce3ca82f68332fb7f96be004d`。
- 0037：Freeze Policy缺少完整文件路径，双文档均未提供完整一致的结构化八项披露。
- Checksums：Freeze Policy Hash复算失败；未覆盖 `validation-manifest.json`；并包含精确Required Files集合外条目。
- Manifest缺少：`evidence_format_version`、`validated_code_commit`、`final_revision`、`checksum_algorithm`、`required_files`、`path_a`、`path_b`。
- 未执行Backend全量回归。等待 `MIGRATION_EVIDENCE_FINAL_COMMIT`。
