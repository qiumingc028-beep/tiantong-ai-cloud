# Sprint62.19-B AI Employee Health 后端架构设计

文档名称：《AI Employee Health 后端架构设计 V1》

阶段：Sprint62.19-B

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做后端架构设计。

禁止事项：

- 不写后端代码
- 不新增 API
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

AI Employee Health Center V1 只负责读取、聚合、评分、展示健康状态。

## 2. 后端定位

AI Employee Health 后端是 AI员工生态的只读健康聚合层。

它不替代任何业务模块，只读取现有系统状态并生成健康摘要：

```text
AI Workforce
Skill Center
Memory Center
Growth Center
Audit Center
AI Meeting Room
Task Center
        ↓
AI Employee Health Service
        ↓
GET /api/ai-employee-health/overview
        ↓
AI Employee Health Center 前端展示
```

核心职责：

- 汇总模块连接状态
- 汇总 API 可用状态
- 汇总数据更新时间
- 计算健康评分
- 输出异常提示
- 保留安全边界字段

不负责：

- 自动修复
- 自动重试业务动作
- 自动创建任务
- 自动修改员工状态
- 自动改变权限
- 自动调用执行系统

## 3. Health 数据模型设计

以下模型为后端响应与服务层概念模型，只做设计，不建表。

### 3.1 HealthStatus

整体健康快照。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| mode | string | 固定为 `readonly` |
| status | string | overall 状态：healthy / degraded / unavailable |
| overall_score | number | 总健康评分，0-100 |
| alert_count | integer | 当前异常数量 |
| generated_at | string | 生成时间 |
| modules | ModuleHealth[] | 模块健康状态 |
| apis | APIHealth[] | API健康状态 |
| freshness | DataFreshness[] | 数据更新时间状态 |
| score | HealthScore | 评分明细 |
| alerts | AlertRecord[] | 异常记录 |
| security | object | 安全边界状态 |

状态规则：

- `healthy`：总分 >= 85 且无 high 级别异常
- `degraded`：总分 60-84 或存在 medium 异常
- `unavailable`：总分 < 60 或核心 API 不可用

### 3.2 ModuleHealth

模块健康状态。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| module_key | string | 模块标识 |
| module_name | string | 模块名称 |
| status | string | connected / empty / degraded / unavailable / not_connected |
| source | string | 数据来源 |
| count | integer | 可用数据数量 |
| last_updated | string / null | 最近更新时间 |
| risk_level | string | low / medium / high / unknown |
| message | string | 展示说明 |
| readonly | boolean | 固定 true |

模块范围：

- `ai_workforce`
- `skill_center`
- `memory_center`
- `growth_center`
- `audit_center`
- `meeting_room`
- `task_center`

### 3.3 APIHealth

API 可用性状态。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| api_key | string | API 标识 |
| path | string | API 路径 |
| status | string | available / degraded / unavailable / not_checked |
| http_status | integer / null | HTTP 状态码 |
| latency_ms | integer / null | 响应耗时 |
| last_checked_at | string | 检查时间 |
| readonly | boolean | 固定 true |
| error_message | string / null | 错误摘要，不输出敏感信息 |

V1 建议监控：

- `/api/ai-employee-ecosystem/overview`
- `/api/health`
- `/api/ready`

### 3.4 DataFreshness

数据新鲜度状态。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| data_key | string | 数据域标识 |
| data_name | string | 数据域名称 |
| last_updated | string / null | 最近更新时间 |
| freshness_status | string | fresh / stale / empty / unavailable / not_connected |
| age_minutes | integer / null | 距离最近更新时间分钟数 |
| threshold_minutes | integer | 过期阈值 |
| message | string | 展示说明 |

V1 阈值建议：

- API健康：5分钟
- AI员工状态：60分钟
- Task状态：30分钟
- Skill/Knowledge/Memory/Growth：24小时
- Audit风险：60分钟

### 3.5 HealthScore

健康评分明细。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| overall | number | 总分 |
| module_score | number | 模块连接评分 |
| api_score | number | API可用评分 |
| freshness_score | number | 数据新鲜度评分 |
| security_score | number | 安全边界评分 |
| alert_penalty | number | 异常扣分 |
| breakdown | object | 各模块评分 |

V1 评分权重：

```text
overall_score =
  module_score * 0.35
+ api_score * 0.25
+ freshness_score * 0.20
+ security_score * 0.20
- alert_penalty
```

