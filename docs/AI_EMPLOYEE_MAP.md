# AI_EMPLOYEE_MAP

## 组织定位

天统AI公司由多个 AI 员工中心组成，每个员工有明确职责、权限边界和执行阶段。

## 核心员工

| 员工 | 代码 | 职责 | 当前能力状态 |
| --- | --- | --- | --- |
| 天统 | tiantong | 总指挥 / 最高调度 | 规划与协调 |
| 天道 | tiandao | 产品设计中心 | PRD / 产品设计 |
| 天工 | tiangong | 系统架构中心 | 架构方案 |
| 天王 | tianwang | 后端开发中心 | API / 数据库 / Worker |
| 天颜 | tianyan | 前端体验中心 | 页面 / 联调 |
| 天检 | tianjian | 测试验收中心 | 测试 / 回归 |
| 天监 | tianjian_audit | AI安全审计中心 | 安全审计 |
| 天盾 | tiandun | 部署运维中心 | Docker / 阿里云 / 健康检查 |
| 天藏 | tiancang | 知识资产中心 | 长期记忆 / 知识沉淀 |
| 天商 | tianshang | 商品中心 | Sprint26 已具备真实执行闭环 MVP |
| 天采 | tiancai_data | 数据采集中心 | 数据采集规划 |
| 天数 | tianshu | 数据分析中心 | 数据分析 |
| 天策 | tiance_strategy | 策略分析中心 | 策略规划 |
| 天创 | tianchuang | 视觉创意中心 | 视觉方案 |
| 天播 | tianbo | 内容传播中心 | 内容生成 |
| 天投 | tiantou | 广告投放中心 | 广告策略 |
| 天誉 | tianyu | SEO/GEO 市场中心 | 市场分析 |
| 天财 | tiancai_finance | 财务分析中心 | 财务分析 |
| 天法 | tianfa | 法务风控中心 | 合规建议 |

## Sprint26 天商执行协议

Employee Execution Contract:

- `employee_id`
- `task_id`
- `input`
- `required_tools`
- `execution_plan`
- `result`
- `status`
- `error_log`
- `review_status`

状态：

`CREATED -> PLANNING -> EXECUTING -> WAITING_TOOL -> COMPLETED -> REVIEWED`

## 权限原则

- Owner/Admin 可以创建和查看执行任务。
- AI员工只能查看授权范围内的数据。
- Viewer 不允许访问执行接口。
- 高风险操作必须经过老板确认和天监审核。
