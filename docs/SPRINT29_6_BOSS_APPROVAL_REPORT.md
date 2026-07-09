# Sprint29.6 老板部署审批报告

目标：在阿里云正式部署前，向老板汇总当前上线状态、已通过项目、未解决风险、人工确认事项、预计影响和回滚方案。

执行边界：

- 本报告只用于审批
- 当前不连接服务器
- 当前不执行部署
- 当前不修改业务代码
- 当前不修改数据库结构

## 1. 当前系统上线状态

当前状态：待部署审批。

已完成：

- V1 冻结版本已完成内部运行验收。
- Sprint28 天监安全审计已完成。
- Sprint29 生产部署方案已完成。
- Sprint29.1 生产配置准备已完成。
- Sprint29.2 部署配置验收报告已完成。
- Sprint29.3 生产部署冻结检查已完成。
- Sprint29.4 生产部署 Runbook 已完成。
- Sprint29.5 生产部署最终审批检查已完成。
- Sprint29.6 部署执行计划和最终检查表已完成。

当前尚未执行：

- 未连接阿里云 ECS。
- 未执行生产部署。
- 未执行生产数据库迁移。
- 未切换公网流量。

## 2. 已通过项目

### 2.1 生产配置

已通过：

- `docker-compose.prod.yml` 可渲染。
- `.env.production.example` 只包含占位符，不包含真实密钥。
- `.env.production` 已加入 `.gitignore`。
- PostgreSQL / Redis / backend 不暴露公网端口。
- Redis 已设计密码认证。
- backend / worker 使用生产环境变量。
- nginx 暴露 80 / 443。

### 2.2 Nginx 安全

已通过：

- HTTP 跳 HTTPS。
- TLS 配置存在。
- 安全 Header 存在：
  - HSTS
  - `X-Content-Type-Options`
  - `X-Frame-Options`
  - `Referrer-Policy`
  - `Permissions-Policy`
- `/api/login` 登录限流存在。
- `/api/` 基础限流存在。
- 隐藏文件访问禁止。

### 2.3 部署文档

已通过：

- 部署前检查清单完整。
- 执行命令清单完整。
- 成功判断标准完整。
- 回滚触发条件完整。
- 禁止操作明确：
  - 不删除 volume
  - 不执行 downgrade
  - 不重建数据库
  - 不执行危险删除

### 2.4 安全边界

已通过：

- 不新增业务功能。
- 不修改 Task Center / AI员工 / Orchestrator 业务逻辑。
- 不改变数据库结构。
- 不提交真实密钥。
- `docs/SSH_FIX_REPORT.md` 继续排除，不进入提交。

## 3. 未解决风险

### 3.1 Cookie Secure 风险

风险等级：中。

说明：

- Nginx 生产配置已准备 HTTPS。
- 但后端 cookie 仍需要后续小改，根据 `APP_ENV=production` 设置 `secure=True`。

建议：

- 如果本次是受控试运行，可接受短期风险。
- 如果直接公网长期运行，建议先安排天王修复并交天监审计。

### 3.2 PostgreSQL 低权限用户依赖人工创建

风险等级：中。

说明：

- 配置已要求使用 `tiantong_app`。
- 生产数据库内必须先创建低权限用户并授予业务表权限。

必须确认：

- `tiantong_app` 存在。
- `tiantong_app` 不是 Superuser。
- `DATABASE_URL` 使用 `tiantong_app`。

### 3.3 Redis 密码依赖人工配置

风险等级：中。

说明：

- 配置已启用 `--requirepass`。
- `.env.production` 中 `REDIS_PASSWORD` 与 `REDIS_URL` 必须一致。

必须确认：

- Redis 密码为强随机值。
- 阿里云安全组未开放 6379。

### 3.4 TLS 证书依赖人工准备

风险等级：中。

说明：

- Nginx 生产配置需要证书路径。
- 证书缺失或过期会导致 nginx 启动失败。

必须确认：

- `TLS_CERT_PATH` 正确。
- `TLS_KEY_PATH` 正确。
- 证书未过期。

### 3.5 容器硬化未完全完成

