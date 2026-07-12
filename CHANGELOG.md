# Changelog

## [1.0.1] - 2026-07-12

### Added

- linux/amd64 生产兼容补丁发布链路。
- amd64 / arm64 分离 wheelhouse、SHA-256 lock 与构建脚本。

### Changed

- Backend / Worker Dockerfile 改为通过显式 lock 路径选择构建平台。
- 版本号统一提升为 1.0.1。

### Security

- 继续要求生产 Secret fail-fast，保留显式 CORS origins 约束。
- 发布中心静态闸门修复为可识别 Git worktree。

### Infrastructure

- amd64 镜像可在 linux/amd64 宿主机原生构建并运行。
- arm64 构建路径仍可通过显式参数保留。

### Tests

- 完整回归：769 passed, 14 warnings。
- amd64 候选栈、离线安装、迁移预演与健康检查通过。

### Known Limitations

- FastAPI / Alembic 与部分 Node 版本警告仍保留，未在本次补丁中消除。
- 生产部署仍需使用显式平台选择，避免宿主机默认架构误选。

## [1.0.0] - 2026-07-11

### Added

- AI Task Center、AI 员工中心、老板驾驶舱、自动派单与 Orchestrator。
- PostgreSQL、Redis、Worker、Nginx、Health Check 和发布审计体系。

### Changed

- 统一应用版本为 1.0.0。
- 对齐 SQLAlchemy metadata 与 Alembic head `0027_v1_schema_alignment`。

### Security

- 生产秘密缺失或使用默认值时 fail-fast。
- 生产 CORS 仅接受显式、非空且非通配的 origin。

### Infrastructure

- 固定 CPython 3.12 linux/arm64 OCI digest。
- 依赖版本与 wheel SHA-256 锁定；生产 Docker 构建使用 hash 校验。

### Tests

- Backend：769 passed。
- Frontend：68 passed。
- Migration、Static Security、Production Policy、Runtime 与 Health Check 通过。

### Known Limitations

- 保留 FastAPI/Alembic 和 Node 非阻塞 warning。
- 生产 Nginx 不公开 OpenAPI schema。
- 镜像签名、SBOM 和 provenance 尚未完成可信验证。
