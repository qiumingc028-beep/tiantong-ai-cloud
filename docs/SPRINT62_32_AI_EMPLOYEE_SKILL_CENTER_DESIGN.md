# Sprint62.32 AI员工技能中心设计文档

文档名称：《Sprint62.32 AI员工技能中心设计文档》

阶段：Sprint62.32

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做产品设计。

禁止事项：

- 不写代码
- 不修改前端
- 不修改后端
- 不修改数据库
- 不创建 migration
- 不接入 Execution Engine
- 不接入 OpenClaw
- 不接入 n8n
- 不自动调用技能
- 不自动安装技能
- 不自动升级技能
- 不自动修改员工权限

Sprint62.32 只设计 AI Workforce Center 的 Skill Center 视图，不进入开发。

## 2. 产品定位

AI员工技能中心是 AI Workforce Center 的能力资产视图。

目标：

- 让老板查看每个 AI员工拥有的技能资产。
- 让老板理解技能属于谁、当前版本、使用效果、风险等级和最近更新情况。
- 将 Skill Center 从“技能资产库”扩展为“员工技能资产视图”。
- 为后续员工能力评估、任务分配、风险审计提供只读依据。

定位边界：

- AI员工技能中心只展示技能资产。
- 技能资产不等于执行权限。
- 技能版本不等于自动升级。
- 技能成功率不等于自动授权。
- 技能风险提示不等于自动处置。

核心原则：

```text
技能 ≠ 权限
能力 ≠ 执行许可
查看 ≠ 调用
高风险技能必须 security_audited=true + boss_confirm=true
```

## 3. 页面结构

建议页面：

```text
frontend/ai-employee-skill-center.html
```

也可作为 AI Workforce Center 内部标签页：

```text
frontend/ai-workforce-center.html#skills
```

### 3.1 页面总览

```text
AI员工技能中心
├── 顶部状态栏
│   ├── AI员工技能中心
│   ├── 当前组织
│   ├── 员工数量
│   ├── 技能数量
│   └── readonly安全模式
├── 技能资产总览
│   ├── 技能总数
│   ├── 已绑定员工数
│   ├── 高风险技能数
│   ├── 平均成功率
│   └── 最近更新时间
├── 员工技能矩阵
│   ├── AI员工
│   ├── 所属部门
│   ├── 拥有技能
│   ├── 技能版本
│   ├── 使用次数
│   ├── 成功率
│   ├── 风险等级
│   └── 详情入口
├── 筛选区
│   ├── 员工筛选
│   ├── 部门筛选
│   ├── 技能分类筛选
│   ├── 风险等级筛选
│   └── 技能版本筛选
└── 安全边界
    ├── 技能只读展示
    ├── 禁止自动调用技能
    ├── 禁止自动安装技能
    ├── 禁止自动升级技能
    └── 禁止自动进入执行系统
```

### 3.2 技能资产总览卡片

展示：

| 卡片 | 说明 |
|---|---|
| 技能总数 | 所有员工关联技能数量去重后的总数 |
| 员工覆盖 | 至少拥有一个技能的员工数量 |
| 高风险技能 | `risk_level=high/critical` 的技能数量 |
| 平均成功率 | 根据使用成功次数 / 使用次数只读计算 |
| 最近更新时间 | 技能资产或使用记录最近更新时间 |

### 3.3 员工技能矩阵

矩阵字段：

| 字段 | 说明 |
|---|---|
| 技能名称 | 技能资产名称 |
| 所属员工 | 拥有或适用该技能的 AI员工 |
| 所属部门 | 员工所在部门 |
| 技能版本 | 当前绑定版本，如 `v1.0`、`v1.1`、`v2.0` |
| 使用次数 | 该员工使用该技能的历史次数 |
| 成功率 | 成功次数 / 使用次数 |
| 更新时间 | 技能或使用记录最近更新时间 |
| 风险等级 | low / medium / high / critical |
| 审计状态 | 是否需要安全审计 |

### 3.4 员工技能详情抽屉

点击某一行后展示只读详情：