风险等级：低到中。

说明：

- 当前未完成非 root 用户运行。
- 当前未完成 read-only rootfs。
- 当前未完成最小 capability 策略。

建议：

- 不阻塞 V1 受控生产部署。
- 纳入 V2 生产硬化。

## 4. 阿里云部署需要老板确认事项

请老板确认：

```text
[ ] 是否确认进入阿里云正式部署窗口
[ ] 是否确认目标 GitHub main commit
[ ] 是否确认目标 ECS 服务器
[ ] 是否确认域名解析已准备
[ ] 是否确认 SSL 证书已准备
[ ] 是否确认 .env.production 已准备且不含占位符
[ ] 是否确认 PostgreSQL 已备份
[ ] 是否确认 tiantong_app 低权限用户已创建
[ ] 是否确认 Redis 密码已设置
[ ] 是否确认阿里云安全组仅开放必要端口
[ ] 是否确认 Cookie Secure 短期风险处理方式
[ ] 是否确认部署失败时允许按 Runbook 回滚
```

## 5. 部署预计影响

### 5.1 服务影响

预计影响：

- backend / worker / nginx 会重建或重启。
- 部署期间可能出现短暂不可用。
- PostgreSQL / Redis 不应删除、不应重建。

预计影响范围：

- 老板驾驶舱
- Task Center
- AI员工中心
- Execution Engine
- Brain Center
- 其他前端页面

### 5.2 数据影响

预计影响：

- 不改变数据库结构以外的业务数据。
- Alembic 会执行到最新 head。
- 部署前必须完成数据库备份。

禁止：

- 不执行 downgrade。
- 不删除数据库 volume。
- 不重建数据库。

### 5.3 安全影响

预计影响：

- Redis 从无密码模式升级为密码模式。
- backend / worker 通过 `REDIS_URL` 使用 Redis 密码。
- Nginx 切换为 HTTPS 入口。
- HTTP 自动跳转 HTTPS。

需要注意：

- Cookie Secure 后端配合仍待小修。

## 6. 回滚方案

### 6.1 回滚触发条件

满足任一条件，必须暂停上线并回滚或修复：

1. Git HEAD 与审批 commit 不一致。
2. `.env.production` 有占位符或权限不是 600。
3. PostgreSQL 备份失败。
4. `tiantong_app` 不存在或权限过高。
5. Redis 密码和 `REDIS_URL` 不一致。
6. TLS 证书不存在或过期。
7. Docker build 失败。
8. Alembic migration 失败。
9. backend / postgres / redis / nginx 非 healthy。
10. worker 持续退出或重启。
11. `/api/health` 或 `/api/ready` 非 200。
12. 核心页面 404 / 500 / 白屏。
13. 未登录管理 API 返回 200。
14. 日志出现 password / token / secret / private key 泄露。
15. 发现数据库或 Redis 端口公网暴露。

### 6.2 Git 回滚

```bash
git log --oneline -5
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 6.3 停止业务层

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend worker
```

### 6.4 单服务重启

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate redis backend worker
```

### 6.5 禁止操作

未经老板明确确认，禁止：

```bash
docker volume rm
docker compose down -v
alembic downgrade
rm -rf /var/lib/postgresql/data
```

## 7. 是否建议进入 Sprint29.7

建议进入 Sprint29.7，但条件是老板先完成以下确认：

- 确认部署窗口。
- 确认目标 ECS。
- 确认 `.env.production`。
- 确认 PostgreSQL 备份和低权限用户。
- 确认 Redis 密码。
- 确认 TLS 证书。
- 确认阿里云安全组。
- 确认 Cookie Secure 短期风险处理方式。

建议 Sprint29.7 定位：

> 天盾阿里云正式部署执行与上线验证。

如果老板不接受 Cookie Secure 短期风险，则应先进入：

> Sprint29.6.1 Cookie Secure 小修复与安全复审。

## 8. 最终结论

当前系统已具备进入阿里云正式部署的准备条件。

不建议跳过人工确认直接部署。

等待老板确认后，方可进入 Sprint29.7 正式部署执行。
