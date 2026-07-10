# Sprint62.14-A AI员工生态 API 服务架构设计 V1

## 1. 阶段边界

本阶段只做 API 架构设计。

禁止：

- 不写代码
- 不新增 API
- 不修改 backend router
- 不创建数据库
- 不创建 migration
- 不接真实业务
- 不接 OpenClaw
- 不接 n8n
- 不接 Execution Engine

目标：

设计 Tiantong AI AI员工生态统一 API 架构，覆盖 AI Workforce、Employee Detail、Skill Center、Knowledge OS、Memory、Growth、Audit、Organization、Task Center。

## 2. 现有 API 基础

当前项目已有相关 API：

| 模块 | 已有 API | 说明 |
| --- | --- | --- |
| AI Workforce | `GET /api/ai-workforce/overview` | Sprint62 只读聚合雏形 |
| AI员工 | `GET /api/ai-employees`、`GET /api/ai-employees/{employee_code}`、`GET /api/ai-employees/{employee_id}/detail` | 员工名册与详情 |
| Employee Workspace | `GET /api/employee-workspace/overview`、`GET /api/employee-workspace/employees/{employee_code}/home` | 员工工作台 |
| Skill / Capability | `GET /api/employee-capabilities/*`、`GET /api/sop-skill-center/*` | 能力与 SOP/Skill 雏形 |
| Knowledge OS | `GET /api/tiancang/*`、`GET /api/knowledge/*` | 天藏与知识中心 |
| Growth | `GET /api/employee-evolution/profile/{code}`、`GET /api/employee-evolution/growth`、`GET /api/employee-evolution/risk-events` | 成长与风险 |
| Audit | `GET /api/employee-activity-log/overview`、`GET /api/employee-activity-trace/*` | 日志和追溯 |
| Organization | `backend/employee_organization/*` 内部 builder | 还没有正式公开 API |
| Task Center | `GET /api/task-center/tasks`、`GET /api/task-center/tasks/{task_id}`、`GET /api/task-center/tasks/{task_id}/audit-logs` | 任务只读接口 |

设计原则：

- 不替换现有 API。
- 新生态 API 作为聚合层，优先复用现有只读 API 和内部 builder。
- 未来统一命名空间建议：

```text
/api/ai-employee-ecosystem/*
```

- V1 只设计 GET 只读接口。
- 高风险 POST/PATCH/DELETE 不进入 V1。

## 3. API 分层

```text
AI Employee Ecosystem API
├── 基础信息 API
├── 能力 API
├── 知识 API
├── 记忆 API
├── 成长 API
├── 审计 API
└── 权限 API
```

### 3.1 基础信息 API

用途：

- AI Workforce 总览。
- 员工详情页。
- Organization 基础归属。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/overview` | 生态总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees` | 员工列表 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}` | 员工生态详情 | 只读 |
| GET | `/api/ai-employee-ecosystem/departments` | 部门列表 | 只读 |
| GET | `/api/ai-employee-ecosystem/status` | 生态安全状态 | 只读 |

### 3.2 能力 API

用途：

- 技能能力、技能版本、技能风险、员工能力画像。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/capability` | 员工能力总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/skills` | 员工技能列表 | 只读 |
| GET | `/api/ai-employee-ecosystem/skills` | 技能资产列表 | 只读 |
| GET | `/api/ai-employee-ecosystem/skills/{skill_code}` | 技能详情 | 只读 |
| GET | `/api/ai-employee-ecosystem/skills/{skill_code}/versions` | 技能版本 | 只读 |

### 3.3 知识 API

用途：

- 员工可用知识、SOP、Prompt、案例。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/knowledge` | 员工知识资产 | 只读 |
| GET | `/api/ai-employee-ecosystem/knowledge/summary` | 知识总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/knowledge/sops` | SOP 摘要 | 只读 |
| GET | `/api/ai-employee-ecosystem/knowledge/prompts` | Prompt 摘要 | 只读、默认脱敏 |
| GET | `/api/ai-employee-ecosystem/knowledge/cases` | 案例摘要 | 只读 |

### 3.4 记忆 API

用途：

- 员工记忆、项目记忆、决策记忆、成功/失败案例。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/memory/overview` | 记忆总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/memory` | 员工记忆 | 只读 |
| GET | `/api/ai-employee-ecosystem/memory/success-cases` | 成功案例 | 只读 |
| GET | `/api/ai-employee-ecosystem/memory/failure-cases` | 失败案例 | 只读 |
| GET | `/api/ai-employee-ecosystem/memory/search` | 记忆搜索 | 只读 |

### 3.5 成长 API

用途：

- 成长评分、技能成长曲线、能力缺口、晋升建议。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/growth/overview` | 成长总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/growth/ranking` | 成长排名 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/growth` | 员工成长详情 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/skill-progress` | 技能成长 | 只读 |
| GET | `/api/ai-employee-ecosystem/growth/gaps` | 能力缺口 | 只读 |

### 3.6 审计 API

用途：

- 审计事件、风险事件、安全状态、审批链。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/audit/overview` | 审计总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/audit/events` | 审计事件 | 只读 |
| GET | `/api/ai-employee-ecosystem/audit/risks` | 风险事件 | 只读 |
| GET | `/api/ai-employee-ecosystem/audit/approvals` | 审批链 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/audit` | 员工审计 | 只读 |

