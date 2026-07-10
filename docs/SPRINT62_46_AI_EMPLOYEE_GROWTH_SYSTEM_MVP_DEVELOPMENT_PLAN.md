# Sprint62.46 AI员工成长系统 MVP 开发计划

文档名称：《AI员工成长系统 MVP 开发计划 V1》

阶段：Sprint62.46

状态：计划完成，等待确认

## 1. 阶段边界

Sprint62.46 目标是将 Sprint62.44 后端 MVP 和 Sprint62.45 前端展示设计推进到前端 MVP 开发阶段。

禁止事项：

- 不修改现有 Task Center 核心流程
- 不修改登录系统
- 不修改 Boss Dashboard
- 不接 Execution Engine
- 不接 OpenClaw
- 不接 n8n
- 不自动执行任务
- 不自动学习
- 不自动升级技能
- 不自动修改权限

安全原则：

```json
{
  "boss_confirm": true,
  "security_audited": true,
  "readonly": true
}
```

## 2. 新增文件

### 2.1 前端文件

新增：

```text
frontend/ai-employee-growth-system.html
```

用途：

- AI员工成长系统 MVP 只读页面。
- 展示 Growth 总览、员工成长列表、待 Boss 确认事项、Memory 候选、Audit 摘要。

### 2.2 测试文件

新增：

```text
tests/test_ai_employee_growth_system_frontend.py
```

用途：

- 检查页面存在。
- 检查只读模式。
- 检查安全边界文案。
- 检查不存在执行、升级、授权、自动学习入口。

### 2.3 验收报告

新增：

```text
docs/SPRINT62_46_ACCEPTANCE_REPORT.md
```

用途：

- 记录修改文件、测试结果、安全检查、风险结论、验收结果。

## 3. 后端 API 实现顺序

Sprint62.44 已完成第一阶段后端 API，本阶段原则上不新增后端 API。

已可复用 API：

```text
GET /api/ai-employee-growth-system/overview
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
GET /api/ai-employee-growth-system/tasks/{task_id}/impact
GET /api/ai-employee-growth-system/waiting-confirm
GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions
```

前端接入顺序：

1. 接入 `GET /api/ai-employee-growth-system/overview`
2. 接入 `GET /api/ai-employee-growth-system/waiting-confirm`
3. 接入 `GET /api/ai-employee-growth-system/employees/{employee_id}/profile`
4. 接入 `GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions`
5. 预留 `GET /api/ai-employee-growth-system/tasks/{task_id}/impact` 查看任务影响

后端限制：

- 不新增写接口。
- 不新增确认接口。
- 不新增执行接口。
- 不修改 Task Center。
- 不修改登录权限。

## 4. 前端页面实现顺序

### 4.1 页面骨架

实现：

- 顶部状态栏
- 左侧导航
- readonly 安全模式标识
- 数据加载状态
- 空数据状态
- 错误状态

显示：

```text
AI Employee Growth System
readonly安全模式
禁止自动执行
```

### 4.2 Growth 总览卡片

接入：

```text
GET /api/ai-employee-growth-system/overview
```

展示：

- 员工总数
- 可评估员工数
- 平均成长评分
- 高风险数量
- Memory 候选数量
- 待 Boss 确认数量

无数据：

```text
暂无成长数据
```

### 4.3 Boss 待确认区

接入：

```text
GET /api/ai-employee-growth-system/waiting-confirm
```

展示：

- 待确认任务
- 风险等级
- `boss_confirm_required`
- `security_audited_required`

限制：

- 只展示。
- 不提供确认按钮。
- 不提供执行按钮。

### 4.4 员工成长列表

从 overview 的 `top_growth_employees` 和员工统计信息开始展示。

字段：

- 员工名称
- 员工编号
- 成长评分
- 成长等级
- 风险状态
- 查看详情入口

说明：

- MVP 可先显示可评估员工 Top 列表。
- 后续再扩展为完整分页列表。

### 4.5 员工成长详情区

点击员工后接入：

```text
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions
```

展示：

- 成长评分
- 评分拆解
- 任务统计
- Audit 摘要
- Memory 摘要
- 技能提升建议

### 4.6 任务影响预留

点击任务或 Memory 候选时接入：

```text
GET /api/ai-employee-growth-system/tasks/{task_id}/impact
```

展示：

- 生命周期状态
- 是否计入 Growth 评分
- score_delta
- Audit 证据
- Memory 候选类型

