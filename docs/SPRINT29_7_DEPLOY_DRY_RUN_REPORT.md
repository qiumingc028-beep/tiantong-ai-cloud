# Sprint29.7 阿里云生产部署 Dry-run 报告

目标：在不连接阿里云、不执行部署的前提下，模拟完整生产部署流程，提前识别失败点和处理方式。

执行边界：

- 只分析，不执行任何生产命令
- 不连接阿里云
- 不修改业务代码
- 不修改数据库结构
- 不删除任何数据

## 1. 模拟完整部署流程

### 阶段 1：连接前确认

模拟动作：

1. 确认目标 ECS。
2. 确认登录方式。
3. 确认部署窗口。
4. 确认部署目录 `/data/apps/tiantong-ai-cloud`。

预计结果：

- 能明确目标服务器。
- 能明确使用 Workbench / SSH Key / 已审批方式登录。
- 能确认当前窗口允许短暂停机或重启。

可能失败点：

- 登录到错误服务器。
- 没有可用登录方式。
- 部署目录不存在。
- 当前窗口不允许重启服务。

失败处理方式：

- 停止部署。
- 重新确认 ECS IP / 域名 / 登录方式。
- 由老板确认是否创建或修复部署目录。

### 阶段 2：服务器基础状态检查

模拟动作：

1. 检查 Docker。
2. 检查 Docker Compose。
3. 检查磁盘空间。
4. 检查端口占用。

预计结果：

- Docker daemon 正常。
- Docker Compose v2 可用。
- 磁盘可用空间不少于 10GB。
- 80 / 443 可用。
- 5432 / 6379 / 8000 不暴露公网。

可能失败点：

- Docker 未安装或 daemon 未启动。
- 当前用户无 Docker 权限。
- 磁盘不足。
- 80 / 443 被其他服务占用。
- 数据库或 Redis 端口暴露公网。

失败处理方式：

- 停止部署。
- 先完成服务器运维修复。
- 不允许在未确认情况下自动安装软件或改端口。

### 阶段 3：GitHub 版本同步

模拟动作：

1. 进入 `/data/apps/tiantong-ai-cloud`。
2. 查看当前 commit。
3. 拉取 GitHub main。
4. reset 到 `origin/main`。
5. 确认 HEAD。

预计结果：

- 服务器 HEAD 与老板确认的 GitHub main commit 一致。
- 无未预期本地修改。

可能失败点：

- GitHub 无法访问。
- 服务器本地存在未提交修改。
- 拉取到未审批 commit。
- 远程仓库地址错误。

失败处理方式：

- 停止部署。
- 输出 `git remote -v`、`git status --short`、`git log -1 --oneline`。
- 等老板确认是否覆盖本地修改。

### 阶段 4：生产环境变量检查

模拟动作：

1. 检查 `.env.production` 是否存在。
2. 检查权限是否为 `600`。
3. 检查是否存在 `<...>` 占位符。
4. 渲染 `docker-compose.prod.yml`。

预计结果：

- `.env.production` 存在。
- 权限为 `600`。
- 所有占位符已替换。
- compose config 成功。

可能失败点：

- `.env.production` 不存在。
- `.env.production` 权限过宽。
- 存在未替换占位符。
- `DATABASE_URL`、`REDIS_URL`、`JWT_SECRET` 等变量缺失。

失败处理方式：

- 停止部署。
- 人工补齐 `.env.production`。
- 不在聊天、Git、日志中输出真实密钥。

### 阶段 5：数据库备份和权限检查

模拟动作：

1. 创建备份目录。
2. 执行 `pg_dump`。
3. 检查 PostgreSQL 角色。
4. 确认 `tiantong_app` 低权限用户。

预计结果：

- 备份文件生成且大小合理。
- `tiantong_app` 存在。
- `tiantong_app` 非 Superuser。
- `tiantong_app` 无 Create DB / Create Role / Replication / Bypass RLS。

可能失败点：

