# Sprint62.19-C AI Employee Health 前端产品设计

文档名称：《AI Employee Health Center 前端页面设计 V1》

阶段：Sprint62.19-C

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做前端产品设计。

禁止事项：

- 不写代码
- 不创建 HTML 页面
- 不修改前端
- 不修改后端
- 不新增 API
- 不创建数据库
- 不创建 migration
- 不接 OpenClaw
- 不接 n8n
- 不接 Execution Engine
- 不自动修复
- 不自动重启
- 不自动执行任务

目标页面：

```text
frontend/ai-employee-health.html
```

页面定位：

AI Employee Health Center 是 AI员工生态的只读健康监控页面，用于让 Boss 查看 AI员工生态各模块的连接状态、API状态、数据更新时间、异常记录和风险等级。

## 2. 页面目标

页面回答 6 个问题：

1. AI员工生态当前整体健康吗？
2. AI员工数量和状态是否正常？
3. 哪些模块已连接，哪些模块异常或未接入？
4. 哪些 API 可用，哪些 API 异常？
5. 各模块数据最近什么时候更新？
6. 有哪些异常需要人工关注？

页面不提供：

- 自动修复按钮
- 自动重启按钮
- 自动执行按钮
- 自动创建任务入口
- 自动修改权限入口
- Execution Engine 入口
- OpenClaw 入口
- n8n 入口

## 3. 数据来源

唯一前端数据来源：

```http
GET /api/ai-employee-health/overview
```

前端只读取该接口，不直接调用各业务模块 API。

接口期望返回：

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

安全字段必须展示或在页面安全检查中验证：

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

## 4. 页面信息架构

```text
AI Employee Health Center
├── 顶部状态栏
│   ├── 标题
│   ├── 当前组织
│   ├── readonly 模式
│   ├── 总健康状态
│   └── 最近检查时间
├── 总健康评分
│   ├── 总分
│   ├── 状态说明
│   ├── 异常数量
│   └── 安全边界提示
├── AI员工数量状态
│   ├── 员工总数
│   ├── working
│   ├── idle
│   ├── frozen
│   └── offline / unknown
├── 模块健康地图
│   ├── AI Workforce
│   ├── Skill Center
│   ├── Memory Center
│   ├── Growth Center
│   ├── Audit Center
│   ├── AI Meeting Room
│   └── Task Center
├── API健康状态
│   ├── API路径
│   ├── 可用状态
│   ├── HTTP状态码
│   ├── 响应耗时
│   └── 最近检查时间
├── 数据更新时间
│   ├── 数据域
│   ├── 最近更新时间
│   ├── 新鲜度状态
│   └── 过期说明
├── 异常记录列表
│   ├── 异常级别
│   ├── 异常类型
│   ├── 所属模块
│   ├── 异常说明
│   └── 是否需要 Boss 确认
└── 风险等级展示
    ├── low
    ├── medium
    ├── high
    └── unknown
```

## 5. 页面布局设计

### 5.1 顶部状态栏

展示：

- `AI Employee Health Center`
- 当前组织：`天统AI`
- 当前模式：`readonly`
- 总健康状态：`healthy / degraded / unavailable`
- 最近检查时间：来自 `generated_at`

视觉规则：

- readonly 使用稳定蓝色或灰蓝色标签
- 不使用警告色表达正常只读状态
- 状态文字短，不占用主要内容区

### 5.2 总健康评分

展示字段：

- `overall_score`
- `status`
- `alert_count`
- `score.module_score`
- `score.api_score`
- `score.freshness_score`
- `score.security_score`

建议结构：

```text
总健康评分：82 / 100
当前状态：degraded
异常数量：2
模块连接：80
API可用：100
数据新鲜度：70
安全边界：100
```

状态展示：

| 状态 | 展示 |
|---|---|
| healthy | 健康 |
| degraded | 需关注 |
| unavailable | 不可用 |
| unknown | 暂无数据 |

### 5.3 AI员工数量状态

数据来源：

- 优先从 Health API 的 `modules` 中读取 `ai_workforce`
- 如果后端返回扩展字段 `employees`，前端可读取员工状态分布

展示字段：

- 员工总数
- working
- idle
- frozen
- offline

无数据时：

```text
暂无员工状态数据
```

禁止：

- 不提供创建员工按钮
- 不提供启动员工按钮
- 不提供冻结/恢复按钮

