# Sprint62.19-A AI员工生态健康监控中心设计

## 1. 阶段边界

本阶段只做产品设计，不写代码。

禁止：

- 不自动修复。
- 不自动重启。
- 不自动执行任务。
- 不接 OpenClaw。
- 不接 n8n。
- 不接 Execution Engine。
- 不修改数据库。
- 不创建 migration。

目标产品：

```text
AI Employee Health Center
```

建议页面：

```text
frontend/ai-employee-health.html
```

定位：

AI Employee Health Center 是 AI员工生态的只读健康监控中心，用于观察 AI Workforce、Skill Center、Memory、Growth、Audit、Meeting、Task Center 的连接状态、数据更新时间、数据完整度和异常提示。

## 2. 产品目标

Health Center 回答 5 个问题：

1. 各模块数据是否能正常读取？
2. 各模块数据最近什么时候更新？
3. 哪些模块尚未接入或暂无数据？
4. AI员工生态数据完整度如何？
5. 哪些异常需要人工检查？

它不负责：

- 修复异常。
- 重启服务。
- 执行任务。
- 修改模块状态。
- 修改员工、技能、权限、记忆、成长数据。

## 3. 总体页面结构

```text
AI Employee Health Center
├── 顶部状态栏
│   ├── AI Employee Health Center
│   ├── 当前组织：天统AI
│   ├── 当前模式：readonly
│   └── 最近检查时间
├── 健康总览
│   ├── 总体健康状态
│   ├── 可用模块数量
│   ├── 异常模块数量
│   ├── 暂未接入模块数量
│   └── 数据完整度评分
├── 数据更新时间监控
│   ├── AI Workforce 更新时间
│   ├── Skill Center 更新时间
│   ├── Memory 更新时间
│   ├── Growth 更新时间
│   ├── Audit 更新时间
│   ├── Meeting 更新时间
│   └── Task Center 更新时间
├── API健康状态
│   ├── /api/ai-employee-ecosystem/overview
│   ├── /api/health
│   ├── /api/ready
│   └── 各模块只读 API 状态
├── 模块连接状态
│   ├── AI Workforce
│   ├── Skill Center
│   ├── Memory Center
│   ├── Growth Center
│   ├── Audit Center
│   ├── Meeting Room
│   └── Task Center
├── 数据完整度评分
│   ├── 员工数据完整度
│   ├── 能力数据完整度
│   ├── Skill数据完整度
│   ├── Memory数据完整度
│   ├── Growth数据完整度
│   ├── Audit数据完整度
│   └── Task数据完整度
└── 异常提示
    ├── 数据不可用
    ├── 数据为空
    ├── 数据过期
    ├── 高风险状态
    └── 暂未接入模块
```

## 4. 数据来源设计

V1 优先复用：

```http
GET /api/ai-employee-ecosystem/overview
GET /api/health
GET /api/ready
```

后续可选只读来源：

| 模块 | API |
| --- | --- |
| AI Workforce | `GET /api/ai-workforce/overview` |
| Skill Center | `GET /api/sop-skill-center/overview` |
| Memory Center | `GET /api/ai-employee-ecosystem/overview.memory` 聚合字段 |
| Growth Center | `GET /api/employee-evolution/growth` |
| Audit Center | `GET /api/employee-evolution/risk-events` |
| Meeting Room | V1 `not_connected` |
| Task Center | `GET /api/task-center/tasks` |

V1 建议：

- Health Center 页面只调用 `GET /api/ai-employee-ecosystem/overview`。
- 系统服务健康可读取 `GET /api/health`。
- 后端如果未来新增 `/api/ai-employee-health/overview`，也必须只读。

## 5. 数据更新时间监控

### 5.1 更新时间字段

| 模块 | 更新时间来源 | V1 状态 |
| --- | --- | --- |
| AI Workforce | 员工 `updated_at` 最大值 | 可接入 |
| Skill Center | 静态配置暂无更新时间 | 显示 `暂无数据` |
| Memory Center | `memory.last_updated` | 可接入 |
| Growth Center | `EmployeeGrowth.created_at` 最大值 | 可接入 |
| Audit Center | `RiskEvent.created_at` 最大值 | 可接入 |
| Meeting Room | 暂无统一来源 | `not_connected` |
| Task Center | `TaskCenterTask.updated_at` 最大值 | 可接入 |

### 5.2 更新时间状态

| 状态 | 判断 |
| --- | --- |
| `fresh` | 最近 24 小时内更新 |
| `stale` | 超过 24 小时未更新 |
| `empty` | 模块无数据 |
| `unavailable` | API 异常 |
| `not_connected` | 模块尚未接入 |

页面展示：

```text
模块名称 / 最近更新时间 / 更新状态 / 数据来源
```

## 6. API 健康状态

### 6.1 API 状态字段

```json
{
  "api": "/api/ai-employee-ecosystem/overview",
  "status": "available",
  "http_status": 200,
  "latency_ms": null,
  "last_checked_at": "2026-07-10T00:00:00Z",
  "readonly": true
}
```

### 6.2 健康状态枚举

| 状态 | 含义 |
| --- | --- |
| `available` | API 可访问且返回结构正常 |
| `partial` | API 可访问但部分模块异常 |
| `empty` | API 可访问但无业务数据 |
| `unavailable` | API 请求失败 |
| `unauthorized` | 无权限访问 |

### 6.3 V1 API 检查项

- `mode=readonly`
- `security.readonly=true`
- `security.execution_engine_called=false`
- `security.openclaw_connected=false`
- `security.n8n_connected=false`
- `errors` 数组可展示模块异常
- `empty_state.no_real_business_data` 可展示空数据状态

## 7. 模块连接状态设计

