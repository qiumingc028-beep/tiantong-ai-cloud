# DECISION_LOG

## 决策 001：第一阶段所有高风险能力必须 dry-run 或人工审批

日期：2026-07-08

背景：

系统逐步具备任务拆解、工具选择、Worker 执行和 AI员工协作能力。

决策：

- Shell、部署、代码修改、外部 API、付款、广告投放、商品发布等能力禁止自动执行。
- 高风险动作必须老板确认和天监审核。

影响：

- Sprint21-Sprint26 的工具和执行能力默认使用 simulation / internal mock。

## 决策 002：Sprint26 先让天商形成真实执行闭环 MVP

日期：2026-07-08

背景：

需要从“规划与模拟”进入“单员工真实闭环”。

决策：

- 第一个真实执行员工选择天商。
- 任务场景为男士机械表市场分析。
- 工具保持内部模拟，不调用外部 API。

影响：

- 新增 `employee_execution_contracts`。
- 新增 `backend/workers/tian_shang_worker.py`。
- 新增内部工具 `backend/tools/`。

## 决策 003：项目长期记忆必须落到 docs

日期：2026-07-08

背景：

聊天上下文会丢失，换窗口、换助手、换电脑会造成项目状态断层。

决策：

- 以 `docs/PROJECT_STATUS.md` 作为当前状态入口。
- 以 `docs/ARCHITECTURE.md`、`docs/AI_EMPLOYEE_MAP.md`、`docs/SPRINT_ROADMAP.md`、`docs/CHANGELOG.md`、`docs/DECISION_LOG.md`、`docs/CODEX_RULES.md` 作为长期记忆核心文件。

影响：

- Sprint26.2 只建立知识档案，不修改业务代码。
