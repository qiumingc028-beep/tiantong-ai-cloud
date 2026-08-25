# PROJECT_STATUS

## V2 Usable V1 S1 release candidate

- 候选基线：本文件所在的新 release-candidate 提交；直接父提交为 `baad4adebe17f3b0bb44e4ca40e680ef10cf91ea`。
- PR：[#34](https://github.com/qiumingc028-beep/tiantong-ai-cloud/pull/34) 仍为 OPEN，尚未合并。
- 生产状态：生产仍运行旧基线 `483ebf560e1a4cfadecee4912a3ff6bca99516f6`；本候选尚未生产部署。
- 业务 UAT：`12/12 PASS`。
- Trusted CI replacement：`1691/1691 PASS`；FC-CI-01 `593/593 PASS`、FC-CI-02 `11/11 PASS`、FC-CI-03 `12/12 PASS`。
- 数据库：Alembic 唯一 head 为 `0047_skill_invocation_audit_scope`。
- CI 合同：job-local PostgreSQL 16、Redis 7、完整 Git 历史，以及从当前候选源码构建的临时 backend/worker 测试镜像；目标为零 SKIP。
- Research 安全：list/detail/sources/claims/evidence 五个读取入口均在 SQL 层执行 Owner scope 隔离，foreign/missing 非枚举。
- Skills Invocation 安全：list/detail/audit/cancel/retry 五个入口均在 SQL 层执行 Owner scope 隔离；EmployeeLog 以 `skill_invocation_id` 精确关联审计。
- 发布门禁：生产数据库与配置备份、rollback readiness 及回滚演练必须在后续生产任务中重新核验；当前不得宣称备份或回滚已就绪。

## 项目名称

天统AI云中台

## 当前版本

V2 Usable V1 S1 release candidate

当前 Git Commit:

以本文件所在的 release-candidate 提交为准（直接父提交 `baad4adebe17f3b0bb44e4ca40e680ef10cf91ea`）。

## 当前 Sprint

R229：文档真值、CI 零 SKIP 与不可变 release candidate 封板

状态：候选验证中；PR OPEN，未合并、未生产部署

## 已完成

- Sprint14：天赋 Skill / 插件赋能中心
- Sprint15：Skill / 插件研究中心
- Sprint16：Deploy Center / CEO Deploy Loop
- Sprint17：AI员工自动派单中心
- Sprint18：AI员工执行引擎
- Sprint19：天复：AI员工复盘学习中心
- Sprint20：AI员工自学习进化中心
- Sprint21：天脑 + 天眼工具权限底座
- Sprint22：Brain Center + Tool Router dry-run 联动
- Sprint23：Brain Center + Orchestrator dry-run 联动
- Sprint24：Brain Execution Center dry-run
- Sprint25：Brain Execution Engine V2
- Sprint25.3：企业级执行引擎增强
- Sprint26：AI员工真实执行闭环 MVP
- Sprint26.1：Sprint26 部署同步与线上验证
- Sprint26.2：天统AI项目长期记忆档案系统 MVP
- Sprint26.3：天统AI项目自动档案同步系统 MVP
- Sprint26.4：Archive Sync 安全审计与正式封版

## 进行中

- R229 正在固定新的不可变 release-candidate 提交、完成 Spec 与 Standards/Security 复审、生成并恢复验证 bundle，以及更新现有 PR #34。
- PR 的自然 CI 必须达到 `1691 PASS / 0 SKIP / 0 FAIL / 0 ERROR`；不得手工 rerun 掩盖首败。

## 下一步

1. 仅在 R229 复审、bundle verify/restore 与 PR 自然 CI 全部通过后，将结果返回 V2 主控。
2. 由后续受控生产任务重新核验生产身份、数据库与配置备份、rollback rehearsal、最终 PR 差异及发布入口。
3. 未获得后续明确授权前，不得合并 PR #34，不得部署生产。

## 风险

- 当前候选包含数据库迁移与 Owner scope 安全修复；CI 通过不替代生产备份、维护窗口、写入冻结和回滚演练。
- PR #34 仍为 OPEN，当前候选与生产运行版本不同；禁止把候选验证结果表述为生产发布结果。
- 生产环境密码、token、API key、连接串及其他凭据不得写入文档、日志或 release bundle。

## 禁止事项

- 禁止自动修改业务代码。
- 禁止自动提交 Git。
- 禁止自动部署。
- 禁止自动调用外部 API。
- 禁止在文档中记录 password / token / secret / API key / Authorization / Bearer / private_key。
- 本任务禁止 merge 与生产部署；发布文档不得提前标记 production ready 或 rollback ready。

## Sprint 完成记录

| Sprint | 完成内容 | 负责人 | Commit ID | 测试结果 | 部署状态 |
| --- | --- | --- | --- | --- | --- |
| Sprint26.4 | Archive Sync 长期记忆档案系统安全审计与正式封版 | 天检 / 天监 / 天盾 | `66ae283785545c6487230938307cd7f89a648170` | `57 passed`，安全审计 PASS | 本地运行环境同步完成，Archive API 已加载 |
| Sprint26.3 | 自动档案同步系统 MVP，新增 Archive Sync API，生成 PROJECT_STATUS / CHANGELOG / DECISION_LOG 草稿 | 天王 / 天检 / 天监 / 天盾 | `66ae283785545c6487230938307cd7f89a648170` | `568 passed`，关键回归 `57 passed` | 已部署同步验证 |
| Sprint26.2 | 长期记忆档案系统 MVP，建立项目文档中心结构 | 天藏 / 天王 | 文档草稿 | 待独立归档 | 已作为 Sprint26.3/26.4 封版基础 |
| Sprint26 | AI员工真实执行闭环 MVP，天商可完成男士机械表市场分析任务 | 天王 / 天检 / 天监 / 天盾 | `629b06289e2003ba20932c99a8e47afc5ed59559` | `561 passed` | 已部署验证 |
| Sprint25.3 | Brain Execution Engine 增强，状态机、priority queue、worker heartbeat、retry、timeout、CEO summary | 天王 | `16c0d87c484b133b19d8a0f772586898b0c882d5` | `555 passed` | 已完成 |
| Sprint24 | Brain Execution Center dry-run 页面与后端 | 天王 / 天颜 | `5b032262a87c287373088d1054887d2a75cb23c0` | 已通过 | 已部署 |
| Sprint23 | Brain Center + Orchestrator dry-run 联动 | 天王 / 天颜 | `46b09d2` / `d941d50` | 已通过 | 已部署 |
| Sprint22 | Brain Center + Tool Router dry-run 联动 | 天王 / 天颜 | `3b15955` / `377c3c6` | 已通过 | 已部署 |
| Sprint21 | Tool Center / Tool Router 权限底座 | 天王 / 天颜 | `0c4fd83` / `009849e` | 已通过 | 已完成 |
| Sprint20 | AI员工自学习进化中心 | 天王 / 天颜 | `7130d2816f778fca9dc26eeea87cdd24549c8d84` | 已通过 | 已完成 |
| Sprint19 | AI员工复盘学习中心 | 天王 / 天颜 | `105d2ce71fdd8e7187563e40f6b641655a2acada` | 已通过 | 已完成 |
