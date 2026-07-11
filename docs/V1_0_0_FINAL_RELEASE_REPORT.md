# 天统 AI 云中台 V1.0.0 最终发布报告

状态：本地正式发布完成，等待远程发布。

## 发布基线

- 正式版本：1.0.0
- 当前真实分支：`终端`
- 原始 HEAD：`9e0a518ce7dfe47909c15b19a61ddf8c80fe6295`
- 旧 Tag 归档：`archive/v1.0.0-pre-sprint67.1`，指向原始 HEAD
- 发布 Commit：本报告所在的选择性 release commit；不可在 commit 内容中自引用自身 hash，权威 hash 由 `git rev-parse v1.0.0^{commit}` 给出
- 新本地 Tag：annotated `v1.0.0`，message 为 `TIANTONG AI Cloud V1.0.0 Final Release`
- develop-v2：从新 release commit 创建或核对，不在本 Sprint 开发 V2
- 远程 Push：未执行
- 生产部署：未执行

## 发布内容与排除范围

本次只纳入 Sprint67.1 发布阻断修复、0027 migration、生产配置与 CORS、版本信息、必要依赖锁和发布文档。Sprint63/64 实现、Sprint65 V2 规划、V2 页面/测试和无法确认的历史文件均保留在工作区，不进入 V1 commit。wheel 二进制保留本地，不进入 Git。

## 验证结论

- 暂存候选树隔离验证：不含 Sprint63/64 router、service、schema、页面或测试。
- 应用版本：Backend 与 OpenAPI 均为 1.0.0。
- Python syntax/import：PASS，候选 Backend 注册 338 routes。
- Frontend validation：68 passed，2 warnings。
- Backend full regression：769 passed，14 warnings。
- Migration：全新 PostgreSQL `upgrade head` PASS，`alembic check` 无 drift。
- Static Security / Production Policy：PASS；生产 Secret 缺失 fail-fast，CORS 合法 origin 通过、恶意 origin 被拒绝。
- Runtime：独立 Compose project 的 PostgreSQL、Redis、Backend、Worker、Nginx 启动成功；Backend/Nginx/PostgreSQL/Redis healthy，Worker heartbeat 正常，restart policy 为 `unless-stopped`，debug=false。
- Health Check：HTTPS `/`、`/health`、`/ready` 均 PASS。
- Release Audit：PASS_WITH_NON_BLOCKING_OBSERVATION。旧验收脚本在生产 Nginx 入口无法读取 `/openapi.json`，但其余 10 项通过；两个目标路由已直接从 Backend OpenAPI 验证存在。
- 敏感信息：暂存区无真实 Secret、private key、`.env.production`、数据库、日志、本机绝对路径或 wheel 二进制。

## 非阻塞 Warning 与限制

- Backend：14 warnings（FastAPI `on_event` 2 条、Alembic `path_separator` 12 条）。
- Frontend：2 条对应 FastAPI import warning。
- 生产 Nginx 有意不公开 OpenAPI schema。
- Python base image digest 已固定；Nginx 仍使用既有固定 tag/digest 解析结果。Cosign/OCI referrer signature 未找到，SBOM/Provenance 未验证。
- wheelhouse 二进制只保留在本地；Git 仅提交 35 项依赖的 SHA-256 lock，生产构建从官方 PyPI 按 hash 获取 compatible wheel。

## 清理与回滚

验证使用独立临时 Compose project、volume、network、证书和测试秘密；完成后全部删除。旧项目容器保持停止并恢复原 restart policy，Docker Desktop 恢复执行前关闭状态。应用回滚入口见 `docs/V1_ROLLBACK_PLAN.md`；Migration 回滚前必须备份并人工审批。