### 5.4 模块健康地图

模块卡片字段：

- 模块名称：`module_name`
- 模块状态：`status`
- 数据数量：`count`
- 风险等级：`risk_level`
- 最近更新时间：`last_updated`
- 数据来源：`source`
- 说明：`message`

模块清单：

- AI Workforce Center
- Skill Center
- Memory Center
- Growth Center
- Audit Center
- AI Meeting Room
- Task Center

状态映射：

| 后端状态 | 前端显示 | 颜色 |
|---|---|---|
| connected | 已连接 | green |
| empty | 暂无数据 | gray |
| degraded | 需关注 | yellow |
| unavailable | 不可用 | red |
| not_connected | 未接入 | gray |
| unknown | 未知 | gray |

交互限制：

- 卡片可查看详情说明
- 不提供修复按钮
- 不提供重试执行按钮
- 不提供重启模块按钮

### 5.5 API健康状态

展示字段：

- `path`
- `status`
- `http_status`
- `latency_ms`
- `last_checked_at`
- `readonly`
- `error_message`

状态映射：

| 状态 | 展示 |
|---|---|
| available | 可用 |
| degraded | 部分异常 |
| unavailable | 不可用 |
| not_checked | 未检查 |

错误展示规则：

- 只展示脱敏后的 `error_message`
- 不展示 token
- 不展示环境变量
- 不展示数据库连接串
- 不展示完整堆栈

### 5.6 数据更新时间

展示字段：

- `data_name`
- `last_updated`
- `freshness_status`
- `age_minutes`
- `threshold_minutes`
- `message`

状态映射：

| 状态 | 展示 |
|---|---|
| fresh | 最新 |
| stale | 已过期 |
| empty | 暂无数据 |
| unavailable | 数据不可用 |
| not_connected | 未接入 |

时间为空时：

```text
暂无更新时间
```

### 5.7 异常记录列表

展示字段：

- `level`
- `type`
- `module_key`
- `title`
- `message`
- `detected_at`
- `requires_boss_confirm`
- `security_audited_required`

异常级别展示：

| level | 展示 | 处理方式 |
|---|---|---|
| info | 提示 | 只展示 |
| warning | 需关注 | 只展示 |
| high | 高风险 | 显示需 Boss 确认和安全审计 |

重要限制：

- `action_available=false` 时不展示任何处理按钮
- high 异常只显示 `需要 Boss 确认`、`需要安全审计`
- 不提供“一键修复”
- 不提供“立即处理”
- 不提供“自动执行”

### 5.8 风险等级展示

风险等级来源：

- `modules[].risk_level`
- `alerts[].level`
- `security` 字段

风险展示：

- `low`：低风险
- `medium`：中风险
- `high`：高风险，需要审核
- `unknown`：未知

当安全字段异常时：

```text
安全边界异常：需要 security_audited=true + boss_confirm=true
```

## 6. 页面状态设计

### 6.1 加载状态

显示：

```text
正在读取 AI员工生态健康状态...
```

禁止：

- 加载中触发重试任务
- 加载中调用执行类接口

### 6.2 空数据状态

当接口可用但无业务数据：

```text
当前未接入真实业务数据
```

模块级空数据：

```text
暂无数据
```

### 6.3 错误状态

当 `/api/ai-employee-health/overview` 请求失败：

```text
当前数据暂不可用
```

页面仍展示：

- 标题
- readonly 模式
- 安全提示
- 空模块结构

禁止：

- 自动修复
- 自动重启
- 自动调用其他执行系统

### 6.4 部分模块异常

处理方式：

- 正常模块继续展示
- 异常模块显示 `不可用`
- 异常列表展示对应记录
- 总健康状态可降级为 `degraded`

## 7. 视觉设计规范

沿用企业大脑总控台和 AI员工工作台的风格：

- 信息密度适中
- 以状态卡片、表格、列表为主
- 不做营销型 hero 页面
- 不使用执行型主按钮
- 不使用夸张装饰

颜色建议：

| 用途 | 颜色语义 |
|---|---|
| healthy / connected / available | green |
| degraded / stale / warning | yellow |
| unavailable / high | red |
| empty / not_connected / unknown | gray |
| readonly | blue-gray |

## 8. 前端组件规划

未来实现时建议拆分为页面内模块，避免引入复杂前端架构：