MVP 可以先预留区域，不强制实现复杂弹层。

## 5. 测试方案

### 5.1 前端静态测试

新增：

```text
tests/test_ai_employee_growth_system_frontend.py
```

覆盖：

- `frontend/ai-employee-growth-system.html` 文件存在
- 页面包含 `AI Employee Growth System`
- 页面包含 `readonly`
- 页面包含 `Boss`
- 页面包含 `security_audited`
- 页面包含空数据文案
- 页面不存在 `执行任务`
- 页面不存在 `自动执行`
- 页面不存在 `自动学习`
- 页面不存在 `自动升级`
- 页面不存在 `修改权限`
- 页面不存在 `Execution Engine`
- 页面不存在 `OpenClaw`
- 页面不存在 `n8n`

### 5.2 后端回归测试

执行：

```text
pytest tests/test_ai_employee_growth_system.py
pytest tests/test_ai_workforce_task_flow.py
pytest tests/test_task_center.py
pytest tests/test_ai_workforce.py
```

目标：

- Growth System API 不回归。
- Task Center 不回归。
- AI Workforce 不回归。
- waiting_confirm 仍不计入正式评分。

### 5.3 安全测试

静态扫描：

```text
rg -n "Execution Engine|OpenClaw|n8n|自动执行|自动学习|自动升级|修改权限" frontend/ai-employee-growth-system.html
```

要求：

- 只允许出现在安全提示或禁止说明中。
- 不允许作为按钮、表单、API 调用、链接入口出现。

### 5.4 Docker Python 3.12 测试

执行：

```text
docker compose run --rm -v /Users/chenqiuming/Developer/tiantong-ai-cloud:/app backend python -m pytest tests/test_ai_employee_growth_system_frontend.py tests/test_ai_employee_growth_system.py tests/test_ai_workforce_task_flow.py tests/test_task_center.py tests/test_ai_workforce.py
```

## 6. 风险点

| 风险 | 说明 | 控制方式 |
|---|---|---|
| 前端误放执行按钮 | 成长建议可能被误解为操作入口 | 测试禁止执行、自动学习、自动升级文案作为按钮 |
| Boss确认被误实现为写操作 | MVP 只展示待确认事项 | 不新增确认 API，不提交 POST/PATCH |
| Task Center 被影响 | 成长页面读取任务状态 | 不修改 Task Center 文件和 API |
| 登录系统被影响 | 新页面可能复用登录逻辑不当 | 只复用现有 token/cookie 检查，不改登录 |
| Boss Dashboard 被污染 | 新入口可能误改总控台 | Sprint62.46 不改 Boss Dashboard |
| 无数据时造假 | 页面为美观填 mock 分数 | 空数据必须显示“暂无成长数据” |
| 执行系统误接入 | 前端调用执行相关接口 | 禁止调用 Execution Engine / OpenClaw / n8n |

## 7. 验收标准

Sprint62.46 通过条件：

- 新增 `frontend/ai-employee-growth-system.html`
- 新增 `tests/test_ai_employee_growth_system_frontend.py`
- 新增 `docs/SPRINT62_46_ACCEPTANCE_REPORT.md`
- 不修改 Task Center 核心逻辑
- 不修改登录系统
- 不修改 Boss Dashboard
- 不创建数据库表
- 不创建 migration
- 不接 Execution Engine
- 不接 OpenClaw
- 不接 n8n
- 不提供自动执行入口
- 不提供自动学习入口
- 不提供自动升级技能入口
- 页面能展示 Growth 总览
- 页面能展示 Boss 待确认事项
- 页面能处理空数据和错误状态
- pytest 通过

## 8. 开发顺序建议

1. 新增 `frontend/ai-employee-growth-system.html` 页面骨架。
2. 接入 overview API，渲染总览卡片。
3. 接入 waiting-confirm API，渲染待确认区。
4. 增加员工成长详情区，按员工加载 profile 和 skill-suggestions。
5. 增加空数据、加载、错误状态。
6. 新增前端测试。
7. 运行 Docker Python 3.12 pytest。
8. 生成 Sprint62.46 验收报告。

## 9. 结论

Sprint62.46 开发计划完成。

建议确认后进入 Sprint62.46-A：先实现独立 `ai-employee-growth-system.html` 只读页面，不改 Task Center、登录系统和 Boss Dashboard。
