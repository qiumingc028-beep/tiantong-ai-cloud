# Sprint31 Command Center Design

## 1. 产品目标

Sprint31 的目标是把现有老板驾驶舱升级为「老板日常经营入口 V2」。

当前 `v0.1.0-mvp` 已经具备 Task Center、AI员工、Orchestrator、Execution Engine、Deploy Center、审批中心和生产健康检查。问题不是缺少模块，而是老板每天使用时需要从多个页面跳转，信息分散。

Sprint31 只做统一展示和入口增强，不改变核心业务流程。

核心目标：

- 老板登录后 10 秒内看清系统是否正常。
- 老板能看到今天 AI 公司做了什么。
- 老板能看到哪些事项需要确认。
- 老板能看到 AI员工是否在线、是否执行任务、是否异常。
- 老板能从驾驶舱进入 Task Center、AI员工、Orchestrator、Execution Engine、Deploy Center、天检验收相关页面。
- 所有高风险事项继续保留 `boss_confirm` 和 `security_audited` 边界。

不做：

- 不自动执行任务。
- 不自动部署。
- 不自动改权限。
- 不自动调用外部 API。
- 不修改 Task Center 状态流。
- 不修改 Orchestrator 规则。
- 不修改 Execution Engine 状态机。

## 2. 页面结构设计

页面：

- 升级现有 `frontend/index.html`
- 页面名称：老板驾驶舱 V2
- 英文定位：Boss Command Center V2

页面结构：

```text
老板驾驶舱 V2
├── 顶部状态栏
│   ├── 当前登录用户
│   ├── 系统健康状态
│   ├── 最近刷新时间
│   └── 退出登录
│
├── 今日运营总览
│   ├── 系统状态
│   ├── AI员工总数 / 在线 / 工作中 / 异常
│   ├── 今日任务数 / 已完成 / 失败 / 待确认
│   ├── 待老板确认数
│   └── 风险提醒数
│
├── 老板待处理事项
│   ├── 待确认任务
│   ├── 高风险审批
│   ├── 待天检验收
│   ├── 待天监安全审计
│   └── 待天盾部署确认
│
├── AI员工运行状态
│   ├── 员工状态分布
│   ├── 当前运行员工
│   ├── 最近完成员工
│   ├── 最近异常员工
│   └── 跳转 AI员工中心
│
├── AI任务中心摘要
│   ├── created
│   ├── assigned
│   ├── running
│   ├── result_submitted
│   ├── accepted / rejected
│   └── 跳转 Task Center
│
├── AI任务编排 / Orchestrator 摘要
│   ├── 最近分析记录
│   ├── 最近任务链路
│   ├── 阻断项
│   └── 跳转 AI任务编排中心
│
├── Execution Engine 摘要
│   ├── 队列数量
│   ├── running / success / failed / timeout
│   ├── Worker 状态
│   └── 跳转 Brain Execution Center
│
├── 天盾部署健康
│   ├── backend / worker / redis / postgres / nginx
│   ├── latest deploy
│   ├── latest health check
│   └── 跳转 Deploy Center
│
└── 最近提醒
    ├── 系统异常
    ├── 任务失败
    ├── 审批等待
    └── 安全边界提示
```

## 3. 前端组件规划

当前前端是静态 HTML 页面体系，Sprint31 不引入前端框架，不做 UI 大改。采用现有 `index.html` 风格继续增强。

建议组件：

### 3.1 顶部 Status Bar

字段：

- `current_user`
- `role_label`
- `system_status`
- `checked_at`

状态：

- `normal`
- `warning`
- `critical`

### 3.2 KPI Cards

展示：

- 系统状态
- AI员工在线数量
- 今日任务数
- 待确认事项
- 风险提醒
- Worker状态

数据来源：

- `/api/ceo-dashboard/v2/overview`

### 3.3 Pending Action List

展示：

- 标题
- 来源模块
- 风险等级
- 当前状态
- 推荐处理动作
- 跳转入口

只允许：

- 查看
- 跳转

不允许：

- 页面内直接批准高风险操作
- 页面内直接执行任务
- 页面内直接部署

数据来源：

- `/api/ceo-dashboard/v2/pending-actions`

### 3.4 Employee Runtime Panel

展示：

- 总员工数
- 在线数
- idle / running / blocked / error
- 当前任务
- 最近错误

数据来源：

- `/api/ceo-dashboard/v2/employee-summary`
- 可复用 `/api/ai-employees/runtime-status`

### 3.5 Task Summary Panel

展示：

- Task Center 各状态数量
- 最近任务
- 失败任务
- 待验收任务

数据来源：

- `/api/ceo-dashboard/v2/task-summary`

