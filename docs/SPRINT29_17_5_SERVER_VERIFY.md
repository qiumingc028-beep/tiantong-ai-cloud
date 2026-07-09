# Sprint29.17.5 阿里云服务器只读环境检查报告

目标：使用老板配置的 SSH Key 对阿里云 ECS 做正式部署前只读环境检查。

执行边界：

- 未执行 `docker compose up`
- 未启动服务
- 未拉取代码
- 未执行数据库迁移
- 未修改服务器文件
- 未修改业务代码

## A. 服务器环境结果

### A1. SSH 连接

连接方式：

```text
ssh -i ~/.ssh/tiantong-prod-key.pem root@120.24.79.232
```

结果：

```text
PASS
```

服务器身份：

```text
user: root
host: iZwz9aedhf4dbph9rqm8a0Z
time: Thu Jul 9 13:00:04 CST 2026
```

### A2. Docker 版本

```text
Docker version 29.1.3, build 29.1.3-0ubuntu3~24.04.2
```

结果：

```text
PASS
```

### A3. Docker Compose 版本

```text
Docker Compose version 2.40.3+ds1-0ubuntu1~24.04.1
```

结果：

```text
PASS
```

### A4. Git 版本

项目目录 Git 信息：

```text
branch: main
remote: https://github.com/qiumingc028-beep/tiantong-ai-cloud.git
current commit: 114bbd71709808001b6433dc0b32539edfb02c26
commit message: Merge pull request #1 from qiumingc028-beep/sprint15-skill-research
```

结果：

```text
PARTIAL
```

说明：

- Git 仓库存在。
- 远程仓库正确。
- 但服务器当前 commit 明显落后于 GitHub main 最新部署目标 `03b4e652a66e1943b5775641cbf02df89f44aab0`。

### A5. Python / Node

本轮未单独输出 Python / Node 版本。

说明：

- 当前生产运行主要依赖 Docker 容器。
- 若 Sprint29.18 需要完整宿主机环境记录，应补充执行：

```bash
python3 --version
node --version
```

### A6. Nginx

宿主机 Nginx 版本：

```text
nginx version: nginx/1.24.0 (Ubuntu)
```

容器状态：

```text
tiantong-ai-cloud-nginx-1 nginx:1.27 Up About an hour 0.0.0.0:80->80/tcp, [::]:80->80/tcp
```

结果：

```text
PARTIAL
```

说明：

- 旧版 nginx 容器正在运行。
- 当前仅监听 80。
- 443 未监听，说明 HTTPS 生产配置尚未启用。

### A7. PostgreSQL 状态

Docker 容器：

```text
tiantong-ai-cloud-postgres-1 postgres:16 Up About an hour (healthy) 5432/tcp
```

宿主机 systemd：

```text
postgresql active
```

端口监听：

```text
127.0.0.1:5432
127.0.1.1:5432
```

结果：

```text
PASS WITH NOTE
```

说明：

- PostgreSQL 容器 healthy。
- 5432 当前仅监听 localhost 地址，未发现公网监听。
- 宿主机也存在 active PostgreSQL 服务，需要部署前确认是否仍需要，避免和容器数据库职责混淆。

### A8. Redis 状态

Docker 容器：

```text
tiantong-ai-cloud-redis-1 redis:7 Up About an hour (healthy) 6379/tcp
```

宿主机 systemd：

```text
redis active
redis-server active
```

端口监听：

```text
127.0.0.1:6379
[::1]:6379
```

结果：

```text
PASS WITH NOTE
```

说明：

- Redis 容器 healthy。
- 6379 当前仅监听 localhost / ::1，未发现公网监听。
- 宿主机 Redis 服务也 active，需要部署前确认是否仍需要，避免和容器 Redis 职责混淆。

### A9. 磁盘空间

```text
/               99G   6.1G   88G   7%
/data          196G   105M  186G   1%
```

结果：

```text
PASS
```

说明：

- 磁盘空间充足。
- `/data` 可作为备份和部署数据目录。