### 3.7 权限 API

用途：

- 权限展示、组织范围、知识范围、技能范围、任务范围。

建议接口：

| Method | Path | 说明 | V1 |
| --- | --- | --- | --- |
| GET | `/api/ai-employee-ecosystem/permissions/overview` | 权限总览 | 只读 |
| GET | `/api/ai-employee-ecosystem/employees/{employee_code}/permissions` | 员工权限范围 | 只读 |
| GET | `/api/ai-employee-ecosystem/roles` | 角色列表 | 只读 |
| GET | `/api/ai-employee-ecosystem/departments/{department_id}/permissions` | 部门权限范围 | 只读 |

## 4. API 命名规范

### 4.1 路径规范

规则：

- 统一前缀：`/api/ai-employee-ecosystem`
- 资源使用复数：`employees`、`skills`、`memory`、`growth`、`audit`
- 员工主键优先使用 `employee_code`
- 动作型路径避免在 V1 出现，如 `execute`、`run`、`upgrade`、`grant`
- 只读接口全部使用 `GET`

推荐命名：

```text
GET /api/ai-employee-ecosystem/overview
GET /api/ai-employee-ecosystem/employees
GET /api/ai-employee-ecosystem/employees/{employee_code}
GET /api/ai-employee-ecosystem/employees/{employee_code}/capability
GET /api/ai-employee-ecosystem/employees/{employee_code}/knowledge
GET /api/ai-employee-ecosystem/employees/{employee_code}/memory
GET /api/ai-employee-ecosystem/employees/{employee_code}/growth
GET /api/ai-employee-ecosystem/employees/{employee_code}/audit
GET /api/ai-employee-ecosystem/employees/{employee_code}/permissions
```

### 4.2 Response 通用结构

