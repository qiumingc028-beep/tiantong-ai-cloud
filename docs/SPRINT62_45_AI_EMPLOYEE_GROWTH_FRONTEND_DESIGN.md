# Sprint62.45 AI员工成长系统前端展示设计

文档名称：《AI Workforce Center 成长系统前端展示设计 V1》

阶段：Sprint62.45

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做前端产品与页面结构设计。

禁止事项：

- 不写代码
- 不修改前端
- 不修改后端
- 不修改数据库
- 不创建 migration
- 不接入 Execution Engine
- 不接入 OpenClaw
- 不接入 n8n
- 不自动执行
- 不自动学习
- 不自动升级技能
- 不自动修改权限

Sprint62.45 基于 Sprint62.44 已完成的只读后端 API，设计 AI Workforce Center 成长系统前端展示方案，保持 Boss 人工确认模式。

## 2. 产品定位

AI员工成长系统前端是 Boss 查看 AI员工成长状态、任务影响、技能建议、审计证据和经验沉淀的只读工作台。

定位：

```text
Boss 查看
↓
员工成长评分
↓
任务影响证据
↓
Audit记录
↓
Memory经验候选
↓
Growth建议
↓
Boss人工确认
```

前端只展示，不提供执行、升级、授权、自动学习入口。

## 3. 页面文件规划

### 3.1 新增页面建议

```text
frontend/ai-employee-growth-system.html
```

职责：

- Growth System 总览
- AI员工成长列表
- Boss 待确认成长事项
- 最近任务成长影响
- Memory / Audit 摘要

### 3.2 增强页面建议

```text
frontend/ai-employee-detail.html
```

职责：

- 在员工详情中增加成长档案区。
- 展示成长评分、技能建议、Memory 摘要、Audit 证据。

### 3.3 不修改页面

本设计阶段不修改任何页面。

后续 Sprint62.46 开发时仍应避免修改：

- `frontend/task-center.html`
- `frontend/enterprise-brain-console.html`
- 登录页面
- Boss Dashboard 核心结构

## 4. AI员工详情页结构

### 4.1 页面布局

```text
AI员工详情页
├── 顶部员工身份区
│   ├── 员工名称
│   ├── 员工编号
│   ├── 部门
│   ├── 岗位
│   ├── 状态
│   └── 风险等级
├── 左侧页内导航
│   ├── 基础信息
│   ├── 技能能力
│   ├── 任务记录
│   ├── 成长评分
│   ├── Audit记录
│   ├── Memory经验
│   └── Growth建议
├── 中间主内容
│   ├── 成长评分卡片
│   ├── 评分拆解
│   ├── 任务影响列表
│   ├── 技能建议
│   ├── Memory候选
│   └── Audit证据链
└── 右侧安全状态
    ├── readonly模式
    ├── Boss确认要求
    ├── 安全审计要求
    └── 禁止自动执行提示
```

### 4.2 顶部员工身份区

展示字段：

- 员工名称
- 员工编号
- 部门
- 岗位
- 当前状态
- 风险等级
- 当前成长等级
- 最近评价时间

空数据：

```text
暂无员工成长数据
```

错误状态：

```text
当前数据暂不可用
```

## 5. 成长评分展示

### 5.1 成长评分卡片

展示：

- 综合成长评分
- 成长等级
- 是否可评估
- 评分来源
- 最近更新时间

状态设计：

| 状态 | 展示 |
|---|---|
| `available=true` | 显示分数、等级、趋势 |
| `available=false` | 显示“暂无成长数据” |
| API失败 | 显示“当前数据暂不可用” |
| waiting_confirm | 显示“待Boss确认，不计入正式评分” |

### 5.2 评分拆解

来自：

```text
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
```

展示字段：

- 任务完成率评分
- 任务质量评分
- 成功率评分
- 用户评价评分
- 技能效果评分
- 风险扣分

视觉建议：

