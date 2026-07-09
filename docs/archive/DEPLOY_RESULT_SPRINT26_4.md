# Sprint26.4 Deploy Result

## 部署结论

状态：未完成，阻塞于阿里云 ECS SSH 认证。

本次未进入服务器执行部署命令，未修改业务代码，未修改数据库结构，未删除数据，未安装软件。

## 部署时间

- 检查时间：2026-07-08
- 目标服务器：`120.24.79.232`
- 项目目录：`/data/apps/tiantong-ai-cloud`

## Commit 版本

- 本地分支：`main`
- 本地 HEAD：`a8f712ac1402b5579d16604bc3aef3af173688f4`
- GitHub main：`a8f712ac1402b5579d16604bc3aef3af173688f4`
- GitHub main 一致性：PASS

## 执行前检查

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| GitHub main 版本确认 | PASS | GitHub main 指向 `a8f712ac1402b5579d16604bc3aef3af173688f4`。 |
| 阿里云 SSH 可达性 | BLOCKED | SSH host key 已接受，但认证失败。 |
| 阿里云服务器环境确认 | NOT RUN | 未通过 SSH 认证，无法进入服务器检查。 |
| Docker 环境确认 | NOT RUN | 未通过 SSH 认证，无法执行 `docker --version`。 |
| 环境变量确认 | NOT RUN | 未通过 SSH 认证，无法检查生产 `.env`。 |

## 阻塞详情

执行 SSH 检查时返回：

```text
root@120.24.79.232: Permission denied (publickey,password).
```

说明：

- 当前本机没有可用于 `root@120.24.79.232` 的 SSH 私钥或免密权限。
- 本次没有使用交互式密码登录。
- 未执行任何远程部署命令。

## Docker 状态

阿里云 Docker 状态：未检查。

原因：SSH 认证失败，无法进入服务器执行：

```bash
docker ps
docker compose ps
docker --version
docker compose version
```

## API 状态

阿里云 API 状态：未检查。

原因：部署未执行，无法确认最新版本是否已运行。

待 SSH 认证修复后需要检查：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -i http://127.0.0.1/api/archive/sprints
curl -i http://127.0.0.1/api/archive/project-status-draft
curl -i http://127.0.0.1/api/archive/decision-draft
```

公网浏览器待验证：

```text
http://120.24.79.232
```

## 应执行但尚未执行的部署步骤

SSH 登录恢复后，按 `docs/DEPLOY_SPRINT26_4.md` 人工执行：

```bash
cd /data/apps/tiantong-ai-cloud
git fetch --prune origin main
git reset --hard origin/main
git rev-parse HEAD
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
docker compose build backend worker
docker compose up -d backend worker nginx
docker compose ps
```

期望：

- HEAD 为 `a8f712ac1402b5579d16604bc3aef3af173688f4`
- Alembic current 为 `0026_sprint26_ai_employee_execution_mvp (head)`
- backend healthy
- worker running
- postgres healthy
- redis healthy
- nginx running
- `/api/health` 返回 200
- `/api/ready` 返回 200
- `/api/archive/*` 未登录返回 401，且不返回 404

## 是否上线成功

否。

当前状态：未部署，等待提供阿里云 SSH 登录方式后继续。

## 下一步

需要老板确认并提供以下任一方式：

1. 可用 SSH 私钥，并确认登录用户。
2. 临时开启当前机器 SSH 公钥访问。
3. 在阿里云 Workbench 中按 `docs/DEPLOY_SPRINT26_4.md` 人工执行部署 SOP。

恢复登录后，天盾继续执行部署验证。