```text
员工技能详情
├── 员工基础信息
│   ├── 员工名称
│   ├── 员工编号
│   ├── 所属部门
│   └── 当前状态
├── 技能基础信息
│   ├── 技能名称
│   ├── 技能版本
│   ├── 技能说明
│   └── 技能状态
├── 使用表现
│   ├── 使用次数
│   ├── 成功次数
│   ├── 失败次数
│   ├── 成功率
│   └── 最近任务
├── 关联资产
│   ├── SOP
│   ├── Prompt
│   ├── 知识文章
│   └── Memory案例
└── 风险审计
    ├── 风险等级
    ├── 最近风险
    ├── 审计记录
    └── 是否需要 Boss 确认
```

详情入口只允许：

- 查看员工
- 查看技能
- 查看审计

禁止：

- 调用技能
- 安装技能
- 升级技能
- 修改权限
- 执行任务

## 4. 数据结构设计

### 4.1 SkillAsset 员工技能资产视图

只设计，不建表。

```json
{
  "skill_asset_id": "employee_skill_tianshang_jd_operation_v1",
  "skill_id": "jd_operation_skill",
  "skill_name": "京东运营技能",
  "skill_category": "business",
  "skill_version": "v1.0",
  "skill_status": "approved",
  "employee_id": "tianshang",
  "employee_name": "天商",
  "department": "业务部门",
  "usage_count": 0,
  "success_count": 0,
  "failure_count": 0,
  "success_rate": null,
  "last_used_at": null,
  "updated_at": null,
  "risk_level": "medium",
  "audit_status": "readonly",
  "security_audited": false,
  "boss_confirm": false,
  "readonly": true
}
```

### 4.2 EmployeeSkillSummary 员工技能摘要

```json
{
  "employee_id": "tianshang",
  "employee_name": "天商",
  "department": "业务部门",
  "skill_total": 3,
  "high_risk_skill_count": 0,
  "average_success_rate": null,
  "last_updated": null,
  "skills": [
    {
      "skill_name": "京东运营技能",
      "skill_version": "v1.0",
      "usage_count": 0,
      "success_rate": null,
      "risk_level": "medium"
    }
  ]
}
```

### 4.3 SkillUsageMetric 技能使用指标

```json
{
  "skill_id": "jd_operation_skill",
  "employee_id": "tianshang",
  "usage_count": 12,
  "success_count": 9,
  "failure_count": 3,
  "success_rate": 0.75,
  "last_task_id": 101,
  "last_used_at": "2026-07-10T10:00:00+08:00",
  "source": "Task Center / Audit Center readonly aggregate"
}
```

### 4.4 风险等级字段

风险等级：

```text
low
medium
high
critical
```

风险来源：

- 技能本身风险
- 员工历史失败记录
- Task Center 阻塞任务
- Audit Center 风险事件
- 是否涉及敏感知识或高风险 API

## 5. API需求分析

### 5.1 首期可复用 API

| 数据 | 现有 API | 用途 |
|---|---|---|
| 员工列表 | `GET /api/ai-workforce/overview` | 员工、部门、技能数量、风险等级 |
| 员工生态总览 | `GET /api/ai-employee-ecosystem/overview` | Skill / Memory / Growth / Audit / Task 汇总 |
| Skill Center | `GET /api/sop-skill-center/overview` | SOP / Skill 绑定状态 |
| Task Center | `GET /api/task-center/tasks` | 技能使用相关任务只读统计 |
| Health Center | `GET /api/ai-employee-health/overview` | 模块健康状态 |

### 5.2 API缺口

当前仍缺少统一员工技能资产 API。

建议后续设计：

```text
GET /api/ai-employee-skills/overview
```