- 使用横向指标条。
- 风险扣分使用红色或橙色 tag。
- 不使用复杂图表，MVP 保持信息密集和稳定。

### 5.3 成长状态颜色

| 状态 | 颜色建议 | 说明 |
|---|---|---|
| excellent | 绿色 | 表现优秀 |
| stable | 蓝色 | 稳定 |
| needs_review | 橙色 | 需要复核 |
| high_risk | 红色 | 高风险 |
| no_data | 灰色 | 暂无数据 |

## 6. 技能展示

### 6.1 技能摘要

展示：

- 技能总数
- 低成功率技能
- 高风险技能
- 最近使用技能
- 技能建议数量

数据来源：

- `GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions`
- 未来可联动 `GET /api/ai-employee-skills/employees/{employee_id}/skills`

### 6.2 技能建议列表

字段：

- 建议类型
- 技能名称
- 建议标题
- 建议原因
- 风险等级
- 状态
- Boss确认要求
- 安全审计要求

禁止按钮：

- 不显示“升级技能”
- 不显示“安装技能”
- 不显示“执行技能”
- 不显示“自动优化”

允许入口：

- 查看技能详情
- 查看任务证据
- 查看审计记录

## 7. Audit记录展示

### 7.1 Audit摘要卡片

数据来源：

```text
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
```

展示：

- 审计事件数量
- 高风险数量
- Boss确认次数
- 安全审计次数
- 最近审计事件

### 7.2 Audit证据链

展示字段：

- 事件时间
- 任务ID
- action
- from_status
- to_status
- 风险等级
- 是否 Boss 确认

空状态：

```text
暂无审计记录
```

边界：

- Audit 只展示。
- 不提供自动修复。
- 不提供自动处罚。
- 不提供权限调整。

## 8. Memory经验展示

### 8.1 Memory摘要

展示：

- 成功案例候选数量
- 失败案例候选数量
- 待确认经验候选数量
- 最近 Memory 候选

数据来源：

```text
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
```

### 8.2 Memory候选列表

字段：

- 任务ID
- 任务标题
- 候选类型
- 状态
- 风险等级
- Boss确认要求
- 安全审计要求

类型：

- success_case
- failure_case
- pending_review
- task_memory

禁止：

- 不显示“自动学习”
- 不显示“加入正式知识库”
- 不显示“自动生成SOP”
- 不显示“自动训练”

允许：

- 查看候选
- 查看来源任务
- 查看审计证据

## 9. Growth建议展示

### 9.1 Growth建议区

展示：

- 技能提升建议
- 风险复盘建议
- 待 Boss 确认事项
- 高风险提醒

数据来源：

- `GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions`
- `GET /api/ai-employee-growth-system/waiting-confirm`

### 9.2 建议卡片

字段：

- 建议标题
- 建议类型
- 原因
- 关联技能
- 风险等级
- 状态
- Boss确认要求
- 安全审计要求

按钮策略：

- MVP 不提供确认写按钮。
- 只提供“查看详情”入口。
- “确认 / 执行 / 升级 / 授权”均不出现。

## 10. Growth System 总览页设计

### 10.1 顶部状态栏

展示：

- AI Employee Growth System
- 当前组织
- readonly安全模式
- 当前数据状态
- Sprint62.45 / Sprint62.46 标识

### 10.2 总览卡片

数据来源：

```text
GET /api/ai-employee-growth-system/overview
```

卡片：

- 员工总数
- 可评估员工
- 平均成长评分
- 高风险成长事件
- Memory候选
- 待Boss确认

### 10.3 员工成长列表

字段：

- 员工名称
- 部门
- 成长评分
- 成长等级
- 任务完成率
- 成功率
- 风险数量
- 最近任务时间

操作：

- 查看员工详情
- 查看成长档案

禁止：

- 执行
- 升级
- 授权
- 自动学习

### 10.4 Boss待确认区

展示：

