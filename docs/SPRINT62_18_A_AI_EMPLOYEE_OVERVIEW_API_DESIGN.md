# Sprint62.18-A AI Employee Ecosystem Overview API 设计

## 1. 阶段边界

本阶段只做 API 架构设计，不写代码。

禁止：

- 不新增 API 实现。
- 不修改后端 router。
- 不修改已有业务逻辑。
- 不修改数据库。
- 不创建 migration。
- 不接 Execution Engine。
- 不接 OpenClaw。
- 不接 n8n。
- 不新增执行能力。

目标接口：

```http
GET /api/ai-employee-ecosystem/overview
```

定位：

AI Employee Ecosystem Overview API 是 AI员工生态驾驶舱的统一只读聚合接口，面向 `frontend/ai-employee-dashboard.html` 提供员工、能力、Skill、Memory、Growth、Audit、Meeting、Task Center 的统一状态。

## 2. 设计原则

1. 只读聚合。
2. 不创建、修改、删除任何业务数据。
3. 不调用任何执行接口。
4. 不改变 Task Center 状态。
5. 不改变员工、技能、权限、成长、记忆状态。
6. 单模块失败不影响整体返回。
7. 无数据时返回空状态，不生成假数据。
8. 明确安全标识：

```json
{
  "readonly": true,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false,
  "auto_execute": false
}
```

## 3. API 概览

```http
GET /api/ai-employee-ecosystem/overview
```

认证：

- 复用现有登录态。
- 建议 owner / admin 可查看全量。
- viewer 只读查看允许范围。
- unauthorized 返回 401。

响应模式：

```json
{
  "mode": "readonly",
  "version": "Sprint62.18-A-design",
  "generated_at": "2026-07-10T00:00:00Z",
  "employees": {},
  "capability": {},
  "skill": {},
  "memory": {},
  "growth": {},
  "audit": {},
  "meeting": {},
  "task": {},
  "centers": [],
  "empty_state": {},
  "security": {},
  "data_sources": [],
  "errors": []
}
```

## 4. 返回 JSON 结构设计

### 4.1 总体结构

```json
{
  "mode": "readonly",
  "version": "ai_employee_ecosystem_overview_v1",
  "generated_at": "2026-07-10T00:00:00Z",
  "employees": {
    "total": 0,
    "working": 0,
    "idle": 0,
    "frozen": 0,
    "offline": 0,
    "departments": []
  },
  "capability": {
    "available": false,
    "configured_capabilities": 0,
    "missing_capability_count": 0,
    "average_maturity_level": null,
    "average_success_rate": null
  },
  "skill": {
    "total": 0,
    "enabled": 0,
    "reviewing": 0,
    "high_risk": 0,
    "sop_count": 0,
    "prompt_count": 0
  },
  "memory": {
    "total": 0,
    "last_updated": null,
    "types": {
      "Experience": 0,
      "DecisionHistory": 0,
      "LearningRecord": 0,
      "SuccessCase": 0,
      "FailureCase": 0
    }
  },
  "growth": {
    "available": false,
    "growth_records": 0,
    "growth_level": null,
    "skill_trend": null,
    "recent_growth_records": 0
  },
  "audit": {
    "risk_count": 0,
    "high_risk_count": 0,
    "pending_boss_confirm": 0,
    "security_audited_required": 0
  },
  "meeting": {
    "available": false,
    "meeting_count": 0,
    "draft_count": 0,
    "participant_count": 0,
    "status": "not_connected"
  },
  "task": {
    "total": 0,
    "running": 0,
    "pending": 0,
    "blocked": 0,
    "review_pending": 0
  },
  "centers": [
    {
      "key": "ai_workforce",
      "name": "AI Workforce Center",
      "status": "empty",
      "count": 0,
      "risk_level": "low",
      "href": "/ai-workforce.html"
    }
  ],
  "empty_state": {
    "no_real_business_data": true,
    "message": "当前未接入真实业务数据"
  },
  "security": {
    "readonly": true,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false,
    "auto_execute": false,
    "high_risk_requires": {
      "boss_confirm": true,
      "security_audited": true
    }
  },
  "data_sources": [
    "ai_workforce",
    "employee_capabilities",
    "sop_skill_center",
    "task_center",
    "tiancang",
    "employee_evolution"
  ],
  "errors": []
}
```

## 5. 字段说明

### 5.1 `employees`

来源优先级：

