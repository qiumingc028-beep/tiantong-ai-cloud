# Sprint31.1 Development Plan: Boss Command Center V2

## 1. 目标

Sprint31.1 的目标是把《Sprint31 老板驾驶舱 V2 技术设计文档》拆成可执行开发任务。

本阶段仍然只做开发拆解，不写业务代码。

总原则：

- 不修改 Task Center 核心状态流。
- 不修改 Orchestrator 规则。
- 不修改 Execution Engine 状态机。
- 不修改 Deploy Center 流程。
- 不新增自动执行能力。
- 老板驾驶舱 V2 第一阶段保持只读聚合。

## 2. 总体开发顺序

推荐顺序：

```text
Sprint31.1  开发拆解
Sprint31.2  后端只读聚合 API
Sprint31.3  后端测试验收
Sprint31.4  前端老板驾驶舱 V2
Sprint31.5  前端验收
Sprint31.6  安全审计
Sprint31.7  部署验证
Sprint31.8  老板浏览器验收
```

必须先做：

- 后端只读 API。
- API 权限控制。
- API 数据字段稳定。
- 前端页面只读展示。

可以后做：

- 数据库快照表。
- 历史趋势图。
- 天检独立验收中心摘要。
- 市场情报、金融/A股、AI新闻等数据中心。

## 3. 后端开发拆解

### Sprint31.2-A: API 路由骨架

目标：

- 在现有 `backend/routers/ceo_dashboard.py` 中增加 v2 只读接口。

新增 API：

```text
GET /api/ceo-dashboard/v2/overview
GET /api/ceo-dashboard/v2/pending-actions
GET /api/ceo-dashboard/v2/employee-summary
GET /api/ceo-dashboard/v2/task-summary
GET /api/ceo-dashboard/v2/orchestrator-summary
GET /api/ceo-dashboard/v2/execution-summary
GET /api/ceo-dashboard/v2/deploy-summary
```

Codex 执行边界：

- 只改 `backend/routers/ceo_dashboard.py`。
- 不新增 migration。
- 不修改 Task Center / Orchestrator / Execution Engine / Deploy Center。

验收：

- 所有接口未登录返回 401。
- Viewer / 普通员工返回 403。
- Owner/Admin/Boss 返回 200。
- 返回 JSON 包含 `readonly: true`。

### Sprint31.2-B: Overview 聚合接口

目标：

- 实现 `/api/ceo-dashboard/v2/overview`。

数据来源：

- 系统健康：复用现有 `build_system_health`
- AI员工：复用 `build_employee_summary`
- Task Center：复用 `build_task_summary`
- 待确认事项：复用或抽象 `build_pending_actions`
- 部署状态：复用 `build_deploy_summary`
- Execution Engine：复用 `build_brain_execution_summary`

返回结构：

```json
{
  "readonly": true,
  "checked_at": "ISO8601",
  "overall_status": "normal",
  "system_status": {},
  "employee_summary": {},
  "task_summary": {},
  "pending_action_summary": {},
  "risk_summary": {},
  "deploy_summary": {},
  "execution_summary": {}
}
```

Codex 执行边界：

- 聚合现有数据。
- 不写数据库。
- 不触发任务。

### Sprint31.2-C: Pending Actions 接口

目标：

- 实现 `/api/ceo-dashboard/v2/pending-actions`。

聚合来源：

- Task Center 待处理任务。
- 高风险任务。
- Orchestrator blocked 项。
- Execution Engine failed / timeout。
- Deploy Center health warning。
- 天检/天监/天盾待处理状态。

返回结构：

```json
{
  "readonly": true,
  "pending_count": 0,
  "items": []
}
```

字段：

```text
id
source
source_id
title
description
risk_level
status
requires_boss_confirm
requires_security_audit
target_url
created_at
```

安全：

- 只展示。
- 不提供批准按钮。
- 不改变任何状态。

### Sprint31.2-D: Employee Summary 接口

目标：

- 实现 `/api/ceo-dashboard/v2/employee-summary`。

依赖：

- `AiEmployee`
- `TaskCenterTask`
- 现有 `/api/ai-employees/runtime-status` 逻辑。

返回：