### 3.6 Orchestrator Panel

展示：

- 最近分析记录
- 最近 task graph / task link
- blocked 原因
- 安全边界提示

数据来源：

- `/api/ceo-dashboard/v2/orchestrator-summary`

### 3.7 Execution Engine Panel

展示：

- execution queue
- worker status
- success / failed / timeout
- latest execution logs

数据来源：

- `/api/ceo-dashboard/v2/execution-summary`
- 可复用 `/api/brain-execution-summary`

### 3.8 Deploy Health Panel

展示：

- latest deploy
- health check status
- service stability score
- backend / worker / redis / postgres / nginx

数据来源：

- `/api/ceo-dashboard/v2/deploy-summary`
- 复用现有 Deploy Center 数据。

## 4. 后端 API 规划

新增前缀：

```text
/api/ceo-dashboard/v2
```

### 4.1 总览接口

```text
GET /api/ceo-dashboard/v2/overview
```

返回：

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

用途：

- 页面首屏 KPI。
- 不做写操作。

### 4.2 待处理事项

```text
GET /api/ceo-dashboard/v2/pending-actions
```

返回：

```json
{
  "pending_count": 0,
  "items": [
    {
      "id": "string",
      "source": "task_center | orchestrator | execution_engine | deploy_center | test_center | security_audit",
      "title": "string",
      "description": "string",
      "risk_level": "low | medium | high",
      "status": "pending | blocked | waiting_review",
      "requires_boss_confirm": true,
      "requires_security_audit": true,
      "target_url": "/task-center.html",
      "created_at": "ISO8601"
    }
  ]
}
```

说明：

- 只聚合待处理事项。
- 不提供批准动作。
- 实际批准仍交给对应中心完成。

### 4.3 AI员工摘要

```text
GET /api/ceo-dashboard/v2/employee-summary
```

返回：

```json
{
  "total": 27,
  "online": 27,
  "idle": 25,
  "running": 2,
  "blocked": 0,
  "error": 0,
  "recent_errors": [],
  "running_employees": []
}
```

### 4.4 Task Center 摘要

```text
GET /api/ceo-dashboard/v2/task-summary
```

返回：