返回：

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
  "employee_skills": [
    {
      "skill_name": "京东运营技能",
      "employee_name": "天商",
      "department": "业务部门",
      "skill_version": "v1.0",
      "usage_count": 0,
      "success_rate": null,
      "updated_at": null,
      "risk_level": "medium"
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

### 5.3 不允许的 API

禁止新增或调用：

- 自动调用技能 API
- 自动安装技能 API
- 自动升级技能 API
- 自动修改员工技能绑定 API
- 自动修改权限 API
- Execution Engine API
- OpenClaw API
- n8n API

## 6. 与现有模块关系

### 6.1 AI Workforce Center

关系：

- 提供员工入口、员工列表、员工详情跳转。
- 技能中心作为 AI Workforce Center 的能力资产标签页。
- 老板从员工卡片进入技能资产视图。

边界：

- 不改变员工状态。
- 不创建员工。
- 不修改员工权限。

### 6.2 Skill Center

关系：

- Skill Center 是技能资产来源。
- AI员工技能中心展示技能与员工之间的只读关系。
- 技能版本、风险等级、审核状态应优先从 Skill Center 获取。

边界：

- 不安装技能。
- 不升级技能。
- 不调用技能。

### 6.3 Task Center

关系：

- Task Center 提供技能使用次数、成功/失败结果、最近任务。
- 使用次数和成功率只做只读统计。

边界：

- 不创建任务。
- 不修改任务状态。
- 不触发任务执行。

### 6.4 Memory Center

关系：

- Memory Center 提供成功案例、失败案例和历史经验。
- 技能详情可展示关联经验和案例数量。

边界：

- 不自动学习。
- 不自动写入 Memory。
- 不自动修改技能评分。

### 6.5 Growth Center

关系：

- Growth Center 提供员工技能成长趋势和熟练度变化。
- 技能成功率可作为成长评价参考。

边界：

- 不自动晋升员工。
- 不自动调整技能熟练度。
- 不自动修改权限。

### 6.6 Audit Center

关系：

- Audit Center 提供技能风险、失败事件、安全审计记录。
- 高风险技能必须展示审计状态。

边界：

- 不自动处罚。
- 不自动封禁技能。
- 不自动调整员工权限。

## 7. 页面筛选与展示规则

筛选：

- 按员工筛选
- 按部门筛选
- 按技能名称搜索
- 按技能版本筛选
- 按风险等级筛选
- 按成功率区间筛选

排序：

- 风险等级从高到低
- 最近更新时间从新到旧
- 使用次数从高到低
- 成功率从低到高，用于发现问题技能

空数据：

- 无技能数据：显示 `暂无技能资产`
- 无使用次数：显示 `暂无使用记录`
- 无成功率：显示 `暂无成功率数据`
- API失败：显示 `当前数据不可用`

禁止：

- 生成假成功率
- 生成假使用次数
- 将前端 mock 结果写入后端

## 8. 安全要求

本设计必须保持：

- 不修改数据库
- 不创建 migration
- 不接入 Execution Engine
- 不接入 OpenClaw
- 不接入 n8n
- 不自动调用技能
- 不自动安装技能
- 不自动升级技能
- 不自动修改员工权限

高风险技能展示规则：

```json
{
  "risk_level": "high",
  "readonly": true,
  "security_audited_required": true,
  "boss_confirm_required": true,
  "auto_skill_call_enabled": false,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false
}
```

## 9. 后续开发建议

建议拆分：

1. Sprint62.33：AI员工技能中心前端只读骨架。
2. Sprint62.34：员工技能资产只读 API 设计。
3. Sprint62.35：员工技能资产只读 API 实现。
4. Sprint62.36：成功率、使用次数与 Audit/Task 只读聚合。

每一步都必须保持：

- 只读
- 不接执行系统
- 不修改数据库结构，除非单独设计并确认
- 不自动调用技能

## 10. 验收结论

Sprint62.32 已完成 AI员工技能中心产品设计。

本设计覆盖：

- 产品定位
- 页面结构
- 数据结构设计
- API需求分析
- 与 AI Workforce Center、Skill Center、Task Center、Memory Center、Growth Center、Audit Center 的关系
- 技能名称、所属员工、技能版本、使用次数、成功率、更新时间、风险等级展示设计
- 禁止修改数据库、创建 migration、接入 Execution Engine / OpenClaw / n8n、自动调用技能

等待确认后再进入开发。