```text
HealthHeader
HealthScorePanel
EmployeeStatusPanel
ModuleHealthGrid
ApiHealthTable
DataFreshnessList
AlertRecordList
SecurityBoundaryPanel
EmptyState
ErrorState
```

V1 可在单 HTML 文件内实现，保持与现有静态页面风格一致。

## 9. 数据映射设计

### 9.1 HealthScorePanel

读取：

- `overall_score`
- `status`
- `score`
- `alert_count`

默认值：

- 分数：0
- 状态：`unknown`
- 异常：0

### 9.2 ModuleHealthGrid

读取：

- `modules[]`

默认值：

- 空数组
- 显示“暂无模块健康数据”

### 9.3 ApiHealthTable

读取：

- `apis[]`

默认值：

- 空数组
- 显示“暂无 API 健康数据”

### 9.4 DataFreshnessList

读取：

- `freshness[]`

默认值：

- 空数组
- 显示“暂无更新时间数据”

### 9.5 AlertRecordList

读取：

- `alerts[]`

默认值：

- 空数组
- 显示“暂无异常记录”

### 9.6 SecurityBoundaryPanel

读取：

- `security.readonly`
- `security.auto_repair_enabled`
- `security.auto_execute_enabled`
- `security.execution_engine_called`
- `security.openclaw_connected`
- `security.n8n_connected`

正常状态：

```text
只读模式已开启，未连接执行系统。
```

异常状态：

```text
安全边界异常，需要人工安全审计。
```

## 10. 安全边界设计

页面必须显示或隐式校验：

```text
readonly=true
auto_repair_enabled=false
auto_execute_enabled=false
execution_engine_called=false
openclaw_connected=false
n8n_connected=false
```

页面禁止出现以下文字作为操作入口：

- 执行
- 自动执行
- 启动
- 自动修复
- 自动重启
- 安装
- 升级
- 授权
- 修改权限
- 调用 Execution Engine
- 连接 OpenClaw
- 连接 n8n

说明性文字可以出现，但不得以按钮、链接、表单提交入口形式出现。

## 11. 测试方案

未来实现时建议新增：

```text
tests/test_ai_employee_health_frontend.py
```

测试项：

1. `frontend/ai-employee-health.html` 文件存在
2. 页面包含 `AI Employee Health Center`
3. 页面包含 `readonly`
4. 页面包含 `/api/ai-employee-health/overview`
5. 页面包含总健康评分区域
6. 页面包含模块健康地图区域
7. 页面包含 API健康状态区域
8. 页面包含数据更新时间区域
9. 页面包含异常记录列表区域
10. 页面包含风险等级展示区域
11. 页面包含空数据文案
12. 页面包含错误状态文案
13. 页面不包含执行按钮
14. 页面不包含自动修复按钮
15. 页面不包含自动重启按钮
16. 页面不包含 OpenClaw 入口
17. 页面不包含 n8n 入口
18. 页面不包含 Execution Engine 入口

建议联动测试：

- API 返回空数据时页面显示空状态
- API 请求失败时页面显示错误状态
- `security.execution_engine_called=false`
- `security.openclaw_connected=false`
- `security.n8n_connected=false`

## 12. Sprint62.19 后续拆分建议

### Sprint62.19-D

实现 AI Employee Health 后端 API。

范围：

- 新增只读 router/service
- 新增 API 测试
- 不修改数据库

### Sprint62.19-E

实现 AI Employee Health 前端页面。

范围：

- 新增 `frontend/ai-employee-health.html`
- 接入 `/api/ai-employee-health/overview`
- 实现加载、空数据、错误状态

### Sprint62.19-F

安全验收。

范围：

- 检查无执行入口
- 检查无 OpenClaw/n8n/Execution Engine 接入
- Docker Python 3.12 测试

## 13. 验收结论

Sprint62.19-C 已完成 AI Employee Health Center 前端产品设计。

本设计满足：

- 只读展示
- 数据来源统一为 `GET /api/ai-employee-health/overview`
- 覆盖总健康评分
- 覆盖 AI员工数量状态
- 覆盖模块健康地图
- 覆盖 API健康状态
- 覆盖数据更新时间
- 覆盖异常记录列表
- 覆盖风险等级展示
- 不提供自动修复、自动重启、自动执行入口
- 不接 Execution Engine
- 不接 OpenClaw
- 不接 n8n

等待确认后，方可进入后续开发阶段。