```json
{
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

### 4.5 Orchestrator 摘要

```text
GET /api/ceo-dashboard/v2/orchestrator-summary
```

返回：

```json
{
  "recent_analysis_count": 0,
  "recent_task_links": [],
  "blocked_count": 0,
  "blocked_items": [],
  "last_analysis_at": "ISO8601"
}
```

### 4.6 Execution Engine 摘要

```text
GET /api/ceo-dashboard/v2/execution-summary
```

返回：

```json
{
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

### 4.7 Deploy Center 摘要

```text
GET /api/ceo-dashboard/v2/deploy-summary
```

返回：

```json
{
  "latest_deploy": {},
  "last_health_check": {},
  "service_status": {
    "backend": "healthy",
    "worker": "running",
    "postgres": "healthy",
    "redis": "healthy",
    "nginx": "healthy"
  },
  "service_stability_score": 100
}
```

## 5. 数据库字段设计

Sprint31 第一阶段原则：

- 尽量不新增核心业务表。
- 只读聚合现有表。
- 如确实需要缓存驾驶舱快照，新增独立表，不影响现有流程。

### 5.1 第一阶段：无新增表

优先读取：

- `task_center_tasks`
- `ai_employees`
- `brain_execution_runs`
- `brain_worker_status`
- `deploy_records`
- `health_check_records`
- `orchestrator_analysis_records`
- `orchestrator_task_links`
- `employee_execution_logs`

### 5.2 可选表：dashboard_snapshots

如后续需要缓存每日经营摘要，可新增：

```text
dashboard_snapshots
```

字段：

```text
id
snapshot_date
snapshot_type
summary_json
risk_level
created_at
created_by
```

用途：

- 保存每日快照。
- 供历史趋势和日报使用。

限制：

- 不参与 Task Center 状态流转。
- 不修改 AI员工状态。
- 不触发执行。

### 5.3 可选表：dashboard_alerts

如后续需要持久化提醒，可新增：

```text
dashboard_alerts
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
target_url
requires_boss_confirm
requires_security_audit
created_at
resolved_at
```

限制：

- 只记录提醒。
- 不替代原模块审批。

## 6. 与现有模块关系

### 6.1 Task Center

关系：

- 只读取任务状态、任务数量、最近任务、失败任务、待验收任务。
- 提供跳转入口到 `task-center.html`。

禁止：

- 不直接修改任务状态。
- 不绕过 Task Center 的 assign / start / review / audit 流程。

### 6.2 AI员工

关系：

- 读取 AI员工总数、状态、当前任务、最近错误、今日完成任务。
- 汇总到老板驾驶舱。

禁止：

- 不创建 AI员工。
- 不启用/禁用 AI员工。
- 不修改员工权限。

### 6.3 Orchestrator

关系：

- 读取最近分析、任务链路、blocked 项。
- 提供跳转到 `orchestrator.html`。

禁止：

- 不修改 Orchestrator 规则。
- 不自动创建任务链。
- 不自动推进任务。

### 6.4 Execution Engine

关系：

- 读取队列、worker、运行状态、失败/超时日志。
- 展示执行风险和最近错误。

禁止：

- 不直接启动 execution。
- 不绕过 `APPROVED` 状态。
- 不绕过 `boss_confirm` / `security_audited`。

### 6.5 天盾 Deploy Center

关系：

- 读取部署历史、最近健康检查、服务状态。
- 提供跳转到 `deploy-center.html`。

禁止：

- 不触发部署。
- 不执行 docker/systemctl/shell。
- 不修改服务器配置。

### 6.6 天检 Test Center

关系：

- 从任务验收、失败任务、待测试事项中抽取展示。
- 后续可增加测试中心摘要。

禁止：

- 不自动标记测试通过。
- 不绕过天检验收。

## 7. 安全权限设计

### 7.1 角色访问

允许访问：

- `owner`
- `admin`
- `boss` 如系统角色归一后等价 owner

禁止访问：

- `viewer`
- 普通 AI员工
- 未登录用户

状态要求：

- 未登录：401
- 无权限：403
- Owner/Admin/Boss：200

### 7.2 写操作边界

Sprint31 页面默认只读。

允许：

- 查看
- 刷新
- 跳转已有中心

禁止：

- 自动执行任务
- 自动部署
- 自动修改权限
- 自动修改 Task Center 状态
- 自动修改 Orchestrator 规则
- 自动启动 Execution Engine
- 自动调用外部 API
- 自动调用 Shell

### 7.3 boss_confirm / security_audited

必须保留：

- `boss_confirm`
- `security_audited`

规则：

```text
低风险：
  可以展示为可处理
  不自动执行

中风险：
  必须等待 boss_confirm

高风险：
  必须 boss_confirm = true
  必须 security_audited = true
  否则 blocked
```

驾驶舱只展示这些状态，不直接改这些状态。

### 7.4 敏感字段过滤

API 和前端禁止返回或展示：

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

### 7.5 审计要求

如后续 Sprint31 增加任何写操作，必须：

- 独立设计。
- 天检验收。
- 天监安全审计。
- 天盾部署验证。

当前设计不包含写操作。

## 8. 开发拆分建议

### Task 1: 后端聚合 API

范围：

- 新增 `/api/ceo-dashboard/v2/*`
- 只读聚合现有数据。
- 不新增数据库表。

测试：

- 401
- 403
- 200
- 数据字段完整
- 敏感字段过滤

### Task 2: 前端驾驶舱 V2

范围：

- 升级 `frontend/index.html`
- 增加 V2 区域。
- 保留原入口。

测试：

- 页面加载
- API路径正确
- 空数据正常
- 错误提示正常

### Task 3: 安全边界检查

范围：

- 确认无危险按钮。
- 确认无自动执行入口。
- 确认无 shell/docker/git/systemctl 调用。

### Task 4: 回归验收

范围：

- Task Center
- AI员工
- Orchestrator
- Execution Engine
- Deploy Center
- 登录权限

## 9. 验收标准

Sprint31 通过条件：

- 老板驾驶舱 V2 页面正常加载。
- `/api/ceo-dashboard/v2/overview` 正常返回。
- 待处理事项、AI员工、任务、执行、部署状态正常展示。
- 未登录返回 401。
- Viewer / 普通员工返回 403。
- Owner/Admin/Boss 返回 200。
- 页面没有自动执行、自动部署、自动改权限按钮。
- 不展示敏感字段。
- 不修改 Task Center 状态流。
- 不修改 Orchestrator 规则。
- 不绕过 Execution Engine 审批链。
- 保留 `boss_confirm` 和 `security_audited` 安全边界。

## 10. 结论

Sprint31 应该优先建设老板驾驶舱 V2。

这是 v1.0 的第一块基础，因为它把现有分散模块聚合为老板每天可用的总入口，同时不破坏任何核心业务链路。

建议进入下一阶段：

- 天工：Sprint31 架构确认
- 天王：后端只读聚合 API
- 天颜：前端驾驶舱 V2
- 天检：测试验收
- 天监：安全审计
- 天盾：部署验证
