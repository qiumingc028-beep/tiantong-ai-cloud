# 天统 AI V2 项目正式交接基线

本文档是 V2 Sprint 11.1 关闭后的唯一正式项目交接基线。每个 Sprint 关门后，必须由人工核验并同步更新本文档；不得依赖聊天记录、旧工作区或历史 QA 快照替代正式交接。

## 当前主线

- 当前集成分支：`develop-v2`
- 当前集成完整 Head：`bdae8a6300c0f9440638044f6e0230120204719b`
- 本文档来源分支：`docs/v2-sprint11-1-project-handoff`
- 下一阶段：内部环境投入使用准备，不是开发新功能。
- 本次 Alpha Workflow 相关四项 Feature Flag 默认关闭，定义位置为 `backend/config.py`：
  - `ALPHA_WORKFLOW_ENABLED=false`
  - `ALPHA_SCENARIO_ENABLED=false`
  - `ALPHA_WORKFLOW_DASHBOARD_ENABLED=false`
  - `ALPHA_DASHBOARD_ENABLED=false`
- `AGENT_RUNTIME_ENABLED` 默认值为 `true`，因此上述四项 Alpha Flag 的状态不代表整个 V2 的全部开关状态。
- V2 当前未部署内部或生产环境，未执行生产 Migration，未合并 `main`。

## Sprint 11.1 合并记录

合并顺序固定为 PR #17 → PR #18 → PR #19：

| PR | 内容 | Head Commit | Merge Commit |
|---|---|---|---|
| #17 | Alpha Workflow 后端、Migration 与正式证据 | `f0f15f47dba447cee49a18568bbce18e72cb2ccb` | `59d87762d8cf00d73ca1ff4e5728a53576dd64a4` |
| #18 | Alpha 专属前端 | `2306c5ef7e0444fa41b7b58ce86595065547f3c4` | `41e05bb4a7441d3b37bb167aaf364a1bb4dfb49f` |
| #19 | QA、验收报告与机器结果 | `2a18ec1dcace31a19bf0c878a394b7bccd79d8bd` | `bdae8a6300c0f9440638044f6e0230120204719b` |

关键冻结点：

- `CODE_FREEZE_COMMIT = 8d9b5f2890545f1f08d05b9b1618f71ff82d6621`
- `AUTHENTIC_EVIDENCE_COMMIT = f0f15f47dba447cee49a18568bbce18e72cb2ccb`
- `QA_HEAD = 2a18ec1dcace31a19bf0c878a394b7bccd79d8bd`
- `FINAL_MIGRATION_HEAD = 0042_v2_alpha_workflow_unique_constraints`

## 正式验证结果

- PostgreSQL 定向门禁：`23 passed / 0 failed`
- Backend 完整回归：`892 passed / 0 failed`
- Official Authenticity Gate：`16 passed / 0 failed`
- Migration 最终为单一 Head：`0042_v2_alpha_workflow_unique_constraints`

正式 Migration 证据位于：

- `artifacts/alpha-migration-evidence/path_a_current.log`
- `artifacts/alpha-migration-evidence/path_b_current.log`
- `artifacts/alpha-migration-evidence/alembic-evidence.txt`
- `artifacts/alpha-migration-evidence/checksums.sha256`
- `artifacts/alpha-migration-evidence/validation-manifest.json`
- `docs/V2_ALPHA_MIGRATION_EVIDENCE.md`
- `docs/V2_MIGRATION_FREEZE_POLICY.md`

最终机器验收结果位于：

- `artifacts/qa/alpha-sprint11/migration-evidence-validation.json`

旧 QA 报告中的 `BLOCK`，以及 `artifacts/qa/alpha-sprint11/test-summary.json` 中的 `migration_evidence_accepted: false`，均是正式 Evidence Bundle 完成前的历史快照，不代表最终状态。最终 Migration 证据状态以 `migration-evidence-validation.json` 的 `PASS` 为准。历史文件保留原貌，不回写或篡改旧结论。

## 当前可用内部路径

仓库当前已有的 V1 能力路径为：

登录 → 老板驾驶舱/京东数据页面 → 今日数据手工录入或 Excel 批量导入 → 指标汇总 → AI 店长分析/任务中心。

相关接口包括：

- `POST /api/login`
- `GET /api/jd/dashboard`
- `GET /api/owner/dashboard`
- `POST /api/metrics/manual`
- `POST /api/metrics/import`
- `POST /api/ai/store-manager/analyze`
- `POST /api/ai/store-manager/enqueue`

这是仓库中已经存在的能力路径；是否已有实际运行中的内部环境，仍需由部署负责人单独现场确认。京东真实接口授权尚未完成时，不得声称已实现实时自动采集。Excel 批量导入是当前最现实的短期数据进入方式。

## 发布与运行状态

