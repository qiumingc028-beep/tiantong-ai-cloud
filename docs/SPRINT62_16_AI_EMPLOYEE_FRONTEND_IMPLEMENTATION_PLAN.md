# Sprint62.16-A AI员工生态前端实现规划

## 1. 阶段边界

本阶段只做开发实施方案。

禁止：

- 不写代码
- 不创建 HTML
- 不修改现有页面
- 不修改后端
- 不创建数据库
- 不创建 migration
- 不接 OpenClaw
- 不接 n8n
- 不接 Execution Engine

依据：

- `docs/SPRINT62_15_AI_EMPLOYEE_FRONTEND_PRODUCT_DESIGN.md`
- `docs/SPRINT62_14_AI_EMPLOYEE_API_ARCHITECTURE.md`
- 当前已有 `frontend/ai-workforce.html`、`frontend/ai-employee-detail.html`、`frontend/skill-center.html`、`frontend/skill-detail.html`

目标：

输出 AI员工生态前端正式开发方案。

## 2. 总体实施原则

1. 先复用已有页面，不推倒重来。
2. 先做只读骨架，再接只读数据。
3. 先空状态可用，再动态数据完善。
4. 每个页面独立验收，不跨 Sprint 扩大范围。
5. 所有页面禁止执行、升级、授权、自动调用外部系统。

统一安全文案：

```text
readonly安全模式
只读展示
当前未接入真实业务数据
当前数据不可用
技能 ≠ 权限
高风险必须 boss_confirm=true + security_audited=true
```

## 3. 页面文件规划

### 3.1 已有页面

| 页面文件 | 当前状态 | 后续规划 | 风险 |
| --- | --- | --- | --- |
| `frontend/ai-workforce.html` | 已有 V2 页面 | 作为生态首页继续增强 | 低 |
| `frontend/ai-employee-detail.html` | 已有员工详情 V2 | 保持最小修改，后续接统一生态 API | 中 |
| `frontend/ai-employee-capability.html` | 已有能力中心页面 | 可作为 Employee Detail 能力下钻页 | 低 |
| `frontend/skill-center.html` | 已有 Skill Center 只读页 | 后续切换统一 API | 低 |
| `frontend/skill-detail.html` | 已有技能详情页 | 后续补充版本和审计信息 | 低 |
| `frontend/tiancang.html` | 已有天藏页面 | Knowledge OS 入口继续复用 | 中 |
| `frontend/knowledge-center.html` | 已有知识中心页面 | 与天藏并行保留 | 中 |
| `frontend/task-center.html` | 已有 Task Center | 只读引用，不嵌入执行入口 | 高 |

### 3.2 待新增页面

后续开发阶段建议新增：

| 页面文件 | 目标 | 首期范围 |
| --- | --- | --- |
| `frontend/memory-center.html` | Memory Center 记忆中心 | 只读骨架 + 空状态 |
| `frontend/growth-center.html` | Growth Center 成长中心 | 只读骨架 + 空状态 |
| `frontend/audit-center.html` | Audit Center 审计中心 | 只读骨架 + 空状态 |
| `frontend/ai-meeting-room.html` | AI Meeting Room | 只读会议列表 + 草稿状态 |

### 3.3 不建议新增的页面

| 页面 | 原因 |
| --- | --- |
| `execution-center.html` | 本阶段禁止接 Execution Engine |
| `permission-edit.html` | 禁止权限修改入口 |
| `skill-install.html` | 禁止自动安装技能 |
| `employee-upgrade.html` | 禁止自动升级员工 |

## 4. 前端组件规划

本项目当前是静态 HTML + 内联 CSS/JS 风格。正式实现阶段可先以页面内组件函数方式复用，后续再抽公共 CSS。

### 4.1 员工卡片

使用页面：

- AI Workforce Center
- Employee Detail 相关推荐
- AI Meeting Room 参与员工

字段：

- 员工名称
- 员工编号
- 部门
- 岗位
- 状态
- 技能数量
- 当前任务
- 风险等级
- 查看员工

状态：

```text
working / idle / frozen / offline
```

按钮白名单：

- 查看员工

禁止：

- 启动员工
- 升级员工
- 修改权限
- 执行任务

### 4.2 能力卡片

使用页面：

- AI Workforce Center
- Employee Detail
- AI Employee Capability
- Skill Center

字段：

- 能力名称
- 分类
- 描述
- 关联技能
- 知识资产
- 风险等级
- 审核状态

按钮白名单：

- 查看
- 进入
- 查看详情

禁止：

- 安装技能
- 升级技能
- 调用技能

### 4.3 技能卡片

使用页面：

- Skill Center
- Skill Detail
- Employee Detail 能力中心

字段：

- 技能名称
- 技能编号
- 技能版本
- 技能状态
- 风险等级
- 审核状态
- 使用员工数量

安全提示：