- waiting_confirm 任务结果
- 待复盘失败任务
- 待确认 Memory 候选
- 待确认技能建议

说明：

- MVP 只展示，不提交确认。
- 后续如要支持确认，必须单独设计审批 API，且保留 `boss_confirm=true` 和 `security_audited=true`。

## 11. API调用规划

### 11.1 页面初始化

Growth System 总览页：

```text
GET /api/ai-employee-growth-system/overview
GET /api/ai-employee-growth-system/waiting-confirm
```

员工详情成长区：

```text
GET /api/ai-employee-growth-system/employees/{employee_id}/profile
GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions
```

任务影响弹层：

```text
GET /api/ai-employee-growth-system/tasks/{task_id}/impact
```

### 11.2 加载状态

页面加载时：

```text
正在加载成长数据...
```

### 11.3 空数据状态

API 返回 `available=false`：

```text
暂无成长数据
```

### 11.4 错误状态

API 请求失败：

```text
当前数据暂不可用
```

### 11.5 权限状态

403：

```text
当前账号无权查看成长系统
```

401：

```text
请先登录
```

## 12. 安全边界

前端必须明确：

```text
readonly安全模式
只读展示
成长评分不等于权限
技能建议不等于技能升级
Memory候选不等于自动学习
Boss确认不等于自动执行
```

页面禁止出现：

- 执行任务
- 自动执行
- 自动学习
- 自动升级技能
- 自动授权
- 修改权限
- 接入 Execution Engine
- 接入 OpenClaw
- 接入 n8n

高风险展示必须包含：

```text
boss_confirm_required=true
security_audited_required=true
```

## 13. Sprint62.46 开发拆分

### Sprint62.46-A Growth System 前端页面 MVP

目标：

- 新增 `frontend/ai-employee-growth-system.html`
- 接入：
  - `/api/ai-employee-growth-system/overview`
  - `/api/ai-employee-growth-system/waiting-confirm`
- 展示总览卡片、待确认列表、空数据和错误状态。

测试：

- 新增 `tests/test_ai_employee_growth_system_frontend.py`
- 检查页面存在、readonly、安全文案、禁止按钮。

### Sprint62.46-B 员工详情页成长区增强

目标：

- 增强 `frontend/ai-employee-detail.html`
- 接入：
  - `/api/ai-employee-growth-system/employees/{employee_id}/profile`
  - `/api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions`
- 展示成长评分、Audit、Memory、Growth建议。

限制：

- 不改变员工业务逻辑。
- 不增加执行按钮。

### Sprint62.46-C 任务成长影响展示

目标：

- 在成长页面或员工详情页支持查看任务影响。
- 接入：
  - `/api/ai-employee-growth-system/tasks/{task_id}/impact`

展示：

- 任务状态
- 是否计入评分
- score_delta
- Audit证据
- Memory候选类型

### Sprint62.46-D 前端验收与安全检查

目标：

- Docker Python 3.12 执行 pytest。
- 检查无执行入口。
- 检查无 OpenClaw / n8n / Execution Engine。
- 检查空数据、错误状态、权限状态。
- 输出 `docs/SPRINT62_46_ACCEPTANCE_REPORT.md`。

## 14. 验收标准

Sprint62.45 通过标准：

- 只新增设计文档。
- 不修改代码。
- 不修改数据库。
- 不创建 migration。
- 不接入 Execution Engine。
- 不接入 OpenClaw。
- 不接入 n8n。
- 明确员工详情页结构。
- 明确成长评分、技能、Audit、Memory、Growth建议展示。
- 明确 API 调用规划。
- 明确 Sprint62.46 开发拆分。
- 保持 Boss 人工确认模式。

## 15. 结论

Sprint62.45 完成 AI员工成长系统前端展示设计。

下一阶段建议进入 Sprint62.46-A，先实现独立 Growth System 只读页面，再逐步增强员工详情页成长区。