### 7.1 模块清单

| 模块 | 连接状态来源 | V1 默认 |
| --- | --- | --- |
| AI Workforce | `employees.total` / center status | available / empty |
| Skill Center | `skill.total` / center status | available / empty |
| Memory Center | `memory.total` / center status | available / empty |
| Growth Center | `growth.available` / center status | available / empty |
| Audit Center | `audit.risk_count` / center status | available / empty |
| Meeting Room | `meeting.status` | not_connected |
| Task Center | `task.total` / center status | available / empty |

### 7.2 模块卡片字段

```json
{
  "module": "Skill Center",
  "connection_status": "available",
  "data_count": 5,
  "last_updated": null,
  "risk_level": "low",
  "message": "Skill Center 只读数据可用"
}
```

### 7.3 状态颜色

| 状态 | 颜色 |
| --- | --- |
| available | green |
| partial | yellow |
| empty | gray |
| stale | yellow |
| unavailable | red |
| not_connected | gray |

## 8. 数据完整度评分

### 8.1 总分模型

```text
health_score =
员工数据完整度 * 20%
+ 能力数据完整度 * 15%
+ Skill数据完整度 * 15%
+ Memory数据完整度 * 15%
+ Growth数据完整度 * 15%
+ Audit数据完整度 * 10%
+ Task数据完整度 * 10%
```

Meeting Room 在 V1 尚未接入，不计入总分，单独显示 `not_connected`。

### 8.2 单模块评分

| 模块 | 满分条件 |
| --- | --- |
| AI Workforce | `employees.total > 0` 且部门数据存在 |
| Capability | `capability.available=true` 且能力字段完整 |
| Skill Center | `skill.total > 0` |
| Memory Center | `memory.total > 0` 且 types 字段完整 |
| Growth Center | `growth.available=true` |
| Audit Center | audit 字段存在，风险统计可读取 |
| Task Center | task 字段存在，状态统计可读取 |

### 8.3 评分等级

| 分数 | 等级 | 含义 |
| --- | --- | --- |
| 90-100 | healthy | 生态数据完整 |
| 70-89 | good | 主要模块可用 |
| 40-69 | partial | 部分模块缺数据 |
| 1-39 | weak | 多数模块缺数据 |
| 0 | empty | 暂无真实业务数据 |

## 9. 异常提示设计

### 9.1 异常类型

| 异常 | 说明 | 示例文案 |
| --- | --- | --- |
| API不可用 | 请求失败或返回错误 | `Overview API 当前不可用` |
| 数据为空 | 模块无数据 | `Skill Center 暂无数据` |
| 数据过期 | 超过阈值未更新 | `Task Center 超过24小时未更新` |
| 模块未接入 | Meeting Room V1 未接入 | `Meeting Room 尚未接入真实数据` |
| 高风险 | high / critical 风险存在 | `Audit Center 存在高风险事项` |
| 安全字段异常 | 安全字段非预期 | `安全边界字段异常，请人工检查` |

### 9.2 异常列表字段

```json
{
  "severity": "warning",
  "module": "Meeting Room",
  "type": "not_connected",
  "message": "Meeting Room 尚未接入真实数据",
  "action_hint": "仅提示人工检查，不自动处理"
}
```

### 9.3 严重级别

| 级别 | 含义 |
| --- | --- |
| info | 正常提示 |
| warning | 需要关注 |
| high | 高风险，需要人工检查 |
| critical | 严重异常，必须人工处理 |

## 10. 安全边界

Health Center 只能：

- 查看健康状态。
- 展示连接状态。
- 展示更新时间。
- 展示异常提示。
- 展示数据完整度评分。

Health Center 禁止：

- 自动修复。
- 自动重启服务。
- 自动执行任务。
- 自动创建任务。
- 自动修改 Task Center 状态。
- 自动修改员工权限。
- 自动修改技能。
- 自动训练模型。
- 调用 Execution Engine。
- 接入 OpenClaw。
- 接入 n8n。

高风险提示必须保留：

```text
boss_confirm=true
security_audited=true
```

## 11. 页面交互设计

按钮白名单：

- 查看
- 进入
- 刷新页面

禁止按钮：

- 修复
- 重启
- 执行
- 自动处理
- 创建任务
- 修改权限
- 接入外部平台

刷新说明：

- V1 可依赖浏览器刷新。
- 如果后续设计“刷新”按钮，只能重新 GET 当前只读 API，不能触发修复或执行。

## 12. 后续开发拆分建议

### Sprint62.19-B 页面骨架

新增：

```text
frontend/ai-employee-health.html
tests/test_ai_employee_health.py
```

验收：

- 页面存在。
- 包含数据更新时间、API健康、模块连接、完整度评分、异常提示。
- 无自动修复、自动重启、执行入口。

### Sprint62.19-C 真实数据接入

接入：

```http
GET /api/ai-employee-ecosystem/overview
GET /api/health
```

验收：

- 加载状态正常。
- 空状态正常。
- 错误状态正常。
- 单模块异常可展示。

### Sprint62.19-D 安全验收

检查：

- 无 Execution Engine。
- 无 OpenClaw。
- 无 n8n。
- 无自动执行。
- 无自动修复。
- 无数据库变化。

## 13. 验收标准

设计阶段通过条件：

- 已定义 AI Employee Health Center 产品定位。
- 已覆盖数据更新时间监控。
- 已覆盖 API 健康状态。
- 已覆盖 7 个模块连接状态。
- 已定义数据完整度评分。
- 已定义异常提示模型。
- 已明确安全边界。
- 未写代码。
- 未修改数据库。
- 未创建 migration。
- 未接 Execution Engine / OpenClaw / n8n。
