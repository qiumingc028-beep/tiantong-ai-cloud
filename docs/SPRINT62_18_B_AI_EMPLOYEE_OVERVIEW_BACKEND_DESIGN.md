# Sprint62.18-B AI Employee Ecosystem Overview 后端实现方案设计

## 1. 阶段边界

本阶段只做后端架构设计，不写代码。

禁止：

- 不新增后端实现。
- 不修改 router。
- 不修改业务逻辑。
- 不修改数据库。
- 不创建 migration。
- 不调用 Execution Engine。
- 不接 OpenClaw。
- 不接 n8n。
- 不自动执行任何动作。
- 不修改员工权限。

目标接口：

```http
GET /api/ai-employee-ecosystem/overview
```

定位：

为 AI Employee Dashboard V1 提供统一只读生态摘要。该接口只聚合现有系统状态，不成为执行入口，不替代现有 AI Workforce、Skill Center、Task Center、Growth、Memory、Audit 模块。

## 2. Router 结构设计

建议新增：

```text
backend/routers/ai_employee_ecosystem.py
```

Router：

```python
router = APIRouter(prefix="/api/ai-employee-ecosystem")
```

接口：

```python
@router.get("/overview")
def get_ai_employee_ecosystem_overview(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_ai_employee_ecosystem_user(request, db)
    return build_ai_employee_ecosystem_overview(db, user)
```

注册方式：

```python
from .routers import ai_employee_ecosystem

app.include_router(ai_employee_ecosystem.router)
```

允许改动范围：

- `backend/routers/ai_employee_ecosystem.py`
- `backend/main.py` 仅注册 router
- `tests/test_ai_employee_ecosystem_overview.py`

禁止：

- 修改现有 Task Center router。
- 修改 Execution Engine。
- 修改 Employee Evolution 分析逻辑。
- 修改数据库模型。

## 3. Service 层结构设计

建议新增 service：

```text
backend/services/ai_employee_ecosystem_overview.py
```

如果当前项目暂无统一 `services/` 目录，也可先在 router 文件内保持纯只读 helper 函数，后续再抽离。推荐结构如下：

```text
backend/services/ai_employee_ecosystem_overview.py
├── build_ai_employee_ecosystem_overview(db, user)
├── collect_employee_stats(db, user)
├── collect_capability_stats(db, user)
├── collect_skill_stats(db, user)
├── collect_memory_stats(db, user)
├── collect_growth_stats(db, user)
├── collect_audit_stats(db, user)
├── collect_meeting_stats(db, user)
├── collect_task_stats(db, user)
├── build_center_entries(sections)
├── build_security_payload()
├── build_empty_state(sections)
└── safe_collect(module, collector)
```

设计原则：

- 每个 collector 只读数据库。
- 每个 collector 独立失败降级。
- 不通过 HTTP 调用本服务内部 API，避免递归、鉴权重复和性能浪费。
- 优先复用已有 helper 函数；无法稳定复用时直接只读查询表。

## 4. 数据读取来源设计

### 4.1 AI Workforce

目标字段：

```json
{
  "total": 0,
  "working": 0,
  "idle": 0,
  "frozen": 0,
  "offline": 0,
  "departments": []
}
```

来源：

- `AiEmployee`
- `TaskCenterTask`
- 现有 `backend/routers/ai_workforce.py` 中的只读统计逻辑可参考：
  - `employee_summary`
  - `build_employee_cards`
  - `task_status_counts`

实现建议：

- 直接查询 `AiEmployee`。
- 根据员工 `status` / runtime 只读推导 working / idle / frozen / offline。
- 部门使用 `department` 字段分组。

不做：

- 不创建员工。
- 不修改员工状态。
- 不刷新 runtime。

### 4.2 Capability Center

目标字段：

```json
{
  "available": false,
  "configured_capabilities": 0,
  "missing_capability_count": 0,
  "average_maturity_level": null,
  "average_success_rate": null
}
```

来源：

- 现有 `backend/routers/employee_capabilities.py`
- 可参考：
  - `build_capability_rows`
  - `build_overview_summary`
  - `aggregate_employee_metrics`

实现建议：

- 如果 helper 函数无副作用，可直接复用。
- 否则按 `AiEmployee` + Task Center 只读统计能力摘要。

不做：

- 不生成能力建议。
- 不修改能力档案。

### 4.3 Skill Center

目标字段：

```json
{
  "total": 0,
  "enabled": 0,
  "reviewing": 0,
  "high_risk": 0,
  "sop_count": 0,
  "prompt_count": 0
}
```

来源：

- `backend/routers/sop_skill_center.py`
- 静态/配置数据：
  - `SKILLS`
  - `SOPS`
  - `PROMPTS`
- 可参考：
  - `get_sop_skill_overview`
  - `get_sop_skill_skills`

