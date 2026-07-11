# TIANTONG AI Cloud V1.0.0 发布范围

## 纳入范围

- Sprint67.1 的 Alembic metadata 注册与 `0027_v1_schema_alignment`。
- 生产 Secret fail-fast、生产 CORS、生产配置模板及专项测试。
- Alembic head 在 deploy/release center 和相关测试中的一致性更新。
- CPython 3.12 linux/arm64 的直接依赖固定、带 SHA-256 锁文件及固定 Python OCI digest 的 Dockerfile。
- 单一 `VERSION` 文件、Backend/OpenAPI 运行时版本读取。
- README、部署、回滚、Release Notes、CHANGELOG、发布清单和最终报告。
- Sprint67.1 blocker closeout 与 Sprint68.1 Tag 冲突审计报告。

## 明确排除

- Sprint63/64 的 AI Workforce View、Platform Account Center、V2 页面、router/service/schema 及对应测试和设计文档。
- Sprint65 Enterprise OS V2 规划。
- Agent Runtime、Capability Layer、Skills Engine、Enterprise Memory、Browser/Desktop/Mobile Use、多模型路由和 AI 员工自主执行。

## 暂缓范围

- `PROJECT_HANDOFF.md`、`graphify-report.md` 和无法确认发布归属的历史报告。
- `artifacts/wheelhouse/linux-arm64-cp312/` 中的 wheel 二进制、元数据快照和本地执行清单；本地保留但不提交。
- 发布前工作区快照 `artifacts/sprint68_2_pre_release_worktree.txt`。

## Hunk 级拆分

`backend/main.py` 的暂存版本只包含 `get_settings`、`APPLICATION_VERSION`、FastAPI version 和安全 CORS 配置；工作区继续保留 Sprint63/64 的 router import、注册和页面入口。禁止整文件暂存。

Dockerfile 只复制提交的 hash lock，并从官方 PyPI 使用 `--require-hashes --only-binary=:all:` 安装；wheel 二进制不进入 Git。