- 备份失败。
- 磁盘不足。
- `POSTGRES_ADMIN_USER` 无权限。
- `tiantong_app` 不存在。
- `tiantong_app` 权限过高。

失败处理方式：

- 停止部署。
- 不执行 migration。
- 先修复数据库权限或备份问题。
- 禁止删除数据库 volume。

### 阶段 6：Docker 构建

模拟动作：

1. 构建 backend。
2. 构建 worker。
3. 构建 nginx。

预计结果：

- 三个镜像均构建成功。
- nginx 使用 `nginx/production.conf`。
- backend / worker 使用 Python 3.12 运行镜像。

可能失败点：

- 网络导致依赖下载失败。
- Docker build cache 或空间不足。
- Dockerfile 配置错误。
- nginx 生产配置复制失败。

失败处理方式：

- 停止启动服务。
- 保留旧容器继续运行。
- 根据 build 日志定位，不改业务逻辑。

### 阶段 7：数据库迁移

模拟动作：

1. 执行 `alembic upgrade head`。
2. 执行 `alembic current`。

预计结果：

- migration 成功。
- Alembic current 为 head。

可能失败点：

- 数据库连接失败。
- 低权限用户不能执行迁移。
- migration 脚本异常。

失败处理方式：

- 停止启动新服务。
- 不执行 downgrade。
- 优先修复权限或通过代码前滚修复。
- 如需恢复数据库，必须老板二次确认。

### 阶段 8：服务启动

模拟动作：

1. 启动生产 compose。
2. 检查容器状态。

预计结果：

- backend healthy。
- postgres healthy。
- redis healthy。
- worker running。
- nginx healthy / running。

可能失败点：

- Redis 密码不一致。
- DATABASE_URL 连接失败。
- TLS 证书路径错误导致 nginx 启动失败。
- backend healthcheck 失败。
- worker 持续重启。

失败处理方式：

- 查看对应服务日志。
- 修复 `.env.production` 或证书路径。
- 必要时回滚 Git / Docker 镜像。
- 禁止删除 volume。

### 阶段 9：健康检查和页面检查

模拟动作：

1. 本机 health/ready。
2. HTTPS domain health/ready。
3. 首页和核心页面。

预计结果：

- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- 核心页面返回 200。
- 浏览器不白屏。

可能失败点：

- Nginx 反代失败。
- HTTPS 证书错误。
- 前端静态文件缺失。
- backend 未就绪。

失败处理方式：

- 检查 nginx / backend 日志。
- 检查证书路径。
- 若无法快速修复，回滚 nginx 或业务镜像。

### 阶段 10：权限和登录检查

模拟动作：

1. 未登录访问管理 API。
2. 浏览器登录 owner / boss / admin。
3. viewer 访问管理接口。

预计结果：

- 未登录返回 401。
- owner / boss / admin 登录成功。
- viewer 无管理权限。
- 响应不泄露敏感字段。

可能失败点：

- 登录失败。
- viewer 越权。
- 未登录接口返回 200。
- 响应泄露 token / secret / password。

失败处理方式：

- 立即停止上线。
- 回滚服务或关闭公网入口。
- 交天监安全审计。

### 阶段 11：日志检查

模拟动作：

1. 查看 backend 日志。
2. 查看 worker 日志。
3. 查看 nginx 日志。

预计结果：

- 无 Traceback。
- 无 ImportError。
- 无 ModuleNotFoundError。
- 无持续 500。
- 无 secret 泄露。

可能失败点：

- 后端持续 500。
- worker 反复重启。
- 日志出现敏感信息。

失败处理方式：

- 立即停止上线。
- 保留日志用于审计。
- 如出现密钥泄露，立即轮换相关密钥。

## 2. 每一步预计结果汇总

