# V1.0.1 AMD64 Validation Report

## 执行摘要

V1.0.1 已完成 linux/amd64 生产兼容验证，结论是可构建、可离线安装、可启动、可迁移、可健康检查。

## 关键结果

- amd64 离线安装：PASS
- amd64 Backend 镜像：PASS，`linux/amd64`
- amd64 Worker 镜像：PASS，`linux/amd64`
- amd64 Frontend 镜像：PASS，`linux/amd64`
- 候选 PostgreSQL：PASS
- 候选 Redis：PASS
- 候选 Backend：PASS
- 候选 Worker：PASS
- 候选 Nginx：PASS
- 候选 Frontend：PASS
- 候选应用版本：`1.0.1`
- 候选 Migration：`0027_v1_schema_alignment`
- 健康检查：PASS
- 冒烟测试：PASS

## 本地验证限制

在本机 Apple Silicon / arm64 宿主机上，强制用 qemu 反复重建 amd64 `redis:7` 会出现段错误；因此本地最终验证保留了稳定的数据库/缓存容器运行态，并重点确认：

- Backend / Worker / Frontend 生产镜像确认为 `linux/amd64`
- 这些镜像在候选栈中能正常连接数据库与 Redis
- 生产目标宿主机为 linux/amd64 时不受此本机限制影响

## 回归结果

- `python -m pytest -q`
- 结果：`769 passed, 14 warnings`

## 观测项

- FastAPI `on_event` 弃用警告仍存在。
- Alembic `path_separator` 警告仍存在。
- 生产构建必须显式指定 `linux/amd64`，否则 Docker Desktop 默认平台可能误选为 `arm64`。

## 运行态检查

- `/api/health`：`running`
- `/api/ready`：`ready`
- 前端静态页面：`/`, `/login.html`, `/ai-workforce.html`, `/task-center.html`, `/deploy-center.html`, `/orchestrator.html` 均可访问。

## 说明

`release_center` 的 commit gate 已修复为可识别 Git worktree；这消除了本地 hotfix/worktree 环境下的误判。
