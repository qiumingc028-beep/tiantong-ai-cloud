# Sprint62.28 AI Workforce Center 前端实现方案设计

文档名称：《AI Workforce Center 前端实现方案 V1》

阶段：Sprint62.28

状态：设计完成，等待确认

## 1. 阶段边界

本阶段只做前端实现方案设计。

禁止事项：

- 不写代码
- 不修改已有页面
- 不修改 Boss Dashboard
- 不修改 Task Center
- 不修改登录系统
- 不修改后端业务逻辑
- 不创建数据库
- 不创建 migration
- 不接入 Execution Engine
- 不接入 OpenClaw
- 不接入 n8n
- 不自动执行任务
- 不自动创建任务
- 不自动修改权限

本方案基于：

- `docs/SPRINT62_27_AI_WORKFORCE_CENTER_DESIGN.md`
- `docs/SPRINT62_16_AI_EMPLOYEE_FRONTEND_IMPLEMENTATION_PLAN.md`
- 当前已有 `frontend/ai-workforce.html`
- 当前已有只读 API：`/api/ai-workforce/overview`、`/api/ai-employee-ecosystem/overview`

## 2. 实现目标

目标页面：

```text
frontend/ai-workforce.html
```

定位：

AI Workforce Center 是 AI员工数字办公室首页，负责统一展示员工、能力、任务、知识、记忆、成长、审计、权限、安全状态。

V1 实现原则：

- 保持独立页面，不改已有页面。
- 复用现有静态 HTML + 页面内 CSS/JS 风格。
- 优先复用已有只读 API。
- API 失败或无数据时显示空状态。
- 所有入口只允许查看或进入。
- 不增加执行、授权、升级、安装、自动运行按钮。

## 3. 页面目录结构

本阶段规划不新增目录。

继续使用当前前端结构：

```text
frontend/
├── ai-workforce.html
├── ai-employee-detail.html
├── ai-employee-capability.html
├── ai-employee-dashboard.html
├── ai-employee-memory.html
├── ai-employee-growth.html
├── ai-employee-health.html
├── skill-center.html
├── skill-detail.html
├── knowledge-center.html
├── tiancang.html
├── task-center.html
├── enterprise-brain-console.html
└── deploy-center.html
```

后续开发只允许增强：

```text
frontend/ai-workforce.html
```

不修改：

- `frontend/index.html`
- `frontend/enterprise-brain-console.html`
- `frontend/task-center.html`
- `frontend/login.html`
- 其他既有业务页面

## 4. frontend 文件规划

### 4.1 本阶段目标文件

| 文件 | 用途 | 是否修改 |
|---|---|---|
| `frontend/ai-workforce.html` | AI Workforce Center 页面 | 后续开发阶段允许最小修改 |
| `docs/SPRINT62_28_AI_WORKFORCE_FRONTEND_PLAN.md` | 本实现方案 | 当前新增 |

### 4.2 只读链接页面

AI Workforce Center 可链接到以下已有页面：

| 页面 | 用途 | 连接方式 |
|---|---|---|
| `ai-employee-detail.html` | 员工详情 | 查看员工 |
| `ai-employee-capability.html` | 能力中心 | 查看能力 |
| `ai-employee-memory.html` | 记忆中心 | 查看记忆 |
| `ai-employee-growth.html` | 成长中心 | 查看成长 |
| `ai-employee-health.html` | 健康状态 | 查看健康 |
| `skill-center.html` | 技能中心 | 查看技能 |
| `knowledge-center.html` / `tiancang.html` | 知识中心 | 查看知识 |
| `task-center.html` | 任务中心 | 只读跳转查看 |
| `enterprise-brain-console.html` | 企业大脑总控台 | 返回总控台 |

链接白名单文案：

- 查看
- 进入
- 查看详情
- 返回总控台

禁止出现：

- 执行
- 启动
- 自动运行
- 升级
- 授权
- 安装
- 调用
- 修复

## 5. 页面组件划分

当前项目以单页 HTML、内联 CSS、内联 JS 为主。后续实现保持该风格，先不抽公共组件文件，避免重构。

### 5.1 顶部状态栏组件

展示：

- AI Workforce Center
- 当前组织
- AI员工数量
- 系统状态
- readonly安全模式
- 当前用户角色

数据来源：

- `/api/me`
- `/api/ai-workforce/overview`
- `/api/ai-employee-ecosystem/overview`

异常状态：

- 用户未登录：沿用现有登录跳转逻辑。
- API失败：显示“当前数据不可用”。
- 无数据：显示“暂无数据”。

### 5.2 左侧导航组件

导航项：

- 员工大厅
- 员工详情
- 技能能力
- 知识资产
- 任务中心
- 记忆中心
- 成长中心
- 风险审计
- 权限范围
- 安全策略

实现方式：

- 页面内锚点跳转。
- 外部页面只作为只读查看入口。
- 不新增执行中心入口。

### 5.3 概览指标卡组件