| 阶段 | 预计结果 |
|---|---|
| 连接前确认 | 目标 ECS、部署窗口、登录方式明确 |
| 服务器状态 | Docker / Compose / 磁盘 / 端口符合部署要求 |
| GitHub 同步 | HEAD 等于老板确认 commit |
| 环境变量 | `.env.production` 存在、权限 600、无占位符 |
| 数据库备份 | 备份文件生成，`tiantong_app` 权限正确 |
| Docker 构建 | backend / worker / nginx 构建成功 |
| 数据库迁移 | Alembic 升级到 head |
| 服务启动 | backend/postgres/redis/nginx healthy，worker running |
| 健康检查 | health/ready 返回 200 |
| 页面检查 | 核心页面 200，无白屏 |
| 权限检查 | 未登录 401，viewer 不越权 |
| 日志检查 | 无持续错误，无敏感泄露 |

## 3. 可能失败点汇总

1. ECS 登录错误或目录错误。
2. Docker / Compose 不可用。
3. 磁盘空间不足。
4. 80 / 443 被占用。
5. 数据库或 Redis 端口暴露公网。
6. GitHub main commit 与审批版本不一致。
7. `.env.production` 缺失或仍有占位符。
8. PostgreSQL 备份失败。
9. `tiantong_app` 不存在或权限过高。
10. Redis 密码和 `REDIS_URL` 不一致。
11. TLS 证书缺失或过期。
12. Docker build 失败。
13. Alembic migration 失败。
14. 服务启动后非 healthy。
15. health/ready 非 200。
16. 页面白屏。
17. 未登录管理 API 返回 200。
18. viewer 越权。
19. 日志泄露 secret。

## 4. 失败处理方式汇总

| 失败类型 | 处理方式 |
|---|---|
| 服务器身份不明 | 停止部署，重新确认 ECS |
| Docker 不可用 | 停止部署，先完成运维修复 |
| 磁盘不足 | 停止部署，清理或扩容后再执行 |
| Git commit 不一致 | 停止部署，等待老板确认 |
| `.env.production` 错误 | 停止部署，人工修复密钥文件 |
| 数据库备份失败 | 停止部署，不允许 migration |
| 数据库权限异常 | 停止部署，修复 `tiantong_app` 权限 |
| Redis 密码异常 | 修复 `.env.production`，重启 redis/backend/worker |
| TLS 失败 | 修复证书路径或回滚 nginx |
| Docker build 失败 | 保持旧服务运行，不启动新服务 |
| Migration 失败 | 停止部署，不 downgrade，人工评估 |
| 服务非 healthy | 查看日志，必要时回滚 |
| 权限绕过 | 立即停止上线，交天监审计 |
| 日志泄密 | 立即停止上线，轮换密钥 |

## 5. 部署前最终确认清单

正式部署前，老板必须确认：

```text
[ ] 目标 ECS 已确认
[ ] 部署窗口已确认
[ ] 登录方式已确认
[ ] GitHub main commit 已确认
[ ] .env.production 已准备
[ ] .env.production 权限为 600
[ ] .env.production 无占位符
[ ] PostgreSQL 备份方案已确认
[ ] tiantong_app 低权限用户已确认
[ ] REDIS_PASSWORD 已确认
[ ] REDIS_URL 与 REDIS_PASSWORD 一致
[ ] TLS_CERT_PATH 已确认
[ ] TLS_KEY_PATH 已确认
[ ] TLS 证书未过期
[ ] 阿里云安全组已确认
[ ] 80 / 443 开放
[ ] 5432 / 6379 / 8000 未开放公网
[ ] Cookie Secure 短期风险已确认或已安排修复
[ ] 回滚方案已确认
[ ] 禁止删除 volume 已确认
[ ] 禁止 downgrade 已确认
[ ] 老板确认可以进入真实部署
```

## 6. Dry-run 结论

根据 `docs/SPRINT29_7_PRODUCTION_DEPLOY_PLAN.md` 模拟，当前部署流程完整，失败处理路径明确。

是否建议进入真实部署：

- 可以进入，但必须先完成最终确认清单。
- 不建议跳过 Cookie Secure 风险确认。
- 不建议在未完成数据库备份和 PostgreSQL 低权限用户确认前部署。

下一步建议：

等待老板确认是否进入：

> Sprint29.7 阿里云生产部署执行
