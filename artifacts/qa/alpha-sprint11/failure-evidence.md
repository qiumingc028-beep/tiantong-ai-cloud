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
## 3406 / 0042 PostgreSQL回归失败矩阵

- PASS：merge-base 0037 Boolean错误在真实PostgreSQL复现；3406 fresh upgrade到0042成功。
- FAIL：0037相对85586868冻结Blob再次被修改（`sa.text("true")`改为`sa.true()`及尾部变化）。
- PASS：五项Required约束名称、列、重复INSERT阻断和幂等重试均通过。
- PASS：0039 downgrade / 0042 re-upgrade后五项约束仍正确。
- FAIL：0042包含 `uq_alpha_workflow_runs_knowledge_asset_id`，Knowledge Asset不能跨Run复用。
- FAIL：ORM Model同样声明Knowledge Asset唯一约束。
- FAIL：重复启动实际返回200，Contract要求409。
- CLOSED：0005两个节点位于同一路径且都有条件创建，但真实PostgreSQL fresh upgrade未发生重复表失败；静态重复扫描为误报。

专项总计：`1 passed, 4 failed`。Backend全量未执行，PR #19保持Draft/BLOCK。
## 0042架构门禁强化执行

隔离PostgreSQL结果：`3 passed, 11 failed`。

PASS：merge-base Boolean缺陷复现与fresh upgrade；相同幂等键返回既有Run；0005 Revision DAG、has_table保护及fresh upgrade共同证明其为冻结历史命名债务。

FAIL：0037字节冻结；0042精确五项集合；Model一致性；Knowledge遗留唯一性清理与跨Run复用；0042 downgrade不恢复Knowledge唯一性/不冲突；五种Required冲突的中文409及IntegrityError脱敏。

## Research 持久化与故障恢复门禁

- 真实PostgreSQL ID门禁：`persist_research_result` 插入 `ResearchClaim.claim_id=<36位execution_id>-c1`，PostgreSQL返回 `StringDataRightTruncation: value too long for type character varying(36)`。Query/Claim等派生ID必须使用稳定、完整、可复算的正式ID格式，禁止用字符串截断掩盖问题。
- Claim插入失败：残留 `(Query, Source, Claim, Evidence)=(3, 4, 0, 0)`，并产生ResearchExecution虚假报告记录；向用户暴露 `database persistence failure`。
- Evidence插入失败：残留 `(3, 4, 1, 0)`，并产生ResearchExecution虚假报告记录；向用户暴露 `database persistence failure`。
- Research commit失败：残留 `(3, 4, 1, 4)`，并产生ResearchExecution虚假报告记录；向用户暴露 `database research commit failure`。
- 已通过的子行为：三类故障均将Run标记为失败/待恢复；同trace重放返回200和相同 `run_id`，且不增加Run/Event。
- 最小修复建议：Research正式记录必须位于可回滚原子事务内；故障后先rollback，再用独立安全事务记录Run失败/恢复状态；所有派生ID使用稳定UUID/正式规范生成并支持upsert或既有记录复用；API只返回中文领域错误，不泄漏DB/ORM异常文本。

## 95465582 定向回归剩余失败

- `test_final_head_unique_constraints_reject_duplicates_and_keep_idempotency_after_reupgrade`：五项Constraint、重复插入、ON CONFLICT幂等和多NULL均已通过，但继续downgrade到0039返回非零；0042→0041→0042单独场景通过。
- `test_research_persistence_uses_stable_uuid_ids_and_real_foreign_keys`：ID超长问题已关闭，实际ID为标准UUID；当前失败变为`research_evidence_source_id_fkey`，Evidence引用的输入Source ID未对应实际生成的ResearchSource ID。
- Claim插入失败：正式行残留 `(Query, Source, Claim, Evidence)=(3, 4, 0, 0)`，ResearchExecution虚假报告残留，AgentExecution仍为`completed`，英文DB错误泄漏。
- Evidence插入失败：正式行残留 `(3, 4, 1, 0)`，ResearchExecution虚假报告残留，AgentExecution仍为`completed`，英文DB错误泄漏。
- Research commit失败：Run=`运行中`、recovery_status=null、Task=`running`、AgentExecution=`completed`；补偿事务未完成。
- 已关闭：同trace顺序及4路并发重放均返回200和同一run_id；五项真实跨Run约束冲突均映射中文409且未泄漏IntegrityError；0005真实执行链成功。

## f50a031 Research正式门禁失败矩阵

- Source→Query：显式commit、关闭Session并重开后，持久化Source的`query_id`为NULL；Evidence→内部Source/Claim外键已通过。
- 重复persist：正式Query/Source/Claim/Evidence数量与内部UUID不增长，跨Execution ID隔离通过；但同一Task的`[V2 Research]` summary被追加2次。
- DataError：真实PostgreSQL `varchar(36)`超长错误已产生，但补偿路径在rollback前读取过期`run.run_id`，最终向TestClient穿透`PendingRollbackError`。
- 23503 FK：Run=`已失败`、Task=`rejected`、AgentExecution=`failed`、正式Research数据回滚、同trace重放幂等均通过；失败审计异常为Task写入2条、AgentExecution写入0条。
- 23505唯一冲突：补偿和回滚通过；同样存在Task失败审计重复及AgentExecution失败审计缺失。
- 五项409测试已改为Service真实创建Run并在Session flush触发PostgreSQL约束，不再在Router层抛裸IntegrityError；五项全部返回中文409。
- Migration边界：0042→0041→0042通过；0039路径按裁决标记`UNSUPPORTED_SEMANTIC_DOWNGRADE`，不再列为代码失败。

## d31565a6 PostgreSQL正式门禁失败矩阵