卡片：

- 员工数量
- 在线状态
- 部门数量
- 技能数量
- 当前任务
- 风险数量
- 知识资产
- 成长状态

状态规则：

- 数值为 `0`：正常显示 0。
- 字段缺失：显示“暂无数据”。
- API失败：显示“当前数据不可用”。

### 5.4 员工卡片组件

字段：

- 员工名称
- 员工编号
- 部门
- 岗位
- 当前状态
- 技能数量
- 当前任务数量
- 风险等级
- 权限范围

状态值：

```text
working
idle
frozen
offline
unknown
```

按钮：

- 查看员工
- 查看能力

禁止：

- 启动员工
- 执行任务
- 自动运行
- 升级员工
- 修改权限

### 5.5 部门分布组件

展示：

- 战略部门
- 数据部门
- 知识部门
- 业务部门
- 技术部门
- 未分类

功能：

- 只做前端筛选。
- 不改变后端数据。
- 不写入筛选状态。

### 5.6 能力中心摘要组件

展示：

- Skill Center 状态
- 技能总数
- 高风险技能数量
- 审核状态
- 知识关联状态

安全提示：

```text
技能 ≠ 权限
能力展示不代表执行许可
```

### 5.7 任务状态摘要组件

展示：

- 任务总数
- 进行中
- 待确认
- 阻塞
- 最近任务状态

边界：

- 只读引用 Task Center。
- 不创建任务。
- 不修改任务状态。
- 不调用 Task Center 写接口。

### 5.8 知识与记忆摘要组件

展示：

- SOP 数量
- Prompt 数量
- 案例数量
- Memory 记录数量
- 最近更新时间

边界：

- 不发布知识。
- 不修改 Prompt。
- 不自动学习。
- 不写入 Memory。

### 5.9 成长与审计摘要组件

展示：

- Growth 是否可用
- 成长评分摘要
- 风险事件数量
- 最近审计事件
- 安全审计状态

边界：

- 不自动晋升。
- 不自动降级。
- 不自动处罚。
- 不自动修复。

### 5.10 权限与安全边界组件

展示：

- 当前用户角色
- 可见范围
- 权限范围
- 高风险要求
- Security Center 状态

固定安全字段：

```json
{
  "readonly": true,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false
}
```

## 6. API 数据来源

### 6.1 首选 API

| 数据 | API | 说明 |
|---|---|---|
| 当前用户 | `GET /api/me` | 登录与角色展示 |
| AI Workforce 概览 | `GET /api/ai-workforce/overview` | 员工、部门、技能、知识、任务、审计摘要 |
| AI员工生态概览 | `GET /api/ai-employee-ecosystem/overview` | 生态模块汇总 |
| AI员工健康 | `GET /api/ai-employee-health/overview` | 健康状态与模块状态 |

### 6.2 只读辅助 API

| 数据 | API | 使用边界 |
|---|---|---|
| 员工名册 | `GET /api/ai-employees` | 只读展示员工 |
| Task Center | `GET /api/task-center/tasks` | 只读任务摘要 |
| 企业大脑总控台 | `GET /api/enterprise-brain-console/overview` | 只读系统状态参考 |

### 6.3 禁止调用 API 类型

禁止调用：

- Task Center 创建任务接口
- Task Center 状态修改接口
- 员工创建/修改接口
- 权限修改接口
- 技能安装/升级接口
- Execution Engine 相关接口
- OpenClaw 相关接口
- n8n 相关接口

## 7. 数据加载方式

加载顺序：

```text
加载页面骨架
 ↓
读取 /api/me
 ↓
读取 /api/ai-workforce/overview
 ↓
补充读取 /api/ai-employee-ecosystem/overview
 ↓
补充读取 /api/ai-employee-health/overview
 ↓
渲染卡片、列表、状态
```

异常处理：

| 场景 | 展示 |
|---|---|
| `/api/me` 401 | 跳转登录页 |
| `/api/me` 403 | 显示无权访问 |
| 概览 API 失败 | 当前数据不可用 |
| 部分模块失败 | 模块不可用，其他模块继续展示 |
| 数据为空 | 暂无数据 |
| 字段缺失 | 暂无数据 |

禁止：

- 失败后自动执行补救动作。
- 自动创建测试数据。
- 自动调用写接口修复数据。

## 8. 状态展示方式

### 8.1 员工状态

| 状态 | 展示文案 | 颜色建议 |
|---|---|---|
| working | 工作中 | 蓝色 |
| idle | 空闲 | 绿色 |
| frozen | 冻结 | 红色 |
| offline | 离线 | 灰色 |
| unknown | 未知 | 灰色 |

### 8.2 风险状态

| 风险 | 展示文案 | 处理 |
|---|---|---|
| low | 低风险 | 只读展示 |
| medium | 中风险 | 展示审计提示 |
| high | 高风险 | 显示需要审核 |
| critical | 严重风险 | 显示需要 Boss 确认和安全审计 |