实现建议：

- 直接读取模块内只读常量或通过 helper 函数封装。
- `enabled` 统计 approved / active / readonly。
- `reviewing` 统计 review / pending / requires_security_audit。
- `high_risk` 统计 safety_level 或 risk_level 为 high / critical。

不做：

- 不安装技能。
- 不升级技能。
- 不改变审核状态。

### 4.4 Memory Center

目标字段：

```json
{
  "total": 0,
  "last_updated": null,
  "types": {
    "Experience": 0,
    "DecisionHistory": 0,
    "LearningRecord": 0,
    "SuccessCase": 0,
    "FailureCase": 0
  }
}
```

来源：

- `TaskCenterTask`
- 天藏相关模型：
  - `KnowledgeArticle`
  - `SopLibrary`
  - `PromptLibrary`
  - `BugCase`

映射：

| Memory 类型 | 数据来源 |
| --- | --- |
| `Experience` | Task Center 任务记录 |
| `DecisionHistory` | KnowledgeArticle |
| `LearningRecord` | SopLibrary + PromptLibrary |
| `SuccessCase` | accepted / audited / summarized 任务 |
| `FailureCase` | rejected 任务 + BugCase |

实现建议：

- 使用 count 查询，不加载全文内容。
- `last_updated` 使用各来源最大更新时间。
- 只返回统计，不返回文章正文、Prompt 内容、SOP 全文。

不做：

- 不写入记忆。
- 不自动学习。
- 不发布知识。

### 4.5 Growth Center

目标字段：

```json
{
  "available": false,
  "growth_records": 0,
  "growth_level": null,
  "skill_trend": null,
  "recent_growth_records": 0
}
```

来源：

- `EmployeeGrowth`
- 可参考 `backend/routers/employee_evolution.py`：
  - `list_employee_growth`

实现建议：

- 直接查询 `EmployeeGrowth`。
- 计算平均 `score` 推导 `growth_level`。
- 使用 `skill_growth` 或 score 推导 `skill_trend`。
- `recent_growth_records` 可按最近 30 天或最新记录数量统计。

明确禁止：

- 不调用 `POST /api/employee-evolution/analyze`。
- 不触发任何成长分析。
- 不创建 `EmployeeGrowth`。

### 4.6 Audit Center

目标字段：

```json
{
  "risk_count": 0,
  "high_risk_count": 0,
  "pending_boss_confirm": 0,
  "security_audited_required": 0
}
```

来源：

- `RiskEvent`
- `TaskCenterTask`
- `TaskCenterReview`
- `TaskCenterAuditLog`

实现建议：

- `risk_count`：RiskEvent 总数。
- `high_risk_count`：high / critical 事件。
- `pending_boss_confirm`：高风险但未确认的事项，V1 可先根据风险等级推导。
- `security_audited_required`：高风险或审计未完成事项。

不做：

- 不自动修复。
- 不封禁员工。
- 不修改权限。
- 不提交审计结果。

### 4.7 Meeting Room

目标字段：

```json
{
  "available": false,
  "meeting_count": 0,
  "draft_count": 0,
  "participant_count": 0,
  "status": "not_connected"
}
```

来源：

- V1 暂无统一 Meeting Room 数据表或 API。

实现建议：

- 返回安全空状态。
- `status="not_connected"`。
- `available=false`。

不做：

- 不创建会议。
- 不生成方案。
- 不创建任务。

### 4.8 Task Center

目标字段：

```json
{
  "total": 0,
  "running": 0,
  "pending": 0,
  "blocked": 0,
  "review_pending": 0
}
```

来源：

- `TaskCenterTask`

状态映射：

| 字段 | 状态 |
| --- | --- |
| `running` | `running` |
| `pending` | `created`, `split`, `assigned` |
| `blocked` | `rejected`, `blocked` |
| `review_pending` | `result_submitted` |

实现建议：

- 使用 SQL 聚合查询或一次读取有限字段后 Python 统计。
- 不调用 Task Center POST/PATCH 接口。

不做：

- 不创建任务。
- 不分配员工。
- 不启动任务。
- 不修改任务状态。

## 5. 返回 JSON 结构