```text
技能 ≠ 权限
```

### 4.4 成长图表

使用页面：

- Growth Center
- Employee Detail 成长中心

V1 实现方式：

- 首期使用指标卡 + 表格趋势。
- 不强依赖图表库。
- 无数据时显示“暂无成长数据”。

字段：

- 成长评分
- 成功率
- 技能成长
- 能力缺口
- 晋升建议状态

禁止：

- 自动晋升
- 自动降级
- 自动调整技能

### 4.5 风险展示

使用页面：

- AI Workforce Center
- Employee Detail 风险中心
- Audit Center
- Skill Center
- Growth Center

字段：

- 风险等级
- 来源模块
- 关联员工
- 关联任务
- 风险说明
- 审计状态
- Boss确认状态

风险等级：

```text
low / medium / high / critical
```

高风险文案：

```text
需要审核：boss_confirm=true + security_audited=true
```

### 4.6 审计列表

使用页面：

- Audit Center
- Employee Detail 审计状态
- Skill Detail 审核记录
- Growth Center 风险记录

字段：

- 事件类型
- 来源模块
- 关联对象
- 风险等级
- 审计状态
- 发生时间

禁止：

- 自动修复
- 自动封禁
- 自动改权

## 5. API 接入规划

### 5.1 统一生态 API

未来目标 API：

```text
/api/ai-employee-ecosystem/*
```

V1 只读接口：

| 页面 | 目标 API |
| --- | --- |
| AI Workforce Center | `GET /api/ai-employee-ecosystem/overview` |
| Employee Detail | `GET /api/ai-employee-ecosystem/employees/{employee_code}` |
| Skill Center | `GET /api/ai-employee-ecosystem/skills` |
| Skill Detail | `GET /api/ai-employee-ecosystem/skills/{skill_code}` |
| Memory Center | `GET /api/ai-employee-ecosystem/memory/overview` |
| Growth Center | `GET /api/ai-employee-ecosystem/growth/overview` |
| Audit Center | `GET /api/ai-employee-ecosystem/audit/overview` |
| AI Meeting Room | `GET /api/ai-employee-ecosystem/meetings/overview` |

说明：

- `meetings/overview` 属于前端实现规划建议，后续 API 设计需单独确认。
- Sprint62.16-A 不新增该 API。

### 5.2 现有 API 复用

正式开发前期优先复用：

| 页面 | 现有 API |
| --- | --- |
| AI Workforce Center | `GET /api/ai-workforce/overview` |
| Employee Detail | `GET /api/ai-employees/{employee_code}/detail` |
| Skill Center | `GET /api/sop-skill-center/skills`、`GET /api/skill-plugin-center/skills` |
| Knowledge OS | `GET /api/tiancang/*`、`GET /api/knowledge/*` |
| Growth Center | `GET /api/employee-evolution/growth`、`GET /api/employee-evolution/risk-events` |
| Audit Center | `GET /api/employee-activity-log/overview`、`GET /api/employee-activity-trace/trace-overview` |
| Task Center | `GET /api/task-center/tasks` |

策略：

- 统一生态 API 未实现前，页面可先复用现有只读 API。
- 当 `/api/ai-employee-ecosystem/*` 实现后，再逐步切换。
- 切换必须逐页验收，不能一次性替换所有页面。

## 6. 数据加载方式

### 6.1 加载状态

每个页面必须有：

```text
正在加载...
已加载
当前数据不可用
暂无数据
当前未接入真实业务数据
无权限查看
请重新登录
```

### 6.2 降级策略

| 场景 | 页面行为 |
| --- | --- |
| API 成功但空数据 | 显示“暂无数据”或“当前未接入真实业务数据” |
| API 失败 | 显示“当前数据不可用” |
| 单模块失败 | 其他模块继续展示 |
| 401 | 跳转登录 |
| 403 | 显示无权限并停止敏感展示 |
| 字段缺失 | 显示“暂无数据” |

### 6.3 数据原则

- 不生成假数据。
- 不伪造成长曲线。
- 不把空数据渲染成真实业务结论。
- 不展示敏感 Prompt 全文。
- 不展示密钥、Cookie、Token、账号密码。

## 7. 分阶段开发计划

### Sprint62.17：Memory Center 只读页面

修改文件：

- 新增 `frontend/memory-center.html`
- 新增 `tests/test_memory_center.py`
- 必要时仅注册 HTML 白名单

范围：

- 页面骨架
- 空状态
- 记忆总览区域
- 员工记忆、项目记忆、决策记忆、成功案例、失败案例、搜索框占位

验收：

- 页面存在
- 无执行按钮
- 无自动学习入口
- 无权限修改入口

### Sprint62.18：Growth Center 只读页面

修改文件：

- 新增 `frontend/growth-center.html`
- 新增 `tests/test_growth_center.py`
- 必要时仅注册 HTML 白名单