模块评分可继续沿用 Sprint62.19-A 的业务权重：

- AI Workforce：20%
- Skill Center：15%
- Memory Center：15%
- Growth Center：15%
- Audit Center：10%
- Task Center：10%
- Capability/Knowledge 汇总能力：15%

AI Meeting Room 在 V1 可展示但不纳入核心评分，避免因未接入数据影响总分。

### 3.6 AlertRecord

异常记录。

字段设计：

| 字段 | 类型 | 说明 |
|---|---|---|
| alert_id | string | 异常标识 |
| level | string | info / warning / high |
| type | string | api_unavailable / data_empty / data_stale / module_unavailable / security_warning |
| module_key | string | 关联模块 |
| title | string | 异常标题 |
| message | string | 异常说明 |
| detected_at | string | 发现时间 |
| requires_boss_confirm | boolean | 高风险是否需要 Boss 确认 |
| security_audited_required | boolean | 高风险是否需要安全审计 |
| action_available | boolean | V1 固定 false |

V1 异常只展示，不提供处理按钮。

## 4. API 设计

### 4.1 Overview API

接口：

```http
GET /api/ai-employee-health/overview
```

定位：

AI员工生态健康状态只读聚合接口。

返回内容：

- 总健康评分
- 模块状态
- API状态
- 数据更新时间
- 异常数量
- 异常列表
- 安全边界状态

### 4.2 Response JSON 草案

