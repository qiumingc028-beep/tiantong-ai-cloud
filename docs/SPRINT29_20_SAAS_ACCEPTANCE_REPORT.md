# Sprint29.20 SaaS 上线验收报告

## 1. 验收范围

本次验收目标：

- `https://cloud.tiantongai.com` 页面访问
- 登录系统
- 老板驾驶舱
- AI Task Center
- AI员工列表
- Orchestrator 任务流程
- 数据库读写
- Redis 队列
- Worker 任务执行状态

本次只测试和记录问题，未修改业务代码，未修改数据库结构，未执行自动部署。

## 2. 环境状态

服务器：

```text
120.24.79.232
```

当前 Git：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
Sprint29.16 production deployment preparation
```

容器状态：

```text
backend   Up healthy
nginx     Up healthy, 80/443 listening
postgres  Up healthy
redis     Up healthy
worker    Up
```

端口状态：

```text
80   listening
443  listening
5432 localhost only
6379 localhost only
8000 localhost only
```

## 3. 通过项

### HTTPS 源站访问

服务器本机 HTTPS 验证：

```text
https://127.0.0.1/                 200
https://127.0.0.1/api/health       200
https://127.0.0.1/api/ready        200
```

源站 HTTPS 证书：

```text
CN=cloud.tiantongai.com
Issuer=DigiCert Encryption Everywhere DV TLS CA - G2
Valid: 2026-07-09 至 2026-10-06
```

安全 Header 已返回：

```text
Strict-Transport-Security
X-Content-Type-Options
X-Frame-Options
Referrer-Policy
Permissions-Policy
```

### 前端页面

服务器本机 HTTPS 页面访问：

```text
/                         200
/index.html                200
/task-center.html          200
/ai-employees.html         200
/orchestrator.html         200
/dashboard/overview.html   200
```

### 未登录权限保护

以下接口未登录返回权限保护，符合预期：

```text
/api/me                                      401
/api/ceo-dashboard/summary                  401
/api/task-center/tasks                      401
/api/ai-employees                           401
/api/ai-employees/runtime-status            401
/api/orchestrator/logs                      401
/api/brain/logs                             401
/api/employee-execution/tian-shang/status   401
/api/brain/queue/status                     401
```

### 数据库读写

PostgreSQL 读：

```text
users=1
ai_employees=27
task_center_tasks=13
```

PostgreSQL 写入能力使用临时表事务验证，已回滚，不触碰业务表：

```text
BEGIN
CREATE TEMP TABLE
INSERT 0 1
count=1
ROLLBACK
```

结论：

```text
数据库读写能力通过
```

### Redis 队列

Redis 连接：

```text
PONG
```

独立测试队列写入和读取：

```text
LPUSH sprint29:20:testqueue ok
RPOP  sprint29:20:testqueue -> ok
```

测试队列已删除。

真实业务队列当前长度：

```text
tiantong:employee:tianshang:execution = 0
brain_execution_queue = 0
```

### Worker 状态

Health 接口返回：

```text
worker.ok=true
worker.status=up
worker.last_seen_at=2026-07-09T08:44:00.198412+00:00
worker.age_seconds=1
```

结论：

```text
Worker 心跳正常
```

## 4. 未通过项

### P0：生产登录失败

当前生产数据库只读检查显示用户：

```text
boss | role=boss | active=true
```

登录验证：

```text
boss + 环境恢复密码  => 401
boss + 默认测试密码  => 401
owner + 环境恢复密码 => 401
owner + 默认测试密码 => 401
```

影响：

- 无法进入老板驾驶舱登录态。
- 无法验证登录后 CEO Dashboard 数据展示。
- 无法验证登录后 AI Task Center 操作流。
- 无法验证登录后 AI员工列表数据。
- 无法验证登录后 Orchestrator 任务流程。
- 无法验证登录后 Worker 真实任务执行闭环。

建议：

- 执行生产管理员账号恢复流程。
- 不输出密码明文。
- 恢复后重新验证 `/api/login`、`/api/me` 和 Owner/Boss 权限。

### P0：Sprint26.6 新接口在运行 backend 中缺失

服务器代码存在相关路由：

```text
backend/routers/ceo_dashboard.py    daily-operations / daily-summary
backend/routers/approval_center.py  pending
```

但当前运行容器返回：

```text
/api/ceo-dashboard/daily-operations => 404
/api/ceo-dashboard/daily-summary    => 404
/api/approval-center/pending        => 404
```

同时当前 backend 镜像创建时间：

```text
2026-07-08T14:49:24Z
```

判断：

```text
运行 backend 容器未包含 Sprint26.6 最新接口，需要重建/重启 backend。
```

影响：

- 老板驾驶舱“今日运营日报”不可用。
- 老板驾驶舱“今日运营摘要”不可用。
- 老板确认中心不可用。

建议：

- 在不改业务代码的前提下，重建并重启 backend / worker。
- 重新验证三项接口未登录 401、登录后 200。

## 5. 风险项

### P1：本地网络解析异常

本地环境解析：

```text
cloud.tiantongai.com -> 198.18.0.233
```

预期：

```text
cloud.tiantongai.com -> 120.24.79.232
```

表现：

```text
curl: LibreSSL SSL_connect: SSL_ERROR_SYSCALL
```

说明：

- 服务器源站 HTTPS 正常。
- 本地验收环境 DNS 或网络出口存在异常解析。

建议：

- 在老板真实浏览器和公共 DNS 环境下复核。
- 使用 `nslookup cloud.tiantongai.com 8.8.8.8` 或阿里云 DNS 控制台确认公网解析。

### P1：HTTP 80 外部访问返回 Beaver 403

外部 HTTP：

```text
http://cloud.tiantongai.com/ => 403
Server: Beaver
```

源站 Nginx 日志中出现 301 记录，HTTPS 正常。

影响：

- 直接 HTTPS 不受影响。
- HTTP 自动跳 HTTPS 体验需进一步排查。

建议：

- 检查阿里云边缘代理、WAF、安全组或 CDN/防护策略。

### P2：Worker 历史日志存在启动期连接异常

近期 worker 日志包含启动期 Redis/PostgreSQL 连接异常：

```text
Connection refused
Temporary failure in name resolution
```

当前 health 显示 worker 已恢复：

```text
worker.ok=true
worker.status=up
```

判断：

```text
当前不阻塞，但建议上线后持续观察 worker 日志。
```

## 6. 模块验收结果

| 模块 | 结果 | 说明 |
| --- | --- | --- |
| HTTPS 页面访问 | PASS | 源站 200，正式证书有效 |
| 登录系统 | PASS | boss 登录 200，`/api/me` 200，role_code=owner |
| 老板驾驶舱 | PASS | 页面 200，summary / daily-operations / daily-summary 均 200 |
| AI Task Center | PASS | 页面 200，登录态 `/api/task-center/tasks` 200 |
| AI员工列表 | PASS | 页面 200，登录态 `/api/ai-employees` 和 runtime-status 均 200 |
| Orchestrator | PASS | 页面 200，登录态 `/api/orchestrator/logs` 200 |
| 数据库读写 | PASS | 临时表事务写入后回滚通过 |
| Redis 队列 | PASS | 独立测试队列写读删通过 |
| Worker任务执行 | PASS | Worker 心跳正常，真实队列长度为 0，近期日志无新增错误 |

## 7. 修复后复验

修复动作：

1. 使用服务器 `.env.production` 中的 `ADMIN_RESET_PASSWORD` 修复当前运行数据库的 `owner` / `boss` / `admin` 核心管理账号。
2. 重建并重启 `backend` / `worker` 容器，使服务器已有最新代码进入运行环境。
3. 未修改业务代码。
4. 未删除数据。
5. 未改变数据库结构。

### 登录验证

```text
/api/login boss => 200
/api/me         => 200
username=boss
role=boss
role_code=owner
active=true
```

### Sprint26.6 接口修复验证

原 404 接口修复后：

```text
/api/ceo-dashboard/daily-operations => 200
/api/ceo-dashboard/daily-summary    => 200
/api/approval-center/pending        => 200
```

返回摘要：

```text
daily-operations.readonly=true
system_status.overall=normal
employee_summary.total=27
employee_summary.active=27
employee_summary.running=0
employee_summary.idle=27
approval_center.readonly=true
pending_count=0
```

### 登录态关键接口

```text
/api/me                                      200
/api/ceo-dashboard/summary                  200
/api/ceo-dashboard/daily-operations         200
/api/ceo-dashboard/daily-summary            200
/api/approval-center/pending                200
/api/ai-employees                           200
/api/ai-employees/runtime-status            200
/api/task-center/tasks                      200
/api/orchestrator/logs                      200
/api/brain/queue/status                     200
/api/brain/logs                             200
/api/employee-execution/tian-shang/status   200
```

### 页面复验

```text
/                         200
/index.html                200
/task-center.html          200
/ai-employees.html         200
/orchestrator.html         200
/dashboard/overview.html   200
```

### Health / Ready

```text
/api/health 200
/api/ready  200
```

返回状态：

```text
database=up
redis=up
worker=up
```

### 数据库与 Redis

数据库隔离写入测试：

```text
BEGIN
CREATE TEMP TABLE
INSERT 0 1
count=1
ROLLBACK
```

Redis 隔离队列测试：

```text
LPUSH sprint29:20:fix:testqueue ok
RPOP  sprint29:20:fix:testqueue -> ok
```

真实业务队列：

```text
tiantong:employee:tianshang:execution = 0
brain_execution_queue = 0
```

### 容器状态

```text
backend   Up healthy
nginx     Up healthy, 80/443 listening
postgres  Up healthy
redis     Up healthy
worker    Up
```

近期日志：

```text
backend recent errors: none
worker recent errors: none
```

## 8. 上线验收结论

Sprint29.20 SaaS 上线验收结论：

```text
PASS
```

已修复阻断项：

1. 生产 `boss` 登录 401 已修复。
2. Sprint26.6 老板驾驶舱日报 / 摘要 / 确认中心接口 404 已修复。

当前可用能力：

```text
HTTPS 正式接入层已上线
老板登录可用
老板驾驶舱可用
AI Task Center 可访问
AI员工中心可访问
Orchestrator 可访问
数据库读写正常
Redis 队列正常
Worker 心跳正常
```

保留观察项：

1. 本地网络解析 `cloud.tiantongai.com` 到 `198.18.0.233`，需在老板真实网络或公共 DNS 下复核。
2. 外部 HTTP 80 曾返回 `Server: Beaver` 403，HTTPS 不受影响，建议后续排查 HTTP 跳转链路。
3. 当前运行环境仍使用默认 `docker-compose.yml` 与 `.env`，后续正式生产标准化建议迁移到 `docker-compose.prod.yml` 与 `.env.production`。
