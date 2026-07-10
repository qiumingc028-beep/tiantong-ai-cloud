# Sprint62.33 AI员工技能中心后端设计

文档名称：《Sprint62.33 AI员工技能中心后端架构设计》

阶段：Sprint62.33

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做后端架构设计。

禁止事项：

- 不写代码
- 不新增 API
- 不修改现有业务逻辑
- 不创建数据库 migration
- 不修改数据库结构
- 不接入 Execution Engine
- 不接入 OpenClaw
- 不接入 n8n
- 不自动调用技能
- 不自动安装技能
- 不自动升级技能
- 不自动修改员工权限

Sprint62.33 只设计 Skill Center 后端架构，等待确认后再开发。

## 2. 后端模块设计

### 2.1 Router 设计

建议新增独立 router：

```text
backend/routers/ai_employee_skills.py
```

建议路由前缀：

```text
/api/ai-employee-skills
```

职责：

- 暴露 AI员工技能中心只读 API。
- 校验登录与查看权限。
- 调用 service 进行只读聚合。
- 返回统一 JSON 结构。
- 不写入数据库。
- 不调用技能执行。

建议 router 结构：

```python
router = APIRouter(prefix="/api/ai-employee-skills")

@router.get("/skills")
def list_employee_skills(...):
    ...

@router.get("/skills/{skill_id}")
def get_skill_detail(...):
    ...

@router.get("/employees/{employee_id}/skills")
def get_employee_skill_relations(...):
    ...
```

权限建议：

- `owner`
- `boss`
- `admin`

后续可扩展：

- 部门负责人只读查看本部门。
- Viewer 只读查看公开摘要。

### 2.2 Service 设计

建议新增 service：

```text
backend/services/ai_employee_skill_center.py
```

职责：

- 聚合员工、技能、任务、成长、记忆、审计数据。
- 生成员工技能资产视图。
- 计算使用次数、成功率、风险等级。
- 统一处理空数据和异常降级。
- 返回只读安全字段。

建议 service 函数：

```python
def build_employee_skill_overview(db: Session, user: User) -> dict:
    ...

def list_employee_skill_assets(db: Session, filters: dict | None = None) -> list[dict]:
    ...

def get_skill_asset_detail(db: Session, skill_id: str) -> dict:
    ...

def get_employee_skill_relations(db: Session, employee_id: str) -> dict:
    ...
```

### 2.3 数据来源

首期只读聚合来源：

| 来源 | 现有对象/API | 用途 |
|---|---|---|
| AI员工 | `AiEmployee` | 员工编号、名称、部门、职责、技能来源 |
| Skill Center | `sop_skill_center.SKILLS` / 未来 Skill 表 | 技能名称、版本、状态、风险 |
| Task Center | `TaskCenterTask` | 使用次数、成功/失败次数、最近任务 |
| Memory Center | Task / Knowledge / Bug 只读聚合 | 成功案例、失败案例、经验引用 |
| Growth Center | `EmployeeGrowth` | 员工成长、成功率参考 |
| Audit Center | `RiskEvent` | 风险等级、审计状态 |

首期不新增表。

### 2.4 API结构总览

```text
GET /api/ai-employee-skills/skills
GET /api/ai-employee-skills/skills/{skill_id}
GET /api/ai-employee-skills/employees/{employee_id}/skills
```

统一响应安全字段：

