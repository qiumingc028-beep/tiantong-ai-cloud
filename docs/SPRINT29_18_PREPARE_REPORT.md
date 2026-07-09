# Sprint29.18 正式部署前置同步报告

目标：完成生产服务器代码同步准备，并确认正式部署前仍需补齐的环境配置。此次仅同步代码和执行只读检查，不执行正式部署。

执行边界：

- 已使用 SSH Key 连接生产服务器
- 已执行 GitHub main 同步
- 未执行 `docker compose up`
- 未执行数据库迁移
- 未启动或重启生产服务
- 未删除数据
- 未开放 `5432` / `6379` 公网
- 未修改业务代码

## A. 当前服务器状态

### A1. 服务器连接

连接方式：

```text
ssh -i ~/.ssh/tiantong-prod-key.pem root@120.24.79.232
```

结果：

```text
PASS
```

### A2. 代码同步前状态

项目目录：

```text
/root/tiantong-ai-cloud
```

同步前 commit：

```text
114bbd71709808001b6433dc0b32539edfb02c26
114bbd7 Merge pull request #1 from qiumingc028-beep/sprint15-skill-research
```

同步前未跟踪文件：

```text
.env.save
.env.save.1
backend/ai_employees/
```

说明：

- 这些未跟踪文件未被删除。
- 本次未执行清理命令。

### A3. 代码同步后状态

执行动作：

```bash
git fetch origin main
git reset --hard origin/main
```

同步后 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
03b4e65 Sprint29.16 production deployment preparation
```

同步结果：

```text
PASS
```

同步后未跟踪文件：

```text
.env.save
.env.save.1
backend/ai_employees/tian_cai/
backend/ai_employees/tian_ce/
```

说明：

- 服务器代码已同步到 GitHub main 最新部署准备版本。
- 未跟踪旧文件仍保留，正式部署前建议人工确认是否需要归档或忽略。

### A4. 当前容器状态

只读检查结果：

```text
tiantong-ai-cloud-worker-1     tiantong-ai-cloud-worker    Up About an hour
tiantong-ai-cloud-backend-1    tiantong-ai-cloud-backend   Up About an hour (healthy)   8000/tcp
tiantong-ai-cloud-nginx-1      nginx:1.27                  Up About an hour             0.0.0.0:80->80/tcp, [::]:80->80/tcp
tiantong-ai-cloud-postgres-1   postgres:16                 Up About an hour (healthy)   5432/tcp
tiantong-ai-cloud-redis-1      redis:7                     Up About an hour (healthy)   6379/tcp
```

说明：

- 当前运行容器仍是同步前已启动的旧运行态。
- 本次未重启容器。
- 本次未执行 production compose。

### A5. 端口状态

只读检查结果：

```text
80:   0.0.0.0 / [::] docker-proxy listening
443:  not listening
5432: 127.0.0.1 / 127.0.1.1 only
6379: 127.0.0.1 / [::1] only
8000: 127.0.0.1 only
```

结论：

- 80 当前公网监听。
- 443 尚未启用。
- 5432 / 6379 / 8000 未发现公网监听。

## B. 同步结果

### B1. GitHub main 最新 commit

目标 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

服务器当前 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

结论：

```text
PASS
```

### B2. 生产部署文件

同步后服务器已存在：

```text
docker-compose.prod.yml
Dockerfile.backend
Dockerfile.worker
Dockerfile.frontend
nginx/production.conf
.env.production.example
```

检查结果：

```text
PASS
```

### B3. .env.production

检查结果：

```text
MISSING .env.production
```

结论：

```text
BLOCKED
```

说明：

- 生产环境变量文件尚未创建。
- 正式部署前必须基于 `.env.production.example` 人工创建 `.env.production`。
- `.env.production` 必须权限为 `600`。
- `.env.production` 不得包含 `<...>` 占位符。

### B4. TLS 配置

检查结果：

```text
NO_ENV_FOR_TLS
```

结论：

```text
BLOCKED
```

说明：

- 因 `.env.production` 缺失，无法读取 `TLS_CERT_PATH` / `TLS_KEY_PATH`。
- `nginx/production.conf` 已具备 HTTPS 配置。
- 服务器证书文件路径仍需人工确认。

### B5. Nginx HTTPS 准备

检查结果：

```text
nginx/production.conf exists
listen 443 ssl http2 exists
ssl_certificate exists
ssl_certificate_key exists
Strict-Transport-Security exists
limit_req exists
proxy_pass exists
```

结论：

```text
CONFIG READY, SERVER TLS FILES NOT CONFIRMED
```

说明：

- 代码层 Nginx HTTPS 配置已就绪。
- 当前运行态 443 未监听，因为尚未执行 production compose。

### B6. PostgreSQL 备份方案

检查结果：

```text
/data/backups/tiantong-ai-cloud: missing
```

结论：

```text
BLOCKED
```

说明：

- 备份目录尚不存在。
- 正式 migration 前必须创建备份目录并完成 PostgreSQL 备份。

### B7. Redis 密码配置

检查结果：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains requirepass
.env.production.example contains REDIS_PASSWORD and REDIS_URL
```

结论：

```text
CONFIG READY, REAL PASSWORD NOT CONFIRMED
```

说明：

- 代码层 Redis 密码机制已存在。
- 真实 `REDIS_PASSWORD` 需在 `.env.production` 中人工配置。

## C. 正式部署前剩余风险

### C1. 阻塞风险

1. `.env.production` 缺失。
2. TLS 证书路径未确认。
3. PostgreSQL 备份目录缺失。
4. PostgreSQL 正式备份尚未执行。
5. Redis 真实密码未确认。
6. PostgreSQL 低权限用户 `tiantong_app` 未确认。
7. 当前 443 未监听，HTTPS 尚未启用。
8. 服务器存在未跟踪旧文件：
   - `.env.save`
   - `.env.save.1`
   - `backend/ai_employees/tian_cai/`
   - `backend/ai_employees/tian_ce/`

### C2. 非阻塞但需注意

1. 当前旧容器仍在运行，本次未重启。
2. 当前 80 对公网开放。
3. 宿主机可能同时存在 PostgreSQL / Redis 服务，需避免与容器职责混淆。
4. 生产 deploy 前应再次确认安全组未开放 `5432` / `6379` / `8000`。

## D. 是否允许进入 Sprint29.18 正式部署

当前结论：

```text
不允许直接进入正式部署。
允许进入 Sprint29.18 正式部署前配置补齐阶段。
```

允许进入正式部署的前置条件：

```text
[ ] 创建 /root/tiantong-ai-cloud/.env.production
[ ] chmod 600 .env.production
[ ] 确认 .env.production 无 <...> 占位符
[ ] 配置 JWT_SECRET
[ ] 配置 POSTGRES_ADMIN_PASSWORD
[ ] 配置 DATABASE_URL 使用 tiantong_app
[ ] 配置 REDIS_PASSWORD 和 REDIS_URL
[ ] 确认 TLS_CERT_PATH 文件存在
[ ] 确认 TLS_KEY_PATH 文件存在
[ ] 创建 /data/backups/tiantong-ai-cloud
[ ] 执行 PostgreSQL 备份
[ ] 确认 tiantong_app 低权限用户存在
[ ] 确认阿里云安全组未开放 5432 / 6379 / 8000
[ ] 确认回滚 commit 和回滚负责人
```

建议下一步：

1. 老板确认进入 Sprint29.18 配置补齐阶段。
2. 只创建 `.env.production` 和备份目录，不启动服务。
3. 验证 production compose config。
4. 完成数据库备份。
5. 再进入正式部署执行。
