# 天统 AI 云中台 V1.0.1 Release Notes

## 一、版本信息

- 产品名称：天统 AI 云中台
- 英文名称：TIANTONG AI Cloud
- 产品定位：Enterprise AI Operating System
- 版本：V1.0.1
- 发布类型：Patch Release

## 二、本次修复目标

本版本只修复生产架构兼容性，不新增业务功能，不修改数据库迁移逻辑：

1. 让 Backend / Worker 能在 linux/amd64 宿主机原生构建与运行。
2. 保留现有 linux/arm64 构建能力。
3. 为 amd64 与 arm64 生成独立 wheelhouse 与 SHA-256 锁定文件。
4. 统一版本号到 1.0.1。
5. 修复 release gate 对 Git worktree 的误判。

## 三、已完成验证

- 完整 pytest：769 passed, 14 warnings。
- amd64 离线依赖安装：PASS。
- amd64 Backend / Worker / Frontend 镜像构建：PASS。
- amd64 候选栈：PASS。
- Migration：`0026 -> 0027_v1_schema_alignment` 预演 PASS。
- `alembic check`：PASS。
- 健康检查与业务冒烟：PASS。

## 四、核心模块

- AI Task Center
- AI 员工中心
- Deploy Center
- 老板驾驶舱
- AI 自动派单
- Orchestrator
- Backend API
- Frontend
- Docker 基础部署
- PostgreSQL / Redis
- Health Check
- 测试体系
- Security Policy
- Release Audit

## 五、已知非阻塞事项

- FastAPI `on_event` 的弃用警告仍存在。
- Alembic `path_separator` 仍有兼容性警告。
- Node 前端验证链路仍保留少量安全警告。
- 生产部署必须显式选择目标平台，避免宿主机默认架构误选。

## 六、V1 范围边界

V1.0.1 仍然只包含生产发布与兼容性修复，不包括：

- Agent Runtime
- Capability Layer
- Skills Engine
- Enterprise Memory
- Browser / Desktop / Mobile Use
- 多模型路由
- AI 员工自主执行
