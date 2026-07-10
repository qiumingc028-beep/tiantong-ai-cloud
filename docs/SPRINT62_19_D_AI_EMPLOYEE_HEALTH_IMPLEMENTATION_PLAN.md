# Sprint62.19-D AI Employee Health 后端实现规划

文档名称：《AI Employee Health 后端实现规划 V1》

阶段：Sprint62.19-D

状态：规划完成，等待确认

## 1. 阶段边界

本阶段只做实现规划，不写代码。

禁止事项：

- 不修改后端代码
- 不修改前端代码
- 不创建数据库
- 不创建 migration
- 不修改现有业务逻辑
- 不接 OpenClaw
- 不接 n8n
- 不调用 Execution Engine
- 不自动修复
- 不自动重启
- 不自动执行任务
- 不自动修改权限

目标接口规划：

```http
GET /api/ai-employee-health/overview
```

定位：AI员工生态健康状态只读聚合 API。

## 2. 当前项目已有数据接口分析

### 2.1 AI员工生态总览接口

已有接口：

```http
GET /api/ai-employee-ecosystem/overview
```

现有文件：

```text
backend/routers/ai_employee_ecosystem.py
backend/services/ai_employee_ecosystem_overview.py
tests/test_ai_employee_ecosystem_overview.py
```

当前能力：

- 返回 `mode=readonly`
- 聚合员工状态
- 聚合能力状态
- 聚合 Skill 状态
- 聚合 Memory 状态
- 聚合 Growth 状态
- 聚合 Audit 风险
- 聚合 Meeting Room 占位状态
- 聚合 Task Center 状态
- 返回 `centers`
- 返回 `empty_state`
- 返回 `security`
- 返回 `errors`

可复用价值：

- Health API 可直接复用该 service 的结果作为主要数据源
- 避免重复查询数据库
- 避免新增业务逻辑
- 避免影响 AI Workforce / Task Center / Skill Center 现有接口

### 2.2 AI Workforce 接口

已有接口：

```http
GET /api/ai-workforce/overview
```

现有文件：

```text
backend/routers/ai_workforce.py
tests/test_ai_workforce.py
```

当前能力：

- 员工总数
- working / idle / frozen
- 部门分布
- 技能数量
- 知识资产数量
- 任务状态
- 风险数量
- 员工卡片
- 只读安全字段

可复用价值：

- 作为 Health API 的补充参考
- Sprint62.19-D 实现时不建议直接重复调用该 HTTP 接口
- 如需员工状态细节，优先从 `ai_employee_ecosystem_overview` 已聚合的 `employees` 字段读取

### 2.3 系统健康接口

已有接口：

```http
GET /api/health
GET /api/ready
```

现有能力：

- Database 健康状态
- Redis 健康状态
- Worker 心跳状态
- 系统时间
- 服务 ready 状态

现有函数：

```text
backend/main.py
├── build_health_payload()
├── health()
└── ready()
```

可复用价值：

- Health API 可在 service 中复用 `build_health_payload()` 的结果
- 不需要新增系统健康检查逻辑
- 不需要增加外部依赖

注意：

- 不能为了 Health Center 自动重启 worker
- 不能为了 Health Center 自动修复 Redis / Database
- 只能读取并展示状态

### 2.4 Task Center 数据

已有来源：

```text
backend/models.py: TaskCenterTask
backend/routers/task_center.py
backend/services/ai_employee_ecosystem_overview.py: collect_task_stats()
```

当前 Health 规划使用方式：

- 不直接修改 Task Center
- 不直接调用执行流程
- 复用生态 Overview 中的 `task` 聚合字段

### 2.5 Skill / Knowledge / Memory / Growth / Audit 数据

已有来源：

```text
backend/routers/sop_skill_center.py
backend/routers/employee_capabilities.py
backend/evolution_models.py
backend/models.py
backend/services/ai_employee_ecosystem_overview.py
```

可复用字段：

- `skill.total`
- `skill.enabled`
- `skill.reviewing`
- `skill.high_risk`
- `memory.total`
- `memory.last_updated`
- `memory.types`
- `growth.available`
- `growth.growth_records`
- `audit.risk_count`
- `audit.high_risk_count`
- `audit.pending_boss_confirm`
- `audit.security_audited_required`

## 3. 可复用 Service 分析

### 3.1 主要复用 Service

```text
backend/services/ai_employee_ecosystem_overview.py
```

建议复用函数：

```text
build_ai_employee_ecosystem_overview(db, user)
```

复用方式：

```text
AI Employee Health Service
        ↓
build_ai_employee_ecosystem_overview(db, user)
        ↓
转换为 HealthStatus / ModuleHealth / APIHealth / DataFreshness / AlertRecord
```