```json
{
  "security": {
    "readonly": true,
    "auto_skill_call_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

## 3. 技能数据模型设计

本阶段只设计，不建表。

### 3.1 EmployeeSkillAsset

用于员工技能列表和技能矩阵。

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `skill_id` | string | 技能唯一标识 |
| `skill_name` | string | 技能名称 |
| `skill_version` | string | 技能版本 |
| `employee_id` | string | 员工编号 |
| `employee_name` | string | 员工名称 |
| `department` | string | 所属部门 |
| `usage_count` | integer | 使用次数 |
| `success_count` | integer | 成功次数 |
| `failure_count` | integer | 失败次数 |
| `success_rate` | number/null | 成功率 |
| `risk_level` | string | low / medium / high / critical |
| `created_time` | string/null | 创建时间 |
| `updated_time` | string/null | 更新时间 |
| `last_used_at` | string/null | 最近使用时间 |
| `audit_status` | string | readonly / review_required / audited |

JSON 示例：

```json
{
  "skill_id": "jd_operation_skill",
  "skill_name": "京东运营技能",
  "skill_version": "v1.0",
  "employee_id": "tianshang",
  "employee_name": "天商",
  "department": "业务部门",
  "usage_count": 12,
  "success_count": 9,
  "failure_count": 3,
  "success_rate": 0.75,
  "risk_level": "medium",
  "created_time": null,
  "updated_time": null,
  "last_used_at": null,
  "audit_status": "readonly"
}
```

### 3.2 SkillDetail

用于技能详情 API。

```json
{
  "skill_id": "jd_operation_skill",
  "skill_name": "京东运营技能",
  "skill_version": "v1.0",
  "description": "京东店铺商品运营、竞品分析、运营建议能力",
  "risk_level": "medium",
  "employee_count": 3,
  "usage_count": 12,
  "success_rate": 0.75,
  "employees": [],
  "task_usage": [],
  "memory_refs": [],
  "growth_refs": [],
  "audit_refs": []
}
```

### 3.3 EmployeeSkillRelation

用于某员工的技能关系 API。

```json
{
  "employee_id": "tianshang",
  "employee_name": "天商",
  "department": "业务部门",
  "skills": [
    {
      "skill_id": "jd_operation_skill",
      "skill_name": "京东运营技能",
      "skill_version": "v1.0",
      "usage_count": 12,
      "success_rate": 0.75,
      "risk_level": "medium"
    }
  ],
  "summary": {
    "skill_total": 1,
    "high_risk_skill_count": 0,
    "average_success_rate": 0.75
  }
}
```

## 4. API设计

### 4.1 GET 技能列表

接口：

```text
GET /api/ai-employee-skills/skills
```

用途：

- 返回所有员工技能资产列表。
- 支持前端技能中心矩阵展示。

Query 参数：

| 参数 | 说明 |
|---|---|
| `employee_id` | 按员工筛选 |
| `department` | 按部门筛选 |
| `risk_level` | 按风险等级筛选 |
| `skill_version` | 按技能版本筛选 |
| `q` | 搜索技能名称或员工名称 |

响应：

```json
{
  "mode": "readonly",
  "summary": {
    "skill_total": 0,
    "employee_with_skill_count": 0,
    "high_risk_skill_count": 0,
    "average_success_rate": null,
    "last_updated": null
  },
  "skills": [
    {
      "skill_id": "jd_operation_skill",
      "skill_name": "京东运营技能",
      "skill_version": "v1.0",
      "employee_id": "tianshang",
      "employee_name": "天商",
      "department": "业务部门",
      "usage_count": 0,
      "success_rate": null,
      "risk_level": "medium",
      "created_time": null,
      "updated_time": null
    }
  ],
  "security": {
    "readonly": true,
    "auto_skill_call_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

### 4.2 GET 技能详情

接口：

```text
GET /api/ai-employee-skills/skills/{skill_id}
```

用途：

- 返回某个技能的完整只读详情。
- 展示关联员工、使用记录、成功率、风险审计。

响应：

```json
{
  "mode": "readonly",
  "skill": {
    "skill_id": "jd_operation_skill",
    "skill_name": "京东运营技能",
    "skill_version": "v1.0",
    "description": "京东店铺商品运营能力",
    "risk_level": "medium",
    "usage_count": 12,
    "success_rate": 0.75,
    "updated_time": null
  },
  "employees": [],
  "task_usage": [],
  "memory_refs": [],
  "growth_refs": [],
  "audit_refs": [],
  "security": {
    "readonly": true,
    "auto_skill_call_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

### 4.3 GET 员工技能关系

接口：

```text
GET /api/ai-employee-skills/employees/{employee_id}/skills
```

用途：

- 返回某个 AI员工拥有或适用的技能列表。
- 支持员工详情页展示技能资产。

响应：

```json
{
  "mode": "readonly",
  "employee": {
    "employee_id": "tianshang",
    "employee_name": "天商",
    "department": "业务部门"
  },
  "summary": {
    "skill_total": 1,
    "high_risk_skill_count": 0,
    "average_success_rate": null
  },
  "skills": [],
  "security": {
    "readonly": true,
    "auto_skill_call_enabled": false,
    "execution_engine_called": false,
    "openclaw_connected": false,
    "n8n_connected": false
  }
}
```

## 5. 与现有模块关系

### 5.1 AI Workforce Center

关系：

- 提供员工列表、员工详情入口、部门和状态信息。
- AI员工技能中心可作为 AI Workforce Center 的能力资产下钻。

读取：

- `AiEmployee.employee_code`
- `AiEmployee.employee_name`
- `AiEmployee.legion`
- `AiEmployee.duty`
- `AiEmployee.task_types`

禁止：

- 修改员工状态
- 修改员工权限
- 创建员工

### 5.2 Task Center

关系：

- 提供技能使用次数和成功率统计依据。
- 按员工或技能关联任务状态。

只读统计：

- 使用次数：关联任务总数
- 成功次数：`accepted / audited / summarized`
- 失败次数：`rejected / failed / blocked`
- 最近使用时间：任务 `updated_at`

禁止：

- 创建任务
- 修改任务状态
- 触发任务执行

### 5.3 Memory Center

关系：

- 提供成功案例、失败案例、经验记忆。
- 未来可展示技能关联案例数量。

首期来源：

- Task Center 成功/失败任务
- Knowledge / BugCase 只读聚合

禁止：

- 自动学习
- 自动写入 Memory
- 自动修改技能评分

### 5.4 Growth Center

关系：

- 提供员工成长记录和技能成熟度参考。
- 技能成功率可作为 Growth 展示依据。

首期来源：

- `EmployeeGrowth`
- Task Center 成功率只读统计

禁止：

- 自动晋升员工
- 自动修改成长等级
- 自动调整权限

### 5.5 Audit Center

关系：

- 提供技能风险、失败事件、安全审计状态。
- 高风险技能必须展示审核要求。

首期来源：

- `RiskEvent`
- Task Center blocked / failed / rejected 状态

禁止：

- 自动处罚
- 自动封禁技能
- 自动调整员工权限

## 6. 只读聚合计算规则

### 6.1 skill_name

来源优先级：

1. Skill Center 静态技能配置
2. `AiEmployee.task_types`
3. 前端/后端只读映射名称

不得生成虚假技能。

### 6.2 skill_version

来源优先级：

1. Skill Center 版本字段
2. 默认显示 `暂无版本`

不得自动升级版本。

### 6.3 usage_count

来源：

- Task Center 只读任务统计。

计算：

```text
usage_count = 与员工或技能相关的任务数量
```

### 6.4 success_rate

来源：

- Task Center 任务结果状态。

计算：

```text
success_rate = success_count / usage_count
```

当 `usage_count=0`：

```text
success_rate = null
```

### 6.5 risk_level

来源：

- Skill Center 风险等级
- Audit Center RiskEvent
- Task Center blocked / failed / rejected

合并规则：

```text
critical > high > medium > low
```

## 7. 空数据与异常处理

空数据：

- 无员工：返回空 `skills=[]`
- 无技能：返回空 `skills=[]`
- 无使用记录：`usage_count=0`，`success_rate=null`
- 无更新时间：`updated_time=null`

异常处理：

- 某个模块读取失败时，返回该模块错误到 `errors`
- 其他模块继续返回
- 不触发重试执行
- 不写入修复数据

错误结构：

```json
{
  "errors": [
    {
      "module": "task_center",
      "message": "Task Center readonly data unavailable"
    }
  ]
}
```

## 8. 安全设计

统一安全字段：

```json
{
  "readonly": true,
  "auto_skill_call_enabled": false,
  "auto_skill_install_enabled": false,
  "auto_skill_upgrade_enabled": false,
  "permission_mutation_enabled": false,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false
}
```

高风险技能：

```json
{
  "risk_level": "high",
  "boss_confirm_required": true,
  "security_audited_required": true,
  "action_available": false
}
```

禁止：

- 创建数据库 migration
- 修改现有业务
- 接入 Execution Engine
- 接入 OpenClaw
- 接入 n8n
- 自动调用技能

## 9. 测试方案

后续开发阶段建议新增：

```text
tests/test_ai_employee_skills.py
```

测试点：

1. 未登录访问返回 401。
2. 无权限角色返回 403。
3. `GET /api/ai-employee-skills/skills` 返回只读结构。
4. `GET /api/ai-employee-skills/skills/{skill_id}` 返回技能详情。
5. `GET /api/ai-employee-skills/employees/{employee_id}/skills` 返回员工技能关系。
6. 空数据时返回空列表和 `success_rate=null`。
7. 安全字段保持 `execution_engine_called=false`、`openclaw_connected=false`、`n8n_connected=false`。
8. 不调用 Task Center 写接口。
9. 不创建 migration。

## 10. 后续开发拆分

建议：

1. Sprint62.34：AI员工技能中心只读 API 实现。
2. Sprint62.35：AI员工技能中心前端页面开发。
3. Sprint62.36：Task Center / Audit Center 使用统计增强。
4. Sprint62.37：技能详情页与员工详情页联动。

每一步都必须保持：

- 只读
- 不修改数据库结构
- 不接执行系统
- 不自动调用技能

## 11. 验收结论

Sprint62.33 已完成 AI员工技能中心后端架构设计。

本设计覆盖：

- Router / Service / 数据来源 / API结构
- 技能数据模型字段：`skill_name`、`skill_version`、`employee_id`、`usage_count`、`success_rate`、`risk_level`、`created_time`、`updated_time`
- 与 AI Workforce Center、Task Center、Memory Center、Growth Center、Audit Center 的关系
- GET 技能列表、GET 技能详情、GET 员工技能关系
- 禁止创建 migration、修改现有业务、接入 Execution Engine / OpenClaw / n8n、自动调用技能

等待确认后再开发。
