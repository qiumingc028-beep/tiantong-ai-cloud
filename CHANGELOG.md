# Changelog

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