优势：

- 已有只读安全测试
- 已有权限用户对象
- 已有模块聚合结果
- 已有错误降级机制 `safe_collect`
- 避免重复写 SQL

### 3.2 可复用系统健康函数

```text
backend/main.py: build_health_payload()
```

建议复用内容：

- database status
- redis status
- worker status
- service time

注意：

- 如果直接从 service import `backend.main.build_health_payload` 可能出现依赖方向不理想
- 更稳妥的后续实现选择：
  - V1 可在 router 层调用现有函数
  - 或先将 health check helper 后续迁出到 `backend/services/system_health.py`
  - Sprint62.19-D 实现阶段如果要求最小修改，可先不抽离，避免重构

规划建议：

- Sprint62.19-D 后续开发优先最小改动
- 不做健康检查函数重构
- 在 Health Service 内只生成 APIHealth 的结构性状态
- 系统 `/api/health` 与 `/api/ready` 可作为已存在 API 状态列出

### 3.3 不复用的模块

以下模块不得被 Health API 调用：

- `backend/execution_engine.py`
- `backend/routers/execution_engine.py`
- `backend/brain_execution/*`
- `backend/employee_execution/*`
- OpenClaw 相关未来入口
- n8n 相关未来入口

原因：

- Health Center 只做状态展示
- 不允许触发执行、队列、worker、外部动作

## 4. 是否需要新增 Router

结论：需要新增独立 Router。

建议新增：

```text
backend/routers/ai_employee_health.py
```

理由：

- Health Center 是独立产品模块
- 避免污染 `ai_employee_ecosystem` router
- 便于单独做权限、安全、测试
- 与前端 `/api/ai-employee-health/overview` 数据来源保持一致

Router 规划：

```text
APIRouter(prefix="/api/ai-employee-health")
└── GET /overview
```

权限建议：

- 沿用 `ai_employee_ecosystem` 只读权限策略
- `owner`：允许
- `admin`：允许
- `viewer`：允许
- `boss`：建议允许，因 Health Center 是 Boss 驾驶舱型只读页面
- `operator`：默认禁止

注意：

- 当前 `ai_employee_ecosystem` 测试允许 `boss_headers` 访问，但 router 常量只包含 owner/admin/viewer，需在实现前以实际测试结果为准
- 为避免引入权限争议，Sprint62.19-D 后续实现应明确并测试 `boss` 是否可访问

## 5. 是否需要新增 Service

结论：需要新增独立 Service。

建议新增：

```text
backend/services/ai_employee_health_overview.py
```

Service 职责：

```text
build_ai_employee_health_overview(db, user)
├── read ecosystem overview
├── build module health
├── build api health
├── build data freshness
├── compute health score
├── build alerts
└── build security payload
```

Service 输入：

- SQLAlchemy Session
- 当前 User

Service 输出：

- HealthStatus dict

禁止：

- `db.add`
- `db.delete`
- `db.commit`
- 创建 TaskCenterTask
- 调用执行类 router/service
- 调用外部 API

## 6. 是否需要新增数据库

结论：不需要。

原因：

- Health API 是实时只读聚合
- 所需数据已由现有表或现有 service 提供
- AlertRecord 在 V1 中为响应内派生对象，不落库
- HealthScore 在 V1 中为响应内计算结果，不落库
- APIHealth 在 V1 中为响应内结构化状态，不落库

## 7. 是否需要 migration

结论：不需要。

禁止创建：

```text
alembic/versions/*
```

禁止修改：

```text
backend/models.py
backend/evolution_models.py
```

后续如果 V2 需要长期健康记录，可另行设计：

- HealthSnapshot
- HealthAlertHistory
- ModuleHealthHistory

但不属于 Sprint62.19-D / V1 范围。

## 8. 实现文件规划

后续确认开发后，建议修改文件：

```text
backend/routers/ai_employee_health.py
backend/services/ai_employee_health_overview.py
backend/main.py
tests/test_ai_employee_health.py
```

修改说明：

| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/routers/ai_employee_health.py` | 新增 | Health API router |
| `backend/services/ai_employee_health_overview.py` | 新增 | 只读健康聚合 service |
| `backend/main.py` | 最小修改 | 注册 router |
| `tests/test_ai_employee_health.py` | 新增 | API、安全、只读测试 |

不修改：

- `backend/models.py`
- `alembic/`
- `backend/routers/task_center.py`
- `backend/routers/execution_engine.py`
- `backend/execution_engine.py`
- 现有员工、技能、成长、审计核心流程

## 9. API 返回结构规划

接口：

```http
GET /api/ai-employee-health/overview
```

核心字段：

```json
{
  "mode": "readonly",
  "status": "healthy",
  "overall_score": 90,
  "generated_at": "2026-07-10T00:00:00+00:00",
  "alert_count": 0,
  "modules": [],
  "apis": [],
  "freshness": [],
  "score": {},
  "alerts": [],
  "security": {
    "readonly": true,
    "auto_repair_enabled": false,
    "auto_execute_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false,
    "permission_mutation_enabled": false,
    "task_mutation_enabled": false
  },
  "data_sources": [
    "ai_employee_ecosystem_overview",
    "system_health",
    "system_ready"
  ]
}
```

员工数量状态：

- 可从 `modules` 的 `ai_workforce` 表达总数
- 可额外增加 `employees` 字段以便前端直接展示：

```json
{
  "employees": {
    "total": 0,
    "working": 0,
    "idle": 0,
    "frozen": 0,
    "offline": 0
  }
}
```

规划建议：

- 为满足 Sprint62.19-C 前端“AI员工数量状态”展示，建议后端返回顶层 `employees`
- 该字段从 ecosystem overview 原样映射，不增加新查询

## 10. 模块映射规划

从 `build_ai_employee_ecosystem_overview` 到 Health 模型的映射：

| Health module_key | 数据来源 | count | status |
|---|---|---:|---|
| `ai_workforce` | `employees` | `employees.total` | total > 0 为 connected，否则 empty |
| `capability` | `capability` | `configured_capabilities` | available 为 connected，否则 empty |
| `skill_center` | `skill` | `skill.total` | total > 0 为 connected，否则 empty |
| `memory_center` | `memory` | `memory.total` | total > 0 为 connected，否则 empty |
| `growth_center` | `growth` | `growth.growth_records` | available 为 connected，否则 empty |
| `audit_center` | `audit` | `audit.risk_count` | high_risk_count > 0 为 degraded，否则 connected/empty |
| `meeting_room` | `meeting` | `meeting.meeting_count` | V1 not_connected |
| `task_center` | `task` | `task.total` | blocked > 0 为 degraded，否则 connected/empty |

风险等级映射：

- high risk count > 0：`high`
- blocked task > 0：`medium`
- no data：`unknown` 或 `low`
- normal：`low`

## 11. APIHealth 规划

V1 API 状态项：

```text
/api/ai-employee-health/overview
/api/ai-employee-ecosystem/overview
/api/health
/api/ready
```

实现建议：

- 不通过 HTTP 调用自己
- `/api/ai-employee-health/overview` 标记为当前响应生成成功
- `/api/ai-employee-ecosystem/overview` 标记为 service 调用成功或 degraded
- `/api/health` 与 `/api/ready` 可根据 `build_health_payload` 判断
- 不做网络探测
- 不做外部探测

## 12. DataFreshness 规划

可直接映射更新时间：

- `memory.last_updated`
- `generated_at`
- system health `time`

暂时无更新时间的模块：

- Skill Center
- Capability
- Meeting Room

处理规则：

- 无数据：`empty`
- 未接入：`not_connected`
- 有错误：`unavailable`
- 有更新时间但超过阈值：`stale`
- 正常：`fresh`

V1 不要求精确追踪所有模块更新时间，优先稳定展示。

## 13. HealthScore 规划

建议函数：

```text
compute_health_score(modules, apis, freshness, security, alerts)
```

评分组成：

```text
overall_score =
  module_score * 0.35