1. 复用 `GET /api/ai-workforce/overview` 逻辑。
2. 读取现有 AI员工名册数据。
3. 读取员工卡片状态。

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | number | AI员工总数 |
| `working` | number | 工作中员工 |
| `idle` | number | 空闲员工 |
| `frozen` | number | 冻结员工 |
| `offline` | number | 离线或未知员工 |
| `departments` | array | 部门分布 |

### 5.2 `capability`

来源：

```http
GET /api/employee-capabilities/overview
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `available` | boolean | 能力中心数据是否可用 |
| `configured_capabilities` | number | 已配置能力数量 |
| `missing_capability_count` | number | 缺失能力数量 |
| `average_maturity_level` | number/null | 平均成熟度 |
| `average_success_rate` | number/null | 平均成功率 |

### 5.3 `skill`

来源：

```http
GET /api/sop-skill-center/skills
GET /api/sop-skill-center/overview
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | number | Skill 总数 |
| `enabled` | number | 已启用或已批准技能 |
| `reviewing` | number | 审核中技能 |
| `high_risk` | number | high / critical 风险技能 |
| `sop_count` | number | SOP 数量 |
| `prompt_count` | number | Prompt 数量 |

### 5.4 `memory`

来源：

```http
GET /api/task-center/tasks
GET /api/tiancang/articles/search
GET /api/tiancang/sops
GET /api/tiancang/prompts
GET /api/tiancang/bugs
```

V1 记忆类型映射：

| 记忆类型 | 映射来源 |
| --- | --- |
| `Experience` | Task Center 任务记录 |
| `DecisionHistory` | 天藏知识文章 / 决策类记录 |
| `LearningRecord` | SOP / Prompt |
| `SuccessCase` | accepted / audited / summarized 任务 |
| `FailureCase` | rejected 任务 / Bug 案例 |

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | number | 记忆总数 |
| `last_updated` | string/null | 最近更新时间 |
| `types` | object | 分类统计 |

### 5.5 `growth`

来源：

```http
GET /api/employee-evolution/growth
```

明确禁止：

```http
POST /api/employee-evolution/analyze
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `available` | boolean | Growth 数据是否可用 |
| `growth_records` | number | 成长记录数 |
| `growth_level` | string/null | 平均评分推导等级 |
| `skill_trend` | string/null | up / stable / down |
| `recent_growth_records` | number | 最近成长记录数量 |

### 5.6 `audit`

来源：

```http
GET /api/employee-evolution/risk-events
GET /api/task-center/tasks
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `risk_count` | number | 风险事件数量 |
| `high_risk_count` | number | high / critical 风险数量 |
| `pending_boss_confirm` | number | 待 Boss 确认事项 |
| `security_audited_required` | number | 需要安全审核事项 |

### 5.7 `meeting`

V1 状态：

- 尚无统一会议 API。
- 返回安全空状态。

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `available` | boolean | 会议中心是否已接入 |
| `meeting_count` | number | 会议数量 |
| `draft_count` | number | 方案草稿数量 |
| `participant_count` | number | 参与员工数 |
| `status` | string | `not_connected` / `empty` / `available` |

### 5.8 `task`

来源：

