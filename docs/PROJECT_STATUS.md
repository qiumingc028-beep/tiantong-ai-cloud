# tiantong-ai-cloud 项目进度

## 当前进度

Sprint 13：SOP / Skill 绑定中心 ✅

## Sprint 13 完成状态

Sprint 13：SOP / Skill 绑定中心已完成。

## 后端 API

后端 API 已完成：

- `/api/sop-skill-center/overview`
- `/api/sop-skill-center/sops`
- `/api/sop-skill-center/sops/{sop_code}`
- `/api/sop-skill-center/skills`
- `/api/sop-skill-center/skills/{skill_code}`
- `/api/sop-skill-center/prompts`
- `/api/sop-skill-center/prompts/{prompt_code}`
- `/api/sop-skill-center/employees`
- `/api/sop-skill-center/employees/{employee_code}`
- `/api/sop-skill-center/task-types`
- `/api/sop-skill-center/departments`
- `/api/sop-skill-center/acceptance-rules`
- `/api/sop-skill-center/security-rules`
- `/api/sop-skill-center/missing-bindings`
- `/api/sop-skill-center/next-upgrades`

## 前端页面

前端页面已完成：

- `/sop-skill-center.html`

页面功能已完成：

- SOP 库总览
- Skill 库总览
- Prompt 模板库总览
- 员工绑定关系
- 推荐模型绑定
- 推荐工具权限绑定
- 缺失绑定提醒
- 只读安全边界说明

## 安全边界

- 第一阶段只读
- 不调用模型
- 不调用工具
- 不派单
- 不开始任务
- 不部署
- 不提交代码
- 不改权限
- 不改任务状态

## worker / Redis timeout 修复

worker / Redis timeout 修复已完成：

- Commit ID：`9d24ee28ebd92c006d358bb90952ebfeb82908bf`
- Redis Timeout 已从崩溃变为 warning
- worker 不应因 Redis Timeout 退出

## Sprint 13 线上验证

- `/sop-skill-center.html?v=sprint13-final` 页面打开正常
- `/api/health` 200
- `/api/ready` 200
- `/api/sop-skill-center/*` 未登录返回 401
- 页面浏览器实测正常

## 下一阶段建议

Sprint 14：天赋 Skill / 插件赋能中心

目标：研究、登记、评估、绑定 Skill / 插件 / MCP / 外部工具能力，但第一阶段仍然只读，不自动安装、不自动下载、不自动赋权、不自动启用。

## 未来 AI 员工规划

天赋：Skill / 插件赋能中心

状态：
已纳入规划，暂不插队开发。

原则：
不影响当前 Sprint 主线、不破坏已验收功能、不增加部署风险时，可以预留；会影响进度或安全边界时，放入后续 Sprint。