后端返回结构与 Sprint62.18-A 保持一致：

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
  "centers": [],
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
  "data_sources": [],
  "errors": []
}
```

## 6. 数据为空处理方案

### 6.1 空数据原则

- 返回 200。
- 对应统计返回 0。
- 对应字符串返回 `null` 或固定空状态。
- `empty_state.no_real_business_data=true`。
- 不生成假数据。

### 6.2 模块空状态

| 模块 | 空状态返回 |
| --- | --- |
| AI Workforce | employees 全部 0，departments 空数组 |
| Capability | `available=false` |
| Skill | total / enabled / reviewing / high_risk 为 0 |
| Memory | total=0，types 全部 0 |
| Growth | `available=false` |
| Audit | risk_count=0 |
| Meeting | `status=not_connected` |
| Task | total=0 |

### 6.3 模块异常

单模块异常不抛出 500，写入：

```json
{
  "module": "memory",
  "status": "unavailable",
  "message": "当前数据不可用"
}
```

只有以下情况返回非 200：

| 状态 | 场景 |
| --- | --- |
| 401 | 未登录 |
| 403 | 已登录但无查看权限 |

## 7. 性能方案

### 7.1 查询策略

优先使用 count / group_by 查询：

- 员工状态：按 status 分组。
- 部门统计：按 department 分组。
- Task 状态：按 status 分组。
- Risk 统计：按 risk_level 分组。
- Memory 统计：只 count，不拉取正文。

避免：

- 不加载大字段正文。
- 不返回 SOP / Prompt / Article 全文。
- 不 N+1 查询员工详情。
- 不通过 HTTP 调内部 API。

### 7.2 查询数量控制

V1 目标：

- 单次 overview 请求控制在 8-12 个轻量查询以内。
- 统计类只取 count / max(updated_at)。
- 复杂计算后续可加入缓存，不在 V1 强制实现。

### 7.3 缓存建议

V1 可不启用缓存。

未来可选：

- Redis 缓存 30-60 秒。
- 缓存 key：`ai_employee_ecosystem:overview:{role}:{user_id}`。
- 缓存内容必须只包含已授权可见数据。

缓存不得绕过权限。

## 8. 权限方案

### 8.1 鉴权入口

建议新增：

```python
def require_ai_employee_ecosystem_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role in {"owner", "boss", "admin", "viewer"}:
        return user
    raise HTTPException(status_code=403, detail="无AI员工生态查看权限")
```

### 8.2 角色范围

| 角色 | 可见范围 |
| --- | --- |
| owner / boss | 全量生态摘要 |
| admin | 管理范围摘要，V1 可先全量只读 |
| viewer | 允许只读摘要，敏感字段最小化 |
| unauthorized | 401 |
| other | 403 |

### 8.3 权限边界

权限只控制可见范围。

禁止：

- 因查看 overview 自动提升权限。
- 因风险状态自动修改权限。
- 因成长评分自动调整角色。
- 因任务状态自动改变员工状态。

## 9. 安全限制落实

后端实现中不得出现：

- `execution_engine`
- `OpenClaw`
- `n8n`
- `/api/execution`
- `/api/brain/start`
- `employee_evolution.analyze`
- `TaskCenterTask(...)` 新建任务
- `db.add(...)`
- `db.delete(...)`
- `db.commit()` 用于业务数据

允许：

- 只读查询。
- 认证校验。
- 构造响应 JSON。
- 捕获单模块异常。

如果后续实现因审计日志需要记录访问行为，必须单独确认；Sprint62.18-B 设计不要求写审计日志。

## 10. 测试方案

建议新增：

```text
tests/test_ai_employee_ecosystem_overview.py
```

测试内容：

1. 未登录访问返回 401。
2. owner 访问返回 200。
3. 返回 `mode=readonly`。
4. 返回字段：
   - employees
   - capability
   - skill
   - memory
   - growth
   - audit
   - meeting
   - task
   - security
   - errors
5. `security.readonly=true`。
6. `security.execution_engine_called=false`。
7. `security.openclaw_connected=false`。
8. `security.n8n_connected=false`。
9. 空数据返回 200 和空状态。
10. 创建接口前后 Task 数量不变。
11. 创建接口前后员工权限不变。
12. 静态扫描 router 文件不包含危险词。

静态扫描建议：

```text
Execution Engine
OpenClaw
n8n
/api/execution
/api/brain/start
employee-evolution/analyze
db.commit()
db.add(
db.delete(
```

## 11. 开发拆分建议

### Sprint62.18-C 后端实现

新增：

- `backend/routers/ai_employee_ecosystem.py`
- `tests/test_ai_employee_ecosystem_overview.py`

最小修改：

- `backend/main.py` 注册 router。

不做：

- 不创建 service 目录，除非代码量明显需要。
- 不改现有模块。

### Sprint62.18-D 前端接入

新增：

- `frontend/ai-employee-dashboard.html`
- `tests/test_ai_employee_dashboard.py`

接入：

- `GET /api/ai-employee-ecosystem/overview`

## 12. 验收标准

设计阶段通过条件：

- 已定义 Router 结构。
- 已定义 Service 层结构。
- 已定义七类数据来源与 Task Center 统计方式。
- 已定义返回 JSON。
- 已定义空数据处理。
- 已定义性能方案。
- 已定义权限方案。
- 已明确安全限制。
- 未写代码。
- 未修改数据库。
- 未创建 migration。
- 未接 Execution Engine / OpenClaw / n8n。