- 当前正式发布版本：`V1.0.1`。
- V2 尚未部署内部环境或生产环境。
- 仓库当前没有足够证据确认公司此刻实际在线运行实例及其精确版本。
- 后续部署前，必须由部署负责人现场确认实际实例、版本、数据库状态、备份与回滚条件。
- “V2 尚未部署”不等于“公司当前没有生产环境”，两者不得混同。

## 当前状态分类

### 1. 已完成且有证据

- Task Center、Orchestrator、AI 员工、Research、Knowledge Center、Skills Engine、Agent Runtime、Computer Executor、Safe Workflow 与 Execution Observability 已完成 Alpha 首次全链路集成。
- Sprint 11.1 代码冻结、PostgreSQL Migration、真实性证据和完整回归均有仓库内证据。
- PR #17、#18、#19 已按固定顺序合入 `develop-v2`。

### 2. 代码完成但员工不可使用

- Alpha 全链路代码已经完成，但上述四项 Alpha Workflow Feature Flag 默认关闭。
- 尚未完成内部环境启用、权限配置、实际员工授权与运营流程验收，因此 AI 员工当前不可作为正式内部服务使用。

### 3. 配置缺口

- 内部环境的 Feature Flag、租户、员工、Skill、审批角色、设备与安全策略尚未按真实组织完成配置。
- 不得通过修改默认值或绕过审批来填补配置缺口。

### 4. 部署缺口

- V2 尚未部署内部环境或生产环境。
- 尚未执行生产 Migration，也未对生产流量开放。
- `main` 未合并本次 V2 交付。

### 5. 数据接入缺口

- 京东 60 店数据仍未真实接入。
- 当前 Alpha 结果来自受控测试数据与演示链路，不得表述为真实业务系统已投入运行。

## 工作区与安全边界

- 旧“终端”脏工作区仅作为历史现场封存；不得清理、覆盖、Stash、Reset，亦不得作为后续主线开发基线。
- 后续工作必须从干净的最新 `origin/develop-v2` 创建独立分支和 Worktree。
- 不扩大 Browser、Computer、Shell、剪贴板或文件操作权限。
- V2 的生产启用继续保持关闭，任何内部启用都必须经过正式安全审查与验收。

## 内部使用缺口优先级

以下事项均为待办，不代表已经批准或完成：

1. P0：PR #20 交接文档正式关门。
2. P1：老板批准内部测试环境及部署窗口。
3. P2：内部环境备份、Migration `0027` → `0042`、健康检查与回滚验证。
4. P3：环境变量、老板/员工账号、角色与权限矩阵。
5. P4：60 店第一批数据导入；短期使用 Excel，后续取得真实京东授权。
6. P5：老板单人灰度 Alpha Workflow 四项 Flag。
7. P6：员工操作手册和内部运营验收。

## 待老板授权清单

| 序号 | 授权事项 | 当前状态 |
|---|---|---|
| 1 | 是否批准部署到内部测试环境 | `PENDING_OWNER_APPROVAL` |
| 2 | 是否批准内部测试库升级至 `0042` | `PENDING_OWNER_APPROVAL` |
| 3 | 是否批准老板单人灰度四项 Alpha Flag | `PENDING_OWNER_APPROVAL` |
| 4 | 是否批准建立员工账号和角色矩阵 | `PENDING_OWNER_APPROVAL` |
| 5 | 是否批准先用 Excel 导入首批 60 店数据 | `PENDING_OWNER_APPROVAL` |
| 6 | 是否批准后续接入京东真实授权凭据 | `PENDING_OWNER_APPROVAL` |

## 协作岗位与所有权

当前七个协作岗位为：

1. ① Codex CLI：主开发、文档整合与最终集成负责人。
2. ② 前端实现与验收岗位。
3. ③ QA 与质量门禁岗位。
4. ④ 架构与安全审查岗位。
5. ⑤ 独立认证岗位。
6. ⑥ 合并拓扑与集成审计岗位。
7. ⑦ Claude 天衡：交付一致性与落地分析，当前为只读模式。

同一时间一个文件只能有一个修改负责人。Claude 的可写任务必须使用独立 Worktree、独立任务分支和明确文件白名单；默认不得 Push、Merge 或部署。所有成果均须由 Codex CLI 复核差异、重跑正式验证并决定是否集成。

最终合并权始终归 Codex CLI。任何岗位的报告、认证或建议均不能自行替代最终集成决策。

## 后续交接要求

- 下一主线是内部真实使用准备：环境、配置、数据、权限、部署与运营准备。
- 未完成上述准备前，不得宣称 V2 已正式投入内部或生产使用。
- 不因新增协作岗位而提前开始新 Sprint、跳过 Post-Merge QA、Closeout 或正式审查。
- 每个 Sprint 关门后，必须人工核验分支 Head、PR 合并记录、Migration Head、测试证据、部署状态和数据接入状态，并同步更新本文件。