### A10. 内存

```text
total: 7.1Gi
used: 882Mi
free: 5.5Gi
available: 6.2Gi
swap: 0B
```

结果：

```text
PASS
```

说明：

- 当前内存充足。
- 未配置 swap，不是阻断项，但生产长期运行可后续评估。

### A11. 端口监听

本轮检查端口：

- `80`
- `443`
- `5432`
- `6379`
- `8000`

结果：

```text
80:   0.0.0.0 / [::] docker-proxy listening
443:  not listening
5432: 127.0.0.1 / 127.0.1.1 only
6379: 127.0.0.1 / [::1] only
8000: 127.0.0.1 only
```

结论：

- 80 对公网监听。
- 443 未启用。
- 5432 / 6379 / 8000 未发现公网监听。

### A12. 项目目录

检查目录：

```text
/root/tiantong-ai-cloud
```

结果：

```text
PASS
```

当前目录存在，包含旧部署文件：

```text
Dockerfile
docker-compose.yml
deploy.sh
backend/
frontend/
nginx/
docs/
```

Git 状态：

```text
current commit: 114bbd71709808001b6433dc0b32539edfb02c26
untracked:
  .env.save
  .env.save.1
  backend/ai_employees/
```

生产配置文件检查：

```text
docker-compose.prod.yml: missing
Dockerfile.backend: missing
Dockerfile.worker: missing
Dockerfile.frontend: missing
nginx/production.conf: missing
.env.production: missing
.env.production.example: missing
```

结果：

```text
BLOCKED
```

说明：

- 服务器项目目录存在，但仍是旧版本。
- Sprint29 生产部署配置尚未同步到服务器。
- 当前不能直接执行 Sprint29 生产部署。

## B. 缺少配置

服务器当前缺少：

1. 最新 GitHub main commit：
   - 目标：`03b4e652a66e1943b5775641cbf02df89f44aab0`
   - 当前：`114bbd71709808001b6433dc0b32539edfb02c26`
2. `docker-compose.prod.yml`
3. `Dockerfile.backend`
4. `Dockerfile.worker`
5. `Dockerfile.frontend`
6. `nginx/production.conf`
7. `.env.production.example`
8. `.env.production`
9. HTTPS 443 监听
10. TLS 证书路径确认
11. 数据库备份文件确认
12. PostgreSQL 低权限应用用户确认
13. Redis 生产密码确认

## C. 是否允许进入 Sprint29.18 正式部署

当前结论：

```text
不允许直接进入正式部署。
允许进入 Sprint29.18 正式部署前同步阶段。
```

原因：

- 服务器环境基础可用：Docker、Compose、磁盘、内存、容器运行状态均正常。
- 但服务器代码严重落后，缺少 Sprint29 生产配置。
- `.env.production` 不存在。
- 443 / HTTPS 尚未启用。
- 生产备份和生产变量尚未确认。

Sprint29.18 前必须完成：

```text
[ ] 记录当前服务器旧 commit：114bbd71709808001b6433dc0b32539edfb02c26
[ ] 备份当前 /root/tiantong-ai-cloud/.env
[ ] 备份当前数据库
[ ] git fetch origin main
[ ] git reset --hard origin/main
[ ] 确认 HEAD 为 03b4e652a66e1943b5775641cbf02df89f44aab0
[ ] 创建 .env.production
[ ] 确认 .env.production 无占位符
[ ] 确认 TLS 证书
[ ] 渲染 docker-compose.prod.yml
[ ] 再执行正式部署
```

## D. 下一步建议

建议 Sprint29.18 拆成两个步骤：

1. 生产代码同步和配置准备：
   - 拉取 GitHub main
   - 不启动服务
   - 不迁移数据库
   - 只确认生产文件到位
2. 正式部署：
   - 数据库备份
   - build
   - migration
   - up
   - health / ready / 登录 / 页面验收

当前应等待老板确认后再进入 Sprint29.18。