### 8.3 模块状态

| 状态 | 展示文案 |
|---|---|
| connected | 已连接 |
| readonly | 只读 |
| empty | 暂无数据 |
| unavailable | 当前数据不可用 |
| restricted | 权限受限 |

### 8.4 安全状态

固定展示：

```text
readonly安全模式
禁止自动执行
禁止自动授权
禁止调用 Execution Engine / OpenClaw / n8n
高风险必须 boss_confirm=true + security_audited=true
```

## 9. Boss / 部门负责人 / AI员工 三种视角

### 9.1 Boss视角

Boss 可见：

- 企业级员工总数
- 全部门分布
- 全局技能摘要
- 全局任务摘要
- 全局风险摘要
- 待确认事项
- Security Center 状态
- Audit Center 高风险摘要

Boss 页面强调：

- 经营视角
- 风险视角
- 跨部门状态
- 人工确认事项

Boss 禁止：

- 直接执行任务
- 直接修改权限
- 绕过审计确认
- 自动调用执行系统

### 9.2 部门负责人视角

部门负责人可见：

- 本部门员工列表
- 本部门员工状态
- 本部门技能摘要
- 本部门任务摘要
- 本部门知识和记忆摘要
- 本部门风险审计摘要

部门负责人页面强调：

- 部门员工状态
- 部门任务风险
- 部门能力缺口
- 部门安全边界

部门负责人禁止：

- 查看其他部门敏感明细
- 自动跨部门授权
- 修改员工权限
- 启动执行动作

### 9.3 AI员工视角

AI员工可见：

- 自身员工档案
- 自身技能范围
- 自身知识范围
- 自身任务记录
- 自身成长状态
- 自身风险提示

AI员工页面强调：

- 自身能力边界
- 自身授权范围
- 自身任务记录
- 自身成长与风险

AI员工禁止：

- 自己提升权限
- 自己修改技能
- 自己调整成长评分
- 自己隐藏审计记录
- 自己创建或执行任务

## 10. 页面安全检查清单

实现前后必须检查：

- 页面不存在执行按钮。
- 页面不存在启动按钮。
- 页面不存在自动运行入口。
- 页面不存在权限修改入口。
- 页面不存在技能安装入口。
- 页面不存在技能升级入口。
- 页面不存在任务创建入口。
- 页面不存在 Task Center 写操作调用。
- 页面不存在 Execution Engine 调用。
- 页面不存在 OpenClaw 调用。
- 页面不存在 n8n 调用。

允许存在：

- 查看员工
- 查看能力
- 查看任务
- 查看审计
- 进入只读中心
- 返回总控台

## 11. 测试规划

建议后续开发阶段更新：

```text
tests/test_ai_workforce.py
```

测试点：

1. 页面文件存在。
2. 页面包含 `AI Workforce Center`。
3. 页面包含 readonly 安全模式。
4. 页面包含员工大厅、能力、任务、知识、记忆、成长、审计、权限、安全区域。
5. 页面调用只读 API。
6. 空数据展示“暂无数据”。
7. API失败展示“当前数据不可用”。
8. 不存在执行按钮。
9. 不存在授权、升级、安装、自动运行入口。
10. 不存在 Execution Engine / OpenClaw / n8n 调用。

不执行测试：

- 本阶段只做设计，不运行开发测试。

## 12. 后续开发顺序建议

### 12.1 第一步：页面结构收敛

目标：

- 保持 `frontend/ai-workforce.html` 独立页面。
- 补齐区域结构和空状态。
- 不改其他页面。

验收：

- 页面正常加载。
- 无执行入口。
- 空状态可用。

### 12.2 第二步：只读数据绑定

目标：

- 接入 `/api/ai-workforce/overview`。
- 补充 `/api/ai-employee-ecosystem/overview`。
- 保持字段缺失兼容。

验收：

- 数据正常渲染。
- API异常降级正常。
- 不调用写接口。

### 12.3 第三步：角色视图展示

目标：

- 根据 `/api/me` 展示 Boss / 部门负责人 / AI员工视角。
- 只做前端展示差异。
- 不修改真实权限系统。

验收：

- 不同角色看到不同说明和范围。
- 不暴露权限编辑入口。

### 12.4 第四步：安全状态联动

目标：

- 展示 Security Center 和 Audit Center 摘要。
- 展示 `boss_confirm=true`、`security_audited=true` 高风险规则。

验收：

- 高风险只提示，不处理。
- 无自动修复和自动执行。

## 13. 验收结论

Sprint62.28 已完成 AI Workforce Center 前端实现方案设计。

本方案覆盖：

- 页面目录结构
- frontend 文件规划
- 页面组件划分
- API 数据来源
- 状态展示方式
- Boss / 部门负责人 / AI员工 三种视角

本阶段没有修改已有页面、Boss Dashboard、Task Center、登录系统、数据库，也没有接入 Execution Engine / OpenClaw / n8n。