```json
{
  "readonly": true,
  "total": 27,
  "online": 27,
  "idle": 0,
  "running": 0,
  "blocked": 0,
  "error": 0,
  "recent_errors": [],
  "running_employees": []
}
```

开发注意：

- 如果现有数据无法判断在线，先按 active/status 聚合。
- 不更新 AI员工状态。

### Sprint31.2-E: Task Summary 接口

目标：

- 实现 `/api/ceo-dashboard/v2/task-summary`。

依赖：

- `TaskCenterTask`

聚合状态：

```text
created
split
assigned
running
result_submitted
accepted
rejected
audited
summarized
failed
```

返回：

```json
{
  "readonly": true,
  "total": 0,
  "today_total": 0,
  "created": 0,
  "assigned": 0,
  "running": 0,
  "result_submitted": 0,
  "accepted": 0,
  "rejected": 0,
  "failed": 0,
  "recent_tasks": [],
  "recent_failed_tasks": []
}
```

开发注意：

- 只查询。
- 不调用任务状态修改接口。

### Sprint31.2-F: Orchestrator Summary 接口

目标：

- 实现 `/api/ceo-dashboard/v2/orchestrator-summary`。

依赖：

- `orchestrator_analysis_records`
- `orchestrator_task_links`
- 现有 Orchestrator router 查询逻辑。

返回：

```json
{
  "readonly": true,
  "recent_analysis_count": 0,
  "recent_task_links": [],
  "blocked_count": 0,
  "blocked_items": [],
  "last_analysis_at": null
}
```

开发注意：

- 只展示最近记录。
- 不生成任务草稿。
- 不创建 Task Center 任务。

### Sprint31.2-G: Execution Summary 接口

目标：

- 实现 `/api/ceo-dashboard/v2/execution-summary`。

依赖：

- `BrainExecutionRun`
- `BrainWorkerStatus`
- `get_queue_status`
- execution logs

返回：

```json
{
  "readonly": true,
  "queue": {
    "waiting": 0,
    "running": 0,
    "success": 0,
    "failed": 0,
    "timeout": 0
  },
  "workers": [],
  "recent_logs": [],
  "latest_error": null
}
```

安全：

- 不调用 `/api/brain/start`。
- 不推进状态机。
- 不消费 Redis queue。

### Sprint31.2-H: Deploy Summary 接口

目标：

- 实现 `/api/ceo-dashboard/v2/deploy-summary`。

依赖：

- `DeployRecord`
- `HealthCheckRecord`
- 现有 `Deploy Center` 查询逻辑。

返回：

```json
{
  "readonly": true,
  "latest_deploy": {},
  "last_health_check": {},
  "service_status": {},
  "service_stability_score": 100
}
```

安全：

- 不执行 `/api/deploy-center/health/check`，除非该接口本身已有明确只记录健康检查的设计。
- 不触发部署。
- 不执行 shell / docker / systemctl。

## 4. 后端数据模型规划

### 第一阶段：不新增数据库表

Sprint31.2 推荐不新增 migration。

理由：

- 驾驶舱 V2 第一阶段是只读聚合。
- 现有表已经覆盖任务、员工、执行、部署和审批状态。
- 避免为展示层过早增加数据库复杂度。

### 后续可选表

仅当 Sprint31 后续需要历史趋势和日报留痕时，再考虑：

```text
dashboard_snapshots
dashboard_alerts
```

这两个表不应进入 Sprint31.2 MVP。

## 5. 后端权限控制

必须复用现有：

- `current_user`
- `normalize_role`

允许：

- `owner`
- `admin`
- `boss` 如果角色归一后存在

禁止：

- 未登录：401
- viewer：403
- 普通 AI员工：403

所有 v2 API 必须返回只读数据，不包含敏感字段。

禁止返回：