+ api_score * 0.25
+ freshness_score * 0.20
+ security_score * 0.20
- alert_penalty
```

边界规则：

- 空数据不等同系统错误
- `not_connected` 在 V1 不直接判为高风险
- `security` 异常必须高权重扣分
- Execution Engine / OpenClaw / n8n 一旦为 true，生成 high alert

## 14. AlertRecord 规划

异常来源：

- ecosystem overview `errors`
- APIHealth unavailable
- ModuleHealth unavailable
- DataFreshness stale
- Audit high risk
- Task blocked
- Security boundary violation

V1 异常行为：

- 只返回 alert
- `action_available=false`
- 高风险标记：

```json
{
  "requires_boss_confirm": true,
  "security_audited_required": true
}
```

禁止：

- 自动处理异常
- 自动创建整改任务
- 自动修复模块

## 15. 权限方案

建议沿用只读权限。

允许：

- owner
- admin
- viewer
- boss

禁止：

- operator
- 未登录用户
- inactive 用户

测试必须覆盖：

- 未登录：401
- owner：200
- admin：200
- viewer：200
- boss：200
- operator：403

如果当前项目权限策略决定 viewer 不可查看健康中心，则实现前需要明确修改本规划；否则建议 Health Center 作为只读状态页允许 viewer 查看。

## 16. 测试方案

新增测试文件：

```text
tests/test_ai_employee_health.py
```

### 16.1 API 登录与权限测试

测试：

- 未登录返回 401
- owner/admin/viewer/boss 返回 200
- operator 返回 403

### 16.2 API 返回结构测试

断言字段：

- `mode`
- `status`
- `overall_score`
- `generated_at`
- `alert_count`
- `modules`
- `apis`
- `freshness`
- `score`
- `alerts`
- `security`
- `data_sources`

### 16.3 只读安全字段测试

断言：

- `security.readonly is True`
- `security.auto_repair_enabled is False`
- `security.auto_execute_enabled is False`
- `security.execution_engine_called is False`
- `security.openclaw_connected is False`
- `security.n8n_connected is False`
- `security.permission_mutation_enabled is False`
- `security.task_mutation_enabled is False`

### 16.4 数据聚合测试

通过测试数据库插入只读数据：

- AiEmployee
- TaskCenterTask
- RiskEvent
- KnowledgeArticle
- SopLibrary
- PromptLibrary
- EmployeeGrowth

验证：

- employees 状态正确
- modules 数量正确
- task blocked 生成 degraded 或 alert
- audit high risk 生成 high risk
- empty data 不报错

### 16.5 只读不变更测试

请求前后对比：

- TaskCenterTask 数量不变
- User role 不变
- AiEmployee 数量不变
- RiskEvent 数量不变

### 16.6 静态安全测试

读取新增 router/service 文件，断言不包含：

- `OpenClaw`
- `n8n`
- `/api/execution`
- `/api/brain/start`
- `ExecutionEngine`
- `TaskCenterTask(`
- `.add(`
- `.delete(`
- `.commit(`
- `requests.`
- `httpx.`

说明：

- 如果只在安全字段字符串中出现 `openclaw_connected` / `n8n_connected`，测试应允许这些安全字段
- 禁止的是连接、调用、执行入口

### 16.7 Docker Python 3.12 验证

后续开发验收建议执行：

```text
pytest tests/test_ai_employee_health.py
pytest tests/test_ai_employee_ecosystem_overview.py
pytest tests/test_ai_workforce.py
pytest
```

## 17. 风险点

### 17.1 权限策略不一致

现象：

- `ai_workforce` 当前不允许 viewer
- `ai_employee_ecosystem` 设计上应允许 viewer
- Health Center 是否允许 boss/viewer 需要统一

控制：

- Sprint62.19-D 实现前明确角色集
- 测试覆盖所有角色

### 17.2 从 `backend/main.py` 复用健康函数的依赖方向

现象：

- Service import main 可能导致依赖方向不理想

控制：

- V1 可不强依赖 `build_health_payload`
- 或只在 router 层调用
- 后续 V2 再抽离 `system_health` service
- 不在本阶段做重构

### 17.3 误触发执行模块

现象：

- 项目中存在 execution_engine、brain_execution、employee_execution 等执行模块

控制：

- Health Service 不 import 这些模块
- 静态测试禁止执行类字符串
- 安全字段固定 false

### 17.4 空数据被误判为系统故障

现象：

- 当前很多 V1 页面未接真实业务数据

控制：

- 空数据使用 `empty`
- 不直接判定 `unavailable`
- 页面显示“当前未接入真实业务数据”

### 17.5 测试误报 OpenClaw / n8n 字符串

现象：

- 安全字段必须包含 `openclaw_connected=false`、`n8n_connected=false`

控制：

- 测试区分安全字段和真实连接逻辑
- 禁止 `connect_openclaw`、`n8n_url`、HTTP 调用等真实接入痕迹

## 18. 实施顺序建议

确认后进入开发时，建议顺序：

1. 新增 `backend/services/ai_employee_health_overview.py`
2. 新增 `backend/routers/ai_employee_health.py`
3. 在 `backend/main.py` 注册 router
4. 新增 `tests/test_ai_employee_health.py`
5. 运行单测
6. 运行回归测试
7. 输出 Sprint62.19-D 开发验收报告

## 19. 验收标准

通过条件：

- 新增 API 可访问
- 返回完整 HealthStatus 结构
- 只读安全字段正确
- 不创建数据库
- 不创建 migration
- 不修改 Task Center 状态
- 不调用 Execution Engine
- 不接 OpenClaw
- 不接 n8n
- 测试通过

## 20. 结论

Sprint62.19-D 后端实现不需要新增数据库，不需要 migration。

推荐新增独立 router/service：

```text
backend/routers/ai_employee_health.py
backend/services/ai_employee_health_overview.py
```

核心数据复用：

```text
backend/services/ai_employee_ecosystem_overview.py
```

当前阶段已完成实现规划，等待确认后再进入代码开发。