范围：

- 成长总览
- 员工成长排名
- 能力变化
- 技能成长摘要
- 能力缺口空状态

验收：

- 页面存在
- 无自动晋升按钮
- 无技能修改入口
- 无权限修改入口

### Sprint62.19：Audit Center 只读页面

修改文件：

- 新增 `frontend/audit-center.html`
- 新增 `tests/test_audit_center.py`
- 必要时仅注册 HTML 白名单

范围：

- 风险总览
- 审计事件列表
- AI员工行为记录
- 技能调用记录
- 权限变化记录
- 安全状态

验收：

- 页面存在
- 无自动修复入口
- 无自动封禁入口
- 无自动修改权限入口

### Sprint62.20：AI Meeting Room 只读页面

修改文件：

- 新增 `frontend/ai-meeting-room.html`
- 新增 `tests/test_ai_meeting_room.py`
- 必要时仅注册 HTML 白名单

范围：

- 会议列表
- 参与 AI员工
- 讨论记录
- 方案总结
- 决策草稿
- 风险提示

验收：

- 页面存在
- 无自动创建任务按钮
- 无自动执行方案按钮
- 无技能调用入口

### Sprint62.21：统一生态前端导航整理

修改文件：

- 仅修改已确认页面导航
- 更新对应页面测试

范围：

- 将 AI员工生态页面统一挂入导航
- 未实现页面显示“设计中”
- 入口只支持查看/进入

验收：

- 导航一致
- 不影响已有页面
- 不新增危险入口

### Sprint62.22：统一生态 API 接入切换规划

范围：

- 先设计，再开发。
- 逐页从现有 API 切换到 `/api/ai-employee-ecosystem/*`。
- 每个页面独立测试。

限制：

- 不一次性替换全部页面。
- 不改变 Task Center 业务流程。

## 8. 安全检查清单

每个前端页面必须确认不存在：

- 自动执行
- 自动升级
- 自动授权
- 自动安装技能
- 自动调用技能
- 自动发布知识
- 自动创建任务
- 自动修改 Task Center 状态
- 自动调用 Execution Engine
- OpenClaw 入口
- n8n 入口

页面必须保留：

```json
{
  "readonly": true,
  "execution_button_visible": false,
  "auto_upgrade_button_visible": false,
  "permission_modify_button_visible": false,
  "execution_engine_called": false,
  "openclaw_connected": false,
  "n8n_connected": false,
  "high_risk_requires": {
    "boss_confirm": true,
    "security_audited": true
  }
}
```

## 9. 测试规划

### 9.1 页面静态测试

每个新增页面测试：

- 文件存在
- 标题存在
- readonly 文案存在
- 空状态存在
- 安全边界存在
- 禁止词不存在

禁止词：

```text
自动执行
自动升级
自动授权
修改权限
调用Execution Engine
OpenClaw
n8n
```

说明：

- 如果页面必须展示 OpenClaw/n8n/Execution Engine 安全状态，只能以“未接入 / false / 禁止”语义出现。

### 9.2 API 降级测试

测试场景：

- API 失败
- API 返回空数组
- API 字段缺失
- 401 未登录
- 403 无权限

验收：

- 页面不报错。
- 显示“当前数据不可用”或“暂无数据”。
- 不出现危险操作兜底按钮。

### 9.3 回归测试

每次新增页面后至少运行：

- 对应新增页面测试
- `tests/test_ai_workforce.py`
- `tests/test_ai_employee_detail.py`
- `tests/test_skill_center.py`

如涉及导航或 HTML 白名单，再补充：

- `tests/test_enterprise_brain_console.py`

## 10. 验收标准

Sprint62.16-A 验收标准：

- 只生成实施规划文档。
- 不写代码。
- 不创建 HTML。
- 不修改现有页面。
- 不修改后端。
- 不创建数据库。
- 不创建 migration。
- 不接 OpenClaw。
- 不接 n8n。
- 不接 Execution Engine。

后续开发验收标准：

- 页面加载正常。
- 空数据正常。
- API 异常正常。
- 无危险按钮。
- 无自动执行链路。
- 不影响已有 AI Workforce、Employee Detail、Skill Center。

## 11. 验收结论

Sprint62.16-A 只完成 AI员工生态前端实现规划。

验收项：

- 已规划页面文件。
- 已规划前端组件。
- 已规划 `/api/ai-employee-ecosystem/*` 接入路径。
- 已规划现有 API 复用策略。
- 已规划数据加载方式和异常降级。
- 已规划安全检查清单。
- 已规划后续 Sprint 开发拆分。

未执行事项：

- 未写代码。
- 未创建 HTML。
- 未修改现有页面。
- 未修改后端。
- 未创建数据库。
- 未创建 migration。
- 未接 OpenClaw。
- 未接 n8n。
- 未接 Execution Engine。