当前代码评估Commit：`d31565a6c18f20384e6140305ee2561a469aef11`；测试分支同步Merge：`0a3f222408c8efdbeee561596070c0007fdc03d7`。真实隔离PostgreSQL 16.14结果：`18 passed, 5 failed`。

1. `test_malicious_upstream_duplicate_source_id_is_mapped_to_internal_uuid`
   - 预期：所有上游Source标识只用于映射，数据库保存内部36位标准UUID，`duplicate_of_source_id`引用真实持久化Source。
   - 实际：第二条Source把160字符恶意上游ID原样写入`duplicate_of_source_id varchar(36)`，PostgreSQL抛出`StringDataRightTruncation`。
   - 最小建议：建立upstream Source ID→内部Source UUID映射后再写`duplicate_of_source_id`；未知引用返回中文领域错误，禁止字符串截断。
2. `...[claim_failure]`
   - 预期：真实Claim DataError先rollback，再用安全事务将Run/Task/AgentExecution补偿为失败/可恢复，并各写一次失败Event/Audit。
   - 实际：`PendingRollbackError`穿透API；Run=`运行中`、Task=`running`、AgentExecution=`completed`；workflow_failed、Task失败审计、AgentExecution失败审计均为0。
   - 最小建议：异常边界第一步无条件rollback，缓存标量ID后再开启独立补偿事务，禁止从失败Session读取过期ORM属性。
3. `...[evidence_fk]`
4. `...[flush_failure]`
5. `...[commit_failure]`
   - 预期：真实23503/23505（含Evidence flush完成后的deferred commit失败）均只产生一次Task失败审计和一次AgentExecution `execution_failed`审计。
   - 实际：三种路径均为Task失败审计2条、AgentExecution失败审计0条；状态补偿、正式Research回滚、同trace重放幂等通过。
   - 最小建议：Task失败状态更新与显式审计只保留一个append入口；补偿事务按execution_id幂等写入唯一的AgentExecutionAudit。

已关闭项：Source.query_id、Evidence外键、Task Summary重复、跨Execution改绑、四路并发正式数据唯一性、五项中文409。完整863+回归未执行，原因是第一阶段代码门禁非零失败。

## 273e6587 PostgreSQL最终验收失败矩阵

评估Commit：`273e658700439e34911dcb6c1e4a7fb2e80101b9`；同步Merge：`6c334405ad3fc60ebe5ecc9dc3fd83fea0b128a4`。结果：`19 passed, 4 failed`。

1. `...[claim_failure]`：真实Claim DataError后 `PendingRollbackError`仍穿透API；Run=`运行中`、Task=`running`、AgentExecution=`completed`，workflow_failed、Task失败审计、AgentExecution失败审计均为0。最小建议仍是异常边界先rollback并使用缓存标量ID，在独立补偿事务中写失败状态与幂等审计。
2. `...[evidence_fk]`
3. `...[flush_failure]`
4. `...[commit_failure]`
   - 三路均已正确回滚Research，并且Knowledge Asset/Version、Skill Invocation、Task Result无残留；Run/Task/AgentExecution状态、workflow_failed=1、AgentExecution execution_failed=1及同trace重放幂等均通过。
   - 唯一剩余失败为Task `alpha_workflow_failed`审计各有2条，预期恰好1条。最小建议：状态更新隐式审计和显式`write_audit_log`只保留一个append入口，或以task/run/action幂等键抑制重复写入。

已关闭：恶意duplicate_of_source_id内部UUID映射、Agent失败审计缺失、后三路失败Event与正式数据原子性。Evidence Gate单独为`5 passed, 8 failed`；完整回归因代码门禁非零失败未执行。

## 8d9b5f28 代码阻塞关闭

冻结代码Commit：`8d9b5f2890545f1f08d05b9b1618f71ff82d6621`。

- 四个历史失败节点：`4 passed, 0 failed`。
- PostgreSQL完整定向门禁：`23 passed, 0 failed`。
- Backend/代码完整回归：`892 passed, 0 failed, 82 warnings in 330.38s`。
- Alpha E2E/质量专项：`28 passed`；Frontend Gate：`6 passed`；V1：`2 passed`；Static Security：`1 passed`；Sensitive Scan：`2 passed`。
- Claim DataError、Evidence 23503、flush 23505及deferred final-commit 23503均完成安全rollback和精确一次补偿审计；PendingRollback、重复Task Audit、缺失Agent Audit及正式数据残留全部关闭。
- 0005结论保持：两个真实Revision在线性DAG上，逐表受`_has_table`保护，真实PostgreSQL fresh upgrade已通过；文件命名债务不是当前Migration执行失败。

当前只剩独立Migration Evidence Bundle阻塞：`5 passed, 8 failed`。代码失败矩阵已清零。

## Evidence Gate合同校正后的当前阻塞

合同现为：最终Head=`0042_v2_alpha_workflow_unique_constraints`；Path A=`v1.0.1`实际Commit/`0027_v1_schema_alignment`；Path B=`85586868bad3dd5d0fecba5f840383feccdc1c78`/`0041_v2_alpha_migration_history_repair`。旧merge-base `2ca1a2579569324ce3ca82f68332fb7f96be004d`仅允许标记为`KNOWN_BROKEN_HISTORICAL_BASELINE`。

旧证据Bundle复验为`5 passed, 9 failed`，当前失败均为证据内容缺失或过期：Path A/B无结构化RAW区、最终Revision仍未统一到0042、Manifest缺字段、Checksum不可复算、0037披露不完整。旧的“最终必须0041”和“Path B必须真实merge-base”均已从Gate删除，不再是失败原因。