```http
GET /api/task-center/tasks
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | number | 任务总数 |
| `running` | number | running 任务 |
| `pending` | number | created / split / assigned |
| `blocked` | number | rejected / blocked |
| `review_pending` | number | result_submitted |

## 6. Center 状态卡设计

`centers` 用于前端统一渲染八大中心状态。

```json
{
  "key": "growth",
  "name": "Growth Center",
  "status": "empty",
  "description": "AI员工成长记录与能力变化",
  "count": 0,
  "last_updated": null,
  "risk_level": "low",
  "href": "/ai-employee-growth.html"
}
```

状态枚举：

| 状态 | 含义 |
| --- | --- |
| `available` | 数据可用 |
| `partial` | 部分数据可用 |
| `empty` | 暂无数据 |
| `unavailable` | 接口异常 |
| `not_connected` | V1 尚未接入 |

风险等级：

```text
low / medium / high / critical
```

## 7. 错误与降级设计

原则：

- 聚合接口不能因为单个模块失败整体 500。
- 单模块失败写入 `errors`。
- 失败模块返回安全空状态。

错误结构：

```json
{
  "module": "growth",
  "source": "/api/employee-evolution/growth",
  "status": "unavailable",
  "message": "当前数据不可用"
}
```

模块降级规则：

| 模块 | 失败结果 |
| --- | --- |
| employees | 员工统计为 0，状态 `unavailable` |
| capability | `available=false` |
| skill | 技能统计为 0 |
| memory | 记忆统计为 0 |
| growth | `available=false` |
| audit | 风险统计为 0 |
| meeting | `not_connected` |
| task | 任务统计为 0 |

## 8. 安全设计

接口必须返回：

```json
{
  "security": {
    "readonly": true,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false,
    "auto_execute": false,
    "high_risk_requires": {
      "boss_confirm": true,
      "security_audited": true
    }
  }
}
```

接口禁止：

- 创建任务。
- 修改任务。
- 修改员工。
- 修改技能。
- 修改记忆。
- 修改成长评分。
- 修改权限。
- 调用 Execution Engine。
- 接入 OpenClaw。
- 接入 n8n。
- 调用外部平台。
- 自动执行任何动作。

## 9. 权限设计

V1 建议权限：

| 角色 | 行为 |
| --- | --- |
| owner | 查看完整生态摘要 |
| admin | 查看管理范围内摘要 |
| viewer | 查看允许范围内只读摘要 |
| unauthorized | 401 |

权限只影响可见范围，不触发任何状态修改。

## 10. 数据来源清单

V1 复用现有只读数据来源：

| 目标模块 | 建议来源 |
| --- | --- |
| employees | `GET /api/ai-workforce/overview` 既有聚合逻辑 |
| capability | `GET /api/employee-capabilities/overview` |
| skill | `GET /api/sop-skill-center/skills`, `GET /api/sop-skill-center/overview` |
| memory | `GET /api/task-center/tasks`, `GET /api/tiancang/articles/search`, `GET /api/tiancang/sops`, `GET /api/tiancang/prompts`, `GET /api/tiancang/bugs` |
| growth | `GET /api/employee-evolution/growth` |
| audit | `GET /api/employee-evolution/risk-events`, `GET /api/task-center/tasks` |
| meeting | V1 安全空状态 |
| task | `GET /api/task-center/tasks` |

实现阶段可选择直接复用服务函数或在 router 内只读查询数据库。无论采用哪种方式，都禁止调用 POST/PATCH/DELETE 接口。

## 11. 测试方案

建议测试文件：

```text
tests/test_ai_employee_ecosystem_overview.py
```

测试点：

1. `GET /api/ai-employee-ecosystem/overview` 返回 200。
2. 返回 `mode=readonly`。
3. 返回 `security.readonly=true`。
4. 返回 `execution_engine_called=false`。
5. 返回 `openclaw_connected=false`。
6. 返回 `n8n_connected=false`。
7. 返回 employees / capability / skill / memory / growth / audit / meeting / task 字段。
8. 无数据时返回空状态。
9. 不创建任务。
10. 不修改 Task Center 状态。
11. 不调用 `/api/employee-evolution/analyze`。
12. 不包含敏感信息字段。

静态安全测试：

- 搜索 router 实现中不得出现：
  - `/api/execution`
  - `/api/brain/start`
  - `OpenClaw`
  - `n8n`
  - `method="POST"` 指向执行或分析接口

## 12. 后续开发拆分建议

### Sprint62.18-B 后端只读 API 开发

新增文件建议：

```text
backend/routers/ai_employee_ecosystem.py
tests/test_ai_employee_ecosystem_overview.py
```

允许改动：

- `backend/main.py` 仅注册 router。

禁止：

- 修改数据库。
- 创建 migration。
- 修改已有业务流程。

### Sprint62.18-C Dashboard 页面开发

新增文件建议：

```text
frontend/ai-employee-dashboard.html
tests/test_ai_employee_dashboard.py
```

接入：

```http
GET /api/ai-employee-ecosystem/overview
```

### Sprint62.18-D 安全验收

验收：

- API 只读。
- 页面只读。
- 无执行入口。
- 无 OpenClaw。
- 无 n8n。
- 无 Execution Engine。
- 无数据库变化。

## 13. 验收标准

设计阶段通过条件：

- 已定义统一 Overview API。
- 已定义返回 JSON 结构。
- 已覆盖员工、能力、Skill、Memory、Growth、Audit、Meeting、Task。
- 已明确数据来源。
- 已明确安全边界。
- 已明确降级策略。
- 未写代码。
- 未修改数据库。
- 未创建 migration。
- 未接 Execution Engine / OpenClaw / n8n。
