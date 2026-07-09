# Sprint29.17 正式部署前准备检查

目标：完成天统AI V1 正式部署前第一阶段准备，确认 GitHub main 同步状态、生产配置状态、阿里云连接阻塞和正式部署前剩余风险。

执行边界：

- 已执行 `git push origin main`
- 已执行 GitHub main 只读验证
- 未执行生产部署
- 未执行 `docker compose up`
- 未执行数据库迁移
- 未修改业务代码

## 1. Git 版本

当前本地分支：

```text
main
```

当前本地 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

当前提交说明：

```text
Sprint29.16 production deployment preparation
```

GitHub main 验证：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0 refs/heads/main
```

结论：

- GitHub main 已同步 Sprint29.16 生产部署准备版本。
- 当前本地工作区在 push 后为干净状态。

## 2. 阿里云连接状态

目标服务器：

```text
120.24.79.232
```

只读 SSH 探测结果：

```text
root@120.24.79.232: Permission denied (publickey).
ubuntu@120.24.79.232: Permission denied (publickey).
```

结论：

- 当前 Codex 环境仍无法通过 SSH 进入阿里云服务器。
- 生产服务器运行态未能远程确认。
- 需要老板通过 Workbench 执行环境检查，或完成 Sprint29.14 中的 SSH Key / deploy 用户方案。

## 3. Docker 状态

本地生产 Compose 静态检查：

```bash
PRODUCTION_ENV_FILE=.env.production.example \
docker compose --env-file .env.production.example -f docker-compose.prod.yml config --services
```

服务清单：

```text
redis
postgres
backend
worker
nginx
```

镜像 / 构建目标：

```text
tiantong-ai-cloud-nginx
postgres:16
redis:7
tiantong-ai-cloud-backend
tiantong-ai-cloud-worker
```

结论：

- 本地 production compose 静态配置可渲染。
- 生产服务器 Docker 运行状态未确认，原因是 SSH 认证失败。

## 4. Nginx 状态

本地配置文件：

- `nginx/production.conf`

已确认：

- HTTP 跳 HTTPS。
- TLS 证书路径配置存在。
- HSTS 存在。
- `X-Content-Type-Options` 存在。
- `X-Frame-Options` 存在。
- `Referrer-Policy` 存在。
- `Permissions-Policy` 存在。
- 登录限流存在。
- API 限流存在。
- `/api` 反代到 backend。
- `/health` / `/ready` 反代到 backend。
- 静态页面 fallback 存在。

生产服务器 Nginx 状态：

- 未确认。
- 需要 Workbench 或 SSH 进入服务器后执行 `docker compose ps` 和页面检查。

## 5. PostgreSQL

本地 production compose 配置：

- 使用 `postgres:16`。
- 使用 named volume `postgres_data`。
- 未发布公网端口。
- 配置 healthcheck。
- `.env.production.example` 要求 `POSTGRES_ADMIN_PASSWORD`。
- 应用运行时 `DATABASE_URL` 使用低权限用户 `tiantong_app`。

生产服务器状态：

- 未确认。

正式部署前必须确认：

```text
[ ] PostgreSQL 容器 healthy
[ ] 数据库已备份
[ ] tiantong_app 低权限用户存在
[ ] DATABASE_URL 使用 tiantong_app
[ ] 5432 未对公网开放
```

## 6. Redis

本地 production compose 配置：

- 使用 `redis:7`。
- 使用 appendonly。
- 启用 `--requirepass`。
- 使用 named volume `redis_data`。
- 未发布公网端口。
- 配置带密码 healthcheck。

生产服务器状态：

- 未确认。

正式部署前必须确认：

```text
[ ] REDIS_PASSWORD 已设置强密码
[ ] REDIS_URL 包含密码
[ ] Redis 容器 healthy
[ ] 6379 未对公网开放
```

## 7. 环境变量

模板文件：

- `.env.production.example`

已确认字段：

- `APP_ENV=production`
- `DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_ADMIN_USER`
- `POSTGRES_ADMIN_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_URL`
- `JWT_SECRET`
- `ADMIN_RESET_PASSWORD`
- `AI_PROVIDER`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `TLS_CERT_PATH`
- `TLS_KEY_PATH`
- `HTTP_PORT`
- `HTTPS_PORT`

生产服务器要求：

```text
[ ] .env.production 已创建
[ ] .env.production 权限为 600
[ ] .env.production 无 <...> 占位符
[ ] JWT_SECRET 为长随机值
[ ] REDIS_PASSWORD 为强密码
[ ] POSTGRES_ADMIN_PASSWORD 为强密码
[ ] OPENAI_API_KEY / DEEPSEEK_API_KEY 按审批结果为空或配置
```

当前状态：

- 服务器真实 `.env.production` 未确认。

## 8. TLS 准备

本地 production compose 配置：

- `TLS_CERT_PATH` 挂载到 `/etc/nginx/certs/fullchain.pem`
- `TLS_KEY_PATH` 挂载到 `/etc/nginx/certs/privkey.pem`
- 只读挂载。

正式部署前必须确认：

```text
[ ] TLS_CERT_PATH 文件存在
[ ] TLS_KEY_PATH 文件存在
[ ] 证书未过期
[ ] 私钥权限受限
[ ] nginx 容器可读取证书
```

当前状态：

- 服务器 TLS 文件未确认。

## 9. 安全组要求

正式部署前必须确认阿里云安全组：

```text
[ ] 80 对公网开放
[ ] 443 对公网开放
[ ] SSH / Workbench 仅可信来源访问
[ ] 5432 不对公网开放
[ ] 6379 不对公网开放
[ ] 8000 不对公网开放
```

当前状态：

- 未在本轮远程确认。
- 需要老板在阿里云控制台或 Workbench 环境中确认。

## A. 是否达到正式部署条件

当前结论：尚未达到正式部署条件。

已满足：

- Sprint29.16 本地提交已完成。
- GitHub main 已同步到 `03b4e652a66e1943b5775641cbf02df89f44aab0`。
- 本地 production compose 静态配置可渲染。
- Docker dry-run build 已在 Sprint29.16 通过。
- `deploy.sh` 已统一使用 `.env.production`。
- systemd service 已统一读取 `.env.production`。

未满足：

- 阿里云 SSH 认证仍失败。
- 生产服务器 Docker / Nginx / PostgreSQL / Redis 运行态未确认。
- 服务器 `.env.production` 未确认。
- TLS 证书未确认。
- 数据库备份未确认。
- 阿里云安全组未确认。

## B. 部署前最后风险

高风险：

1. 未完成服务器环境检查直接部署。
2. 未备份数据库直接执行 migration。
3. `.env.production` 仍含占位符。
4. TLS 证书路径错误导致 nginx 无法启动。
5. 5432 / 6379 / 8000 暴露公网。
6. owner/admin 登录无法验收。

中风险：

1. Docker build 在服务器侧失败。
2. worker 启动但任务队列异常。
3. Redis 密码配置与 `REDIS_URL` 不一致。
4. Cookie Secure 与 HTTPS 配置不一致。

## C. Sprint29.18 正式部署计划

进入 Sprint29.18 前必须由老板确认：

```text
[ ] 通过 Workbench 或 SSH 完成服务器只读检查
[ ] 目标部署 commit 为 03b4e652a66e1943b5775641cbf02df89f44aab0
[ ] .env.production 已准备且无占位符
[ ] PostgreSQL 已备份
[ ] Redis 密码已确认
[ ] PostgreSQL 低权限用户已确认
[ ] TLS 证书已确认
[ ] 阿里云安全组已确认
[ ] 回滚负责人已确认
[ ] 部署窗口已确认
```

Sprint29.18 计划执行顺序：

1. 进入阿里云服务器。
2. 确认服务器环境。
3. `git fetch origin main`。
4. `git reset --hard origin/main`。
5. 确认 HEAD 为 `03b4e652a66e1943b5775641cbf02df89f44aab0`。
6. 检查 `.env.production`。
7. 渲染 `docker-compose.prod.yml`。
8. 备份 PostgreSQL。
9. build backend / worker / nginx。
10. 执行 Alembic migration。
11. 启动服务。
12. 验证 `/api/health`、`/api/ready`。
13. 验证登录、老板驾驶舱、AI员工中心、Task Center。
14. 检查 backend / worker / nginx 日志。

当前建议：

- 暂停正式部署。
- 先解决 SSH / Workbench 服务器检查阻塞。
- 老板确认服务器环境后，再进入 Sprint29.18。
