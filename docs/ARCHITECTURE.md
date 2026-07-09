# ARCHITECTURE

## 系统定位

天统AI云中台是一个面向 AI 公司运营的云中台，包含任务中心、AI员工体系、自动派单、执行引擎、工具权限、部署中心、老板驾驶舱和知识资产中心。

## 分层架构

### 1. 接入层

- Frontend HTML pages under `frontend/`
- Nginx serves frontend and proxies `/api/*`
- FastAPI backend under `backend/`

### 2. 权限与安全层

- `backend/auth.py`
- `backend/auth_data.py`
- TianShen Approval Center: `backend/security/tian_shen/`
- Tool Permission Center: `backend/tool_center/`
- Tool Router: `backend/tool_router/`

### 3. 任务与调度层

- Task Center: `backend/routers/task_center.py`
- Auto Dispatch Center: `backend/routers/auto_dispatch.py`
- Brain Execution: `backend/brain_execution/`
- Brain Orchestrator: `backend/brain_orchestrator/`
- Redis queues:
  - Task queue
  - Brain execution queue
  - Tian Shang execution queue

### 4. AI员工执行层

- Employee Execution Engine: `backend/execution_engine.py`
- Sprint26 Employee Execution Contract: `backend/employee_execution/`
- Tian Shang Worker: `backend/workers/tian_shang_worker.py`
- Worker entry: `backend/worker.py`

### 5. 工具层

第一阶段工具均为安全模拟或内部计算：

- `backend/tools/market_search.py`
- `backend/tools/data_analysis.py`
- `backend/tools/report_generator.py`

禁止真实外部 API、Shell、自动部署、自动改代码。

### 6. 数据层

- PostgreSQL: 业务数据、任务、日志、执行合同、复盘、能力成长
- Redis: 队列、session、heartbeat
- Alembic: 数据库迁移

当前 migration head:

`0026_sprint26_ai_employee_execution_mvp`

### 7. 驾驶舱与运营层

- CEO Dashboard: `backend/routers/ceo_dashboard.py`
- Deploy Center: `backend/routers/deploy_center.py`
- Release Center: `backend/routers/release_center.py`

## 核心数据流

老板目标输入
-> Brain / Auto Dispatch 分析
-> AI员工匹配
-> 审批与安全检查
-> Redis Queue
-> Worker 执行
-> 结果写回
-> 复盘学习
-> 知识沉淀

## Sprint26 天商闭环

Owner 创建任务
-> `employee_execution_contracts`
-> `tiantong:employee:tianshang:execution`
-> Tian Shang Worker
-> AI Planner
-> internal tools
-> AI Executor
-> Task Center Result
-> CEO Dashboard status

## 安全边界

- 不自动执行 Shell
- 不自动调用外部 API
- 不自动部署
- 不自动修改代码
- 不自动修改权限
- 不在文档或 API 中返回敏感字段