```json
{
  "mode": "readonly",
  "status": "degraded",
  "overall_score": 82,
  "generated_at": "2026-07-10T10:00:00+08:00",
  "alert_count": 2,
  "modules": [
    {
      "module_key": "ai_workforce",
      "module_name": "AI Workforce Center",
      "status": "connected",
      "source": "/api/ai-workforce/overview",
      "count": 12,
      "last_updated": "2026-07-10T09:58:00+08:00",
      "risk_level": "low",
      "message": "AI员工总览数据可用",
      "readonly": true
    }
  ],
  "apis": [
    {
      "api_key": "ai_employee_ecosystem_overview",
      "path": "/api/ai-employee-ecosystem/overview",
      "status": "available",
      "http_status": 200,
      "latency_ms": 35,
      "last_checked_at": "2026-07-10T10:00:00+08:00",
      "readonly": true,
      "error_message": null
    }
  ],
  "freshness": [
    {
      "data_key": "task_center",
      "data_name": "Task Center",
      "last_updated": null,
      "freshness_status": "empty",
      "age_minutes": null,
      "threshold_minutes": 30,
      "message": "当前未接入真实业务数据"
    }
  ],
  "score": {
    "overall": 82,
    "module_score": 80,
    "api_score": 100,
    "freshness_score": 70,
    "security_score": 100,
    "alert_penalty": 6,
    "breakdown": {
      "ai_workforce": 20,
      "skill_center": 15,
      "memory_center": 10,
      "growth_center": 10,
      "audit_center": 10,
      "task_center": 7
    }
  },
  "alerts": [
    {
      "alert_id": "health-task-center-empty",
      "level": "info",
      "type": "data_empty",
      "module_key": "task_center",
      "title": "Task Center 暂无数据",
      "message": "当前未接入真实业务数据",
      "detected_at": "2026-07-10T10:00:00+08:00",
      "requires_boss_confirm": false,
      "security_audited_required": false,
      "action_available": false
    }
  ],
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

## 5. Router 架构设计

未来实现建议新增独立 Router：

```text
backend/routers/ai_employee_health.py
```

Router 职责：

- 定义 `/api/ai-employee-health/overview`
- 调用 Health Service
- 返回统一 JSON
- 不直接查询数据库
- 不调用外部平台
- 不调用 Execution Engine

建议结构：

```text
APIRouter(prefix="/api/ai-employee-health", tags=["ai-employee-health"])
└── GET /overview
```

注册方式：

- 未来在 `backend/main.py` 只新增 router include
- 不修改已有 API 行为
- 不改变现有权限逻辑

## 6. Service 架构设计

未来实现建议新增独立 Service：

```text
backend/services/ai_employee_health_overview.py
```

Service 职责：

```text
build_ai_employee_health_overview()
├── collect_ecosystem_overview()
├── collect_system_api_health()
├── build_module_health()
├── build_api_health()
├── build_data_freshness()
├── compute_health_score()
├── build_alert_records()
└── build_security_state()
```

### 6.1 collect_ecosystem_overview

读取 AI员工生态统一 Overview 数据。

优先来源：

- 复用 `ai_employee_ecosystem_overview` 服务层
- 或内部只读函数

原则：

- 不通过 HTTP 自调用造成额外网络依赖
- 不修改已有生态 API
- 如果数据不可用，返回安全空状态

### 6.2 collect_system_api_health

读取系统健康状态。

可用来源：

- `/api/health`
- `/api/ready`
- 现有内部健康检查函数

原则：

- 只读检查
- 不触发修复
- 不重启服务
- 不写入日志以外的业务状态

### 6.3 build_module_health

将不同模块数据统一成 `ModuleHealth`：

- AI Workforce：员工总数、状态分布、风险数量
- Skill Center：技能数量、风险等级、审核状态
- Memory Center：记忆数量、最近更新时间
- Growth Center：成长数据可用性、成长记录数量
- Audit Center：风险事件数量、安全状态
- Meeting Room：会议数据可用性
- Task Center：任务总量、运行中、阻塞、待确认

### 6.4 build_api_health

输出 API 可用状态：

- 可访问：`available`
- 返回但数据不完整：`degraded`
- 失败：`unavailable`
- 未检查：`not_checked`

错误信息必须脱敏，不输出 token、连接串、环境变量、堆栈敏感路径。

### 6.5 build_data_freshness

统一判断数据更新时间：

- 有最近时间且未超阈值：`fresh`
- 有最近时间但超过阈值：`stale`
- 无数据：`empty`
- 数据源异常：`unavailable`
- 模块未接入：`not_connected`

### 6.6 compute_health_score

计算总健康评分。

设计原则：

- 空数据不等于系统错误
- 未接入真实业务数据时可给 `empty` 提示，不直接判定为高风险
- API 不可用优先影响总分
- 安全边界异常必须高权重扣分

### 6.7 build_alert_records

生成只读异常：

- API不可用
- 模块不可用
- 数据为空
- 数据过期
- 风险数量异常
- 安全字段异常

所有异常在 V1 均 `action_available=false`。

### 6.8 build_security_state

安全状态固定包含：

```json
{
  "readonly": true,
  "auto_repair_enabled": false,
  "auto_execute_enabled": false,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false,
  "permission_mutation_enabled": false,
  "task_mutation_enabled": false
}
```

## 7. 数据来源设计

### 7.1 AI Workforce

读取内容：

- 员工总数
- 员工状态
- 部门分布
- 风险数量

建议来源：

- 已有 AI Workforce overview API
- 已有员工模型只读查询

禁止：

- 创建员工
- 修改员工状态
- 修改员工权限

### 7.2 Skill Center

读取内容：

- 技能数量
- 技能状态
- 审核状态
- 风险等级

建议来源：

- 现有 Skill Center 页面/API
- sop skill center 相关只读数据

禁止：

- 自动安装技能
- 自动升级技能
- 自动授权技能

### 7.3 Memory Center

读取内容：

- 记忆数量
- 记忆类型
- 最近更新时间

V1 若无正式 API：

- 返回 `not_connected` 或 `empty`
- 显示“暂无数据”

禁止：

- 自动学习
- 自动修改记忆
- 自动训练模型

### 7.4 Growth Center

读取内容：

- 成长数据是否可用
- 成长记录数量
- 最近成长时间

禁止：

- 自动升级员工
- 自动修改技能
- 自动调整权限

### 7.5 Audit Center

读取内容：

- 风险数量
- 审计事件数量
- 安全检查状态

禁止：

- 自动修复
- 自动封禁
- 自动修改权限

### 7.6 AI Meeting Room

读取内容：

- 会议数量
- 草稿数量
- 最近会议时间

V1 若未实现：

- 返回 `not_connected`
- 不计入核心健康评分

禁止：

- 自动创建会议
- 自动创建任务
- 自动执行方案

### 7.7 Task Center

读取内容：

- 任务总数
- 运行中
- 待确认
- 阻塞
- 最近任务更新时间

禁止：

- 创建任务
- 修改任务状态
- 执行任务

## 8. 权限设计

V1 权限定位：只读展示权限。

角色建议：

| 角色 | 访问能力 |
|---|---|
| owner | 查看完整健康摘要 |
| admin | 查看管理范围内健康摘要 |
| viewer | 查看允许范围内摘要 |
| unauthorized | 禁止访问 |

实现原则：

- 不新增真实权限系统
- 不改变已有权限逻辑
- 复用现有认证/鉴权机制
- 未授权返回 401 或 403
- 不因访问健康接口产生权限变化

高风险信息展示规则：

- 可以展示风险状态
- 不展示敏感凭据
- 不展示环境变量
- 不展示数据库连接串
- 不展示完整堆栈敏感路径

## 9. 空数据与异常降级设计

### 9.1 数据为空

返回：

- 模块状态：`empty`
- 文案：`当前未接入真实业务数据`
- 总体状态不直接判定为失败

### 9.2 API失败

返回：

- API状态：`unavailable`
- 模块状态：`degraded` 或 `unavailable`
- 生成 warning/high alert
- 其他模块继续展示

### 9.3 部分字段缺失

处理：

- 数字字段默认 0
- 状态字段默认 `unknown`
- 时间字段默认 null
- 文案字段显示 `暂无数据`

### 9.4 安全字段异常

如果发现以下字段不为 false：

- `execution_engine_called`
- `openclaw_connected`
- `n8n_connected`
- `auto_execute_enabled`

必须：

- health status 降级
- 生成 high alert
- 标记需要 `security_audited=true`
- 标记需要 `boss_confirm=true`

## 10. 性能设计

V1 数据量较小，优先简单可靠。

建议：

- Service 内聚合现有只读数据
- 避免跨服务 HTTP 自调用
- 单次请求内设置合理超时
- 单模块失败不阻断整体响应
- 可在 V2 增加短 TTL 缓存

缓存设计建议：

- V1：不强制缓存
- V2：内存 TTL 30-60 秒
- V3：接入 Redis 健康快照

禁止：

- 为健康接口创建新业务表
- 为健康评分引入写入型任务
- 自动调度后台修复任务

## 11. 安全边界

AI Employee Health 后端必须保持：

```json
{
  "readonly": true,
  "auto_repair_enabled": false,
  "auto_execute_enabled": false,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false
}
```

明确禁止：

- 自动修复
- 自动重启
- 自动执行任务
- 自动创建任务
- 自动修改任务状态
- 自动修改员工权限
- 自动安装技能
- 自动升级技能
- 自动调用 Execution Engine
- 自动连接 OpenClaw
- 自动连接 n8n

Health Center 只能告诉老板哪里异常，不能替老板处理异常。

## 12. 测试方案

未来实现时建议新增：

```text
tests/test_ai_employee_health.py
```

测试用例：

1. API 返回 200
2. `mode=readonly`
3. 返回 `overall_score`
4. 返回 `modules`
5. 返回 `apis`
6. 返回 `freshness`
7. 返回 `alert_count`
8. 返回 `security.readonly=true`
9. `execution_engine_called=false`
10. `openclaw_connected=false`
11. `n8n_connected=false`
12. 空数据时不报错
13. 模块异常时整体接口仍可返回
14. 不存在执行、修复、权限修改字段

安全测试：

- 搜索接口实现中不得出现 Execution Engine 调用
- 不得出现 OpenClaw/n8n 连接逻辑
- 不得写数据库
- 不得创建任务
- 不得修改权限

## 13. Sprint62.19 后续拆分建议

### Sprint62.19-C

实现 AI Employee Health Overview API。

范围：

- 新增 router
- 新增 service
- 新增 tests
- 只读聚合

### Sprint62.19-D

实现 AI Employee Health Center 前端页面。

范围：

- 新增 `frontend/ai-employee-health.html`
- 接入 `/api/ai-employee-health/overview`
- 展示健康评分、模块状态、异常列表

### Sprint62.19-E

安全验收与发布检查。

范围：

- Docker Python 3.12 测试
- 安全边界检查
- 无执行入口检查
- 无数据库变化检查

## 14. 验收结论

Sprint62.19-B 已完成 AI Employee Health 后端架构设计。

本设计满足：

- 只读聚合
- 不修改数据库
- 不新增 migration
- 不接 Execution Engine
- 不接 OpenClaw
- 不接 n8n
- 不自动修复
- 不自动执行
- 不修改权限

等待确认后，方可进入 Sprint62.19-C 后端实现阶段。
