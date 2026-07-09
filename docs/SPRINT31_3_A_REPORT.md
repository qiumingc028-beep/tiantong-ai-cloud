# Sprint31.3-A AI员工详情聚合 API 报告

## 一、开发目标

实现 AI员工详情聚合 API：

```http
GET /api/ai-employees/{employee_id}/detail
```

该接口用于只读聚合 AI员工基础档案、当前运行状态、技能列表、可执行任务类型、权限范围、最近任务记录、成功率统计和最近日志。

## 二、修改文件

本次修改：

- `backend/routers/ai_employees.py`
- `tests/test_ai_employee_detail.py`
- `docs/SPRINT31_3_A_REPORT.md`

未修改：

- Task Center 核心逻辑
- Orchestrator 调度逻辑
- Execution Engine
- 数据库模型
- Alembic migration
- Docker / Nginx
- 前端页面

## 三、API说明

### GET `/api/ai-employees/{employee_id}/detail`

权限：

- 未登录：401
- 无 AI员工名册读取权限：403
- Owner/Admin/Boss：允许访问

数据来源：

- `ai_employees`
- `task_center_tasks`
- `task_center_results`
- `task_center_reviews`
- `task_center_audit_logs`
- `employee_logs`
- Tool Router 只读路由信息

返回结构包含：

- `employee`：员工基础信息
- `department`：部门 / 军团
- `current_status`：当前运行状态
- `skills`：从 `task_types` 映射的技能列表
- `executable_task_types`：可执行任务类型
- `permission_scope`：默认权限和工具权限摘要
- `recent_tasks`：最近任务记录
- `success_rate`：成功率统计
- `recent_logs`：最近日志摘要
- `safety`：只读与安全边界标记

安全默认值：

- `readonly=true`
- `can_auto_execute=false`
- `can_modify_permissions=false`
- `requires_boss_confirm_for_high_risk=true`

## 四、数据库说明

本次未新增数据库表，未执行 migration。

后续如果需要更精细的员工技能与权限管理，可在 Sprint31.3-B/C 后评估新增：

- `employee_skills`
- `employee_tasks`
- `employee_logs`
- `employee_permissions`

当前阶段不需要修改数据库结构。

## 五、安全说明

本接口只读，不会：

- 创建任务
- 修改任务状态
- 触发 Orchestrator
- 触发 Execution Engine
- 写入 Redis queue
- 自动执行任务
- 修改员工权限

敏感字段处理：

- 不返回 `password_hash`
- 不返回 token
- 不返回 secret
- 不返回 API key
- 不返回 Authorization 信息
- 不返回 private key
- 日志摘要命中敏感词时返回 `[redacted]`

## 六、测试结果

测试命令：

```bash
docker compose run --rm -v /Users/chenqiuming/Developer/tiantong-ai-cloud:/app backend python -m pytest -q tests/test_ai_employee_detail.py tests/test_ai_employee_registry.py tests/test_ai_employee_runtime_status.py
```

结果：

```text
20 passed, 2 warnings
```

补充：

- 本机默认 `python3` 为 Python 3.9.6，无法解析项目当前 Python 3.10+ 类型语法。
- 已使用项目 Docker Python 3.12 backend 容器完成测试。

`git diff --check`：

```text
passed
```

## 七、风险说明

风险等级：低

已控制风险：

- 只读聚合，无状态流转。
- 不触发执行引擎。
- 不新增数据库。
- 不展示任务 description / split_plan / raw execution log。
- 最近日志做敏感词过滤。

剩余注意项：

- 当前成功率基于 Task Center 状态统计，后续可接入 Execution Engine 和 Review Center 做更精准评分。
- 技能列表当前来自 `AiEmployee.task_types`，后续可迁移到结构化 `employee_skills`。

## 八、结论

Sprint31.3-A 后端开发完成。

是否允许进入老板验收：是。

是否允许进入 Sprint31.3-B 前端详情页开发：是。
