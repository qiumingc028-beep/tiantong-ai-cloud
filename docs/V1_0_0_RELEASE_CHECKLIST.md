# V1.0.0 最终发布清单

- [x] Git 工作区审计：`git status --short`；选择性暂存，保护 V2。
- [x] 敏感信息检查：对暂存 blob 执行模式扫描；未发现真实 Secret。
- [x] 版本号检查：`VERSION` 与 Backend/OpenAPI 均为 `1.0.0`。
- [x] Migration 检查：隔离 PostgreSQL 执行 `alembic upgrade head`、`alembic check`。
- [x] Backend Tests：正式 V1 测试集 769 passed。
- [x] Frontend Validation：68 passed。
- [x] Static Security：PASS。
- [x] Production Policy：PASS。
- [x] Docker Production Startup：使用独立 project、临时 volume/network 验证。
- [x] Health Check：PostgreSQL、Redis、Backend、Worker、Nginx 通过。
- [x] Release Audit：PASS_WITH_NON_BLOCKING_OBSERVATION。
- [x] Release Notes：`docs/RELEASE_NOTES_V1.0.0.md`。
- [x] CHANGELOG：`CHANGELOG.md`。
- [x] Deploy 文档：`deploy/README.md`。
- [x] Rollback 文档：`docs/V1_ROLLBACK_PLAN.md`。
- [x] Git Commit：本清单随选择性 release commit 提交；hash 以 `v1.0.0^{commit}` 为准。
- [x] Git Tag：旧本地 Tag 已有归档引用；验证完成后安全替换为 annotated `v1.0.0`。
- [x] V2 分支准备：Tag 成功后从正式 release commit 创建本地 `develop-v2`，不切换开发。