- `password`
- `password_hash`
- `token`
- `secret`
- `API Key`
- `Authorization`
- `bearer-style credential`
- `private_key`
- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`

## 6. 前端开发拆解

### Sprint31.4-A: 页面结构升级

目标：

- 升级 `frontend/index.html` 为老板驾驶舱 V2。

保留：

- 现有菜单体系。
- 现有登录检查。
- 现有整体视觉风格。

新增区域：

```text
今日运营总览
老板待处理事项
AI员工运行状态
AI任务中心摘要
AI任务编排摘要
Execution Engine 摘要
天盾部署健康
最近提醒
```

Codex 执行边界：

- 只改 `frontend/index.html`。
- 不新增前端框架。
- 不重做 UI。

### Sprint31.4-B: 前端状态管理

目标：

- 在静态页面内建立轻量状态对象。

建议：

```javascript
const dashboardState = {
  overview: null,
  pendingActions: [],
  employeeSummary: null,
  taskSummary: null,
  orchestratorSummary: null,
  executionSummary: null,
  deploySummary: null,
  loading: false,
  error: null
};
```

状态来源：

- 页面初始化一次加载。
- 手动刷新按钮。

不做：

- WebSocket。
- EventSource。
- 自动高频轮询。

### Sprint31.4-C: API 接入

目标：

- 接入后端 v2 API。

调用顺序：

```text
GET /api/me
GET /api/ceo-dashboard/v2/overview
GET /api/ceo-dashboard/v2/pending-actions
GET /api/ceo-dashboard/v2/employee-summary
GET /api/ceo-dashboard/v2/task-summary
GET /api/ceo-dashboard/v2/orchestrator-summary
GET /api/ceo-dashboard/v2/execution-summary
GET /api/ceo-dashboard/v2/deploy-summary
```

错误处理：

- 401：跳转登录。
- 403：显示无权限。
- 500：显示服务器异常。
- 网络异常：显示网络异常。
- 空数组：显示暂无数据。

### Sprint31.4-D: 组件渲染

组件函数建议：

```text
renderOverview()
renderPendingActions()
renderEmployeeSummary()
renderTaskSummary()
renderOrchestratorSummary()
renderExecutionSummary()
renderDeploySummary()
renderAlerts()
```

安全要求：

- 所有动态文本必须 escape。
- object / array 必须安全格式化。
- 不显示 `[object Object]`。

### Sprint31.4-E: 路由和跳转

页面只允许跳转到已有中心：

```text
/task-center.html
/ai-employees.html
/orchestrator.html
/ai-execution.html
/deploy-center.html
/employee-activity-log.html
/employee-activity-trace.html
```

禁止：

- window.open 外部跳转。
- iframe。
- 浏览器自动化。
- 外部 API 页面跳转。

## 7. 前端组件清单

### 必须开发

- KPI 卡片组件
- 待处理事项列表
- AI员工运行状态卡
- Task Center 状态卡
- Orchestrator 摘要卡
- Execution Engine 摘要卡
- Deploy Health 卡
- 最近提醒列表
- 错误/空状态组件

### 可以后开发

- 趋势图
- 历史日报
- 市场热点卡
- AI新闻卡
- 金融/A股行情卡
- 电商经营数据大屏

## 8. 依赖关系

### Task Center

使用：

- 任务数量
- 任务状态
- 最近任务
- 失败任务
- 待验收任务

不能：

- 改状态。
- 自动分配。
- 自动开始任务。

### AI员工

使用：

- 员工数量
- 员工状态
- 当前任务
- 最近错误

不能：

- 创建员工。
- 修改员工。
- 改权限。

### Orchestrator

使用：

- 最近分析。
- task link。
- blocked 项。

不能：

- 生成任务草稿。
- 确认创建任务。
- 推进 Orchestrator 规则。

### Execution Engine

使用：

- execution run 状态。
- worker 状态。
- queue 状态。
- logs。

不能：

- start execution。
- consume queue。
- 改状态机。

### 天盾 Deploy Center

使用：

- 部署记录。
- 健康检查记录。
- 服务状态。

不能：

- 部署。
- docker。
- systemctl。
- shell。

## 9. Codex 可执行 Sprint 拆分

### Sprint31.2: 后端只读 API

负责人：

- 天王：后端开发中心

输入：

- `docs/SPRINT31_COMMAND_CENTER_DESIGN.md`
- `docs/SPRINT31_1_DEVELOPMENT_PLAN.md`

任务：

- 在 `backend/routers/ceo_dashboard.py` 增加 v2 API。
- 不新增数据库表。
- 增加 `tests/test_ceo_dashboard_v2.py`。

验收：

- 401 / 403 / 200 覆盖。
- 全部接口只读。
- 不返回敏感字段。

### Sprint31.3: 后端验收

负责人：

- 天检：测试验收中心

任务：

- 验证所有 v2 API。
- 验证权限。
- 验证不影响 Task Center / Orchestrator / Execution Engine / Deploy Center。

输出：

- PASS / FAIL
- 风险项
- 是否允许前端开发

### Sprint31.4: 前端驾驶舱 V2

负责人：

- 天颜：前端联调中心

任务：

- 升级 `frontend/index.html`。
- 接入 v2 API。
- 完成只读展示。
- 保持现有 UI 风格。

验收：

- 页面正常加载。
- 所有模块完整。
- 错误和空数据正常。
- 没有危险按钮。

### Sprint31.5: 前端验收

负责人：

- 天检：测试验收中心

任务：

- 页面验收。
- API 联调。
- 权限检查。
- 回归测试。

输出：

- PASS / FAIL
- 风险项
- 是否允许安全审计

### Sprint31.6: 安全审计

负责人：

- 天监：AI安全审计中心

检查：

- 无自动执行。
- 无自动部署。
- 无权限绕过。
- 无敏感字段泄露。
- boss_confirm / security_audited 未被绕过。

输出：

- 安全等级
- 必须修复项
- 是否允许部署验证

### Sprint31.7: 部署验证

负责人：

- 天盾：部署运维中心

任务：

- Git 同步。
- Docker build。
- 健康检查。
- 页面检查。
- API 检查。

禁止：

- 修改业务代码。
- 修改数据库结构。
- 手动改线上数据。

### Sprint31.8: 老板浏览器验收

负责人：

- 老板 / 天检协同

检查：

- 登录。
- 驾驶舱 V2。
- 待处理事项。
- AI员工状态。
- Task Center 摘要。
- Orchestrator 摘要。
- Execution Engine 摘要。
- Deploy Health 摘要。

## 10. 必须先开发

后端：

- `/api/ceo-dashboard/v2/overview`
- `/api/ceo-dashboard/v2/pending-actions`
- `/api/ceo-dashboard/v2/employee-summary`
- `/api/ceo-dashboard/v2/task-summary`
- `/api/ceo-dashboard/v2/execution-summary`

前端：

- `frontend/index.html` V2 首屏
- 今日运营总览
- 待处理事项
- AI员工运行状态
- Task Center 摘要
- Execution Engine 摘要

原因：

- 这些是老板每天使用的核心信息。
- 数据来源已存在。
- 风险最低。

## 11. 可以后开发

接口：

- `/api/ceo-dashboard/v2/orchestrator-summary`
- `/api/ceo-dashboard/v2/deploy-summary`
- 后续 Test Center 摘要
- 历史趋势接口

页面：

- 趋势图
- 多日对比
- AI经营数据卡
- 市场热点入口
- 电商数据入口

原因：

- 这些增强价值高，但不影响驾驶舱 V2 首版成立。

## 12. 暂不开发的数据中心

以下数据中心不进入 Sprint31.1/31.2：

- 全球热点中心
- AI新闻中心
- 金融市场中心
- A股行情中心
- 天采电商数据中心 v2
- RAG 知识搜索

原因：

- 这些属于 Sprint32 之后。
- 涉及外部数据、成本、安全边界和数据质量。

## 13. 验收标准

Sprint31.1 文档通过标准：

- 前端任务拆清楚。
- 后端任务拆清楚。
- API 清单明确。
- 权限边界明确。
- 依赖模块明确。
- 每个任务可以交给 Codex 单独执行。
- 没有要求修改核心架构。
- 没有新增危险能力。

Sprint31 后续开发通过标准：

- `pytest` 全部通过。
- `git diff --check` 通过。
- v2 API 未登录 401。
- Viewer / 普通员工 403。
- Owner/Admin/Boss 200。
- 页面无自动执行按钮。
- 页面无自动部署按钮。
- 页面不展示敏感字段。
- 不破坏 Task Center。
- 不破坏 Orchestrator。
- 不破坏 Execution Engine。
- 不破坏 Deploy Center。

## 14. 结论

Sprint31.1 建议完成后，下一步进入 Sprint31.2 后端只读聚合 API。

最小可交付版本应该先完成：

```text
overview
pending-actions
employee-summary
task-summary
execution-summary
```

这五个接口足以支撑老板驾驶舱 V2 的核心首屏。
