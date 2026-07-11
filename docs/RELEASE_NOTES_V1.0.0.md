# 天统 AI 云中台 V1.0.0 Release Notes

## 版本信息

- 产品名称：天统 AI 云中台
- 英文名称：TIANTONG AI Cloud
- 产品定位：Enterprise AI Operating System
- 版本：V1.0.0

## V1 核心模块

V1 已完成 AI Task Center、AI 员工中心、Deploy Center、老板驾驶舱、AI 自动派单、Orchestrator、Backend API、Frontend、Docker 基础部署、PostgreSQL/Redis、Health Check、测试体系、Security Policy 与 Release Audit。

## 最终验证

- Backend：769 passed，14 warnings
- Frontend：68 passed，2 warnings
- Migration upgrade/check：PASS
- Static Security：PASS
- Production Policy：PASS
- Production Runtime：VERIFIED
- Health Check：PASS
- Release Audit：PASS_WITH_NON_BLOCKING_OBSERVATION

## 已知非阻塞事项

- FastAPI `on_event` 和 Alembic `path_separator` 存在非阻塞弃用警告。
- Node 验证存在实验性 warning；不在本次发布中冒险升级依赖。
- 生产 Nginx 不公开 `/openapi.json`，旧验收脚本的两个 schema 探测与生产分层入口不兼容；真实页面、API 与路由已分别验证。
- 镜像 digest 已固定；Cosign/OCI referrer 签名未找到，SBOM/Provenance 尚未验证。

## V1 边界

V1 聚焦 AI 员工管理、任务管理、自动派单、Orchestrator 编排、老板驾驶舱以及部署运行基础设施。Agent Runtime、Capability Layer、Skills Engine、Enterprise Memory、Browser/Desktop/Mobile Use、多模型路由和 AI 员工自主执行进入 V2，不属于本次发布。