```json
{
  "mode": "readonly",
  "request_id": "optional",
  "data": {},
  "meta": {
    "source_modules": [],
    "last_updated": null,
    "empty": false
  },
  "security": {
    "readonly": true,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

### 4.3 Error 通用结构

```json
{
  "mode": "readonly",
  "error": {
    "code": "not_found",
    "message": "员工不存在",
    "source_module": "ai_employees"
  },
  "security": {
    "readonly": true,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

### 4.4 空数据结构

```json
{
  "mode": "readonly",
  "data": {
    "items": []
  },
  "meta": {
    "empty": true,
    "empty_message": "当前未接入真实业务数据"
  },
  "security": {
    "readonly": true
  }
}
```

## 5. Request / Response JSON 示例

### 5.1 生态总览

Request：

```http
GET /api/ai-employee-ecosystem/overview
```

Response：

```json
{
  "mode": "readonly",
  "data": {
    "employees": {
      "total": 0,
      "working": 0,
      "idle": 0,
      "frozen": 0
    },
    "departments": [],
    "skills": {
      "total": 0,
      "high_risk": 0
    },
    "knowledge": {
      "articles": 0,
      "sop": 0,
      "prompt": 0
    },
    "memory": {
      "available": false,
      "success_cases": 0,
      "failure_cases": 0
    },
    "growth": {
      "available": false,
      "average_score": null
    },
    "audit": {
      "risk_count": 0,
      "pending_approvals": 0
    },
    "tasks": {
      "total": 0,
      "running": 0,
      "blocked": 0
    }
  },
  "security": {
    "readonly": true,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

### 5.2 员工详情

Request：

```http
GET /api/ai-employee-ecosystem/employees/tianwang
```

Response：

```json
{
  "mode": "readonly",
  "data": {
    "employee": {
      "employee_code": "tianwang",
      "employee_name": "天王",
      "department": "研发交付军团",
      "role": "后端 API、数据库模型、迁移、权限和测试",
      "status": "active",
      "risk_level": "medium"
    },
    "capability": {
      "skill_count": 0,
      "knowledge_count": 0,
      "capability_summary": null
    },
    "tasks": {
      "current": null,
      "history_count": 0
    },
    "growth": {
      "available": false,
      "score": null
    },
    "audit": {
      "risk_count": 0,
      "latest_event": null
    }
  },
  "security": {
    "readonly": true,
    "can_execute": false,
    "can_modify_permission": false,
    "high_risk_requires": {
      "boss_confirm": true,
      "security_audited": true
    }
  }
}
```

### 5.3 员工能力

Request：

```http
GET /api/ai-employee-ecosystem/employees/tianwang/capability
```

Response：

```json
{
  "mode": "readonly",
  "data": {
    "employee_code": "tianwang",
    "skills": [],
    "skill_versions": [],
    "knowledge_assets": {
      "sop": 0,
      "prompt": 0,
      "cases": 0
    },
    "risk": {
      "level": "low",
      "notes": []
    }
  },
  "security": {
    "readonly": true,
    "auto_install_skill": false,
    "auto_upgrade_skill": false,
    "auto_execute_skill": false
  }
}
```

### 5.4 记忆搜索

Request：

```http
GET /api/ai-employee-ecosystem/memory/search?keyword=复盘&employee_code=tianwang
```

Response：

```json
{
  "mode": "readonly",
  "data": {
    "items": [],
    "filters": {
      "keyword": "复盘",
      "employee_code": "tianwang"
    }
  },
  "meta": {
    "empty": true,
    "empty_message": "当前未接入真实记忆数据"
  },
  "security": {
    "readonly": true,
    "auto_learning_applied": false
  }
}
```

### 5.5 审计事件

Request：

```http
GET /api/ai-employee-ecosystem/audit/events?risk_level=high
```

Response：

```json
{
  "mode": "readonly",
  "data": {
    "items": [],
    "risk_level": "high"
  },
  "security": {
    "readonly": true,
    "auto_fix": false,
    "auto_block_employee": false,
    "auto_modify_permission": false
  }
}
```

## 6. 前端页面调用关系

### 6.1 AI Workforce

页面：

```text
frontend/ai-workforce.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/overview`
- `GET /api/ai-employee-ecosystem/employees`
- `GET /api/ai-employee-ecosystem/departments`
- `GET /api/ai-employee-ecosystem/audit/risks`

### 6.2 Employee Detail

页面：

```text
frontend/ai-employee-detail.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/employees/{employee_code}`
- `GET /api/ai-employee-ecosystem/employees/{employee_code}/capability`
- `GET /api/ai-employee-ecosystem/employees/{employee_code}/knowledge`
- `GET /api/ai-employee-ecosystem/employees/{employee_code}/memory`
- `GET /api/ai-employee-ecosystem/employees/{employee_code}/growth`
- `GET /api/ai-employee-ecosystem/employees/{employee_code}/audit`

### 6.3 Skill Center

页面：

```text
frontend/skill-center.html
frontend/skill-detail.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/skills`
- `GET /api/ai-employee-ecosystem/skills/{skill_code}`
- `GET /api/ai-employee-ecosystem/skills/{skill_code}/versions`
- `GET /api/ai-employee-ecosystem/audit/events?source_module=skill_center`

### 6.4 Memory

页面：

```text
frontend/memory-center.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/memory/overview`
- `GET /api/ai-employee-ecosystem/memory/search`
- `GET /api/ai-employee-ecosystem/memory/success-cases`
- `GET /api/ai-employee-ecosystem/memory/failure-cases`

### 6.5 Growth

页面：

```text
frontend/growth-center.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/growth/overview`
- `GET /api/ai-employee-ecosystem/growth/ranking`
- `GET /api/ai-employee-ecosystem/growth/gaps`
- `GET /api/ai-employee-ecosystem/audit/risks?source_module=growth`

### 6.6 Audit

页面：

```text
frontend/audit-center.html
```

建议调用：

- `GET /api/ai-employee-ecosystem/audit/overview`
- `GET /api/ai-employee-ecosystem/audit/events`
- `GET /api/ai-employee-ecosystem/audit/risks`
- `GET /api/ai-employee-ecosystem/audit/approvals`
- `GET /api/ai-employee-ecosystem/status`

## 7. 安全设计

### 7.1 V1 禁止接口

V1 不设计以下接口：

```text
POST /api/ai-employee-ecosystem/employees
POST /api/ai-employee-ecosystem/employees/{employee_code}/upgrade
POST /api/ai-employee-ecosystem/employees/{employee_code}/skills/install
POST /api/ai-employee-ecosystem/employees/{employee_code}/permissions/grant
POST /api/ai-employee-ecosystem/tasks/create
POST /api/ai-employee-ecosystem/tasks/{task_id}/execute
PATCH /api/ai-employee-ecosystem/permissions/*
DELETE /api/ai-employee-ecosystem/*
```

禁止：

- 自动执行接口
- 自动升级接口
- 自动修改权限接口
- 自动安装技能接口
- 自动发布知识接口
- 自动学习应用接口

### 7.2 高风险接口要求

未来如进入 V3/V4 人工审批阶段，所有高风险接口必须包含：

```json
{
  "boss_confirm": true,
  "security_audited": true,
  "request_reason": "string",
  "risk_review_id": "string",
  "approval_id": "string"
}
```

即使审批通过：

- 仍不得自动执行任务。
- 仍不得绕过 Task Center。
- 仍不得直接进入 Execution Engine。

### 7.3 API 安全状态字段

所有生态 API Response 必须包含：

```json
{
  "security": {
    "readonly": true,
    "auto_execute_enabled": false,
    "auto_upgrade_enabled": false,
    "auto_permission_modify_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

## 8. V1 / V2 / V3 API 演进路线

### V1：只读聚合 API 设计

目标：

- 设计统一命名空间。
- 定义 Response 格式。
- 定义前端调用关系。
- 禁止写入、执行、权限修改。

本阶段只输出文档，不实现。

### V2：只读 API 实现

目标：

- 实现 `/api/ai-employee-ecosystem/overview`。
- 实现员工详情、能力、知识、成长、审计的只读聚合。
- 复用现有表和 API。

限制：

- 不创建新数据库。
- 不调用 Execution Engine。
- 不修改 Task Center 状态。

### V3：人工审批 API 草稿

目标：

- 设计审批申请草稿接口。
- 支持技能变更申请、知识发布申请、成长建议申请、权限变更申请。

限制：

- 只创建申请草稿。
- 不自动执行申请结果。
- 必须进入 Audit Center。

## 9. 验收结论

Sprint62.14-A 只完成 AI员工生态 API 服务架构设计 V1。

验收项：

- 已设计基础信息 API、能力 API、知识 API、记忆 API、成长 API、审计 API、权限 API。
- 已设计 API 命名规范。
- 已提供 Request / Response JSON 示例。
- 已设计 AI Workforce、Employee Detail、Skill Center、Memory、Growth、Audit 前端调用关系。
- 已规划 V1/V2/V3 API 演进路线。
- 已明确所有高风险接口必须 `boss_confirm=true` 与 `security_audited=true`。
- 已明确禁止自动执行接口、自动升级接口、自动修改权限接口。

未执行事项：

- 未写代码。
- 未新增 API。
- 未修改 backend router。
- 未创建数据库。
- 未创建 migration。
- 未接真实业务。
- 未接 OpenClaw。
- 未接 n8n。
- 未接 Execution Engine。
