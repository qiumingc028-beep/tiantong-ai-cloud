# 天统AI云中台 V1 发布检查清单

## 1. 环境检查

- [ ] 已安装 Docker。
- [ ] 已安装 Docker Compose。
- [ ] 当前仓库代码已拉取到目标机器。
- [ ] 当前分支和发布版本已确认。
- [ ] 根目录不存在真实生产密钥文件。
- [ ] `.env.example` 存在。
- [ ] 本地开发启动前已从 `.env.example` 复制 `.env`。
- [ ] 生产部署前已从 `.env.production.example` 创建 `.env.production`。
- [ ] `.env`、`.env.production` 未进入 Git 管理。
- [ ] `.gitignore` 包含 `.env` 和 `.env.production`。

## 2. Docker 检查

本地开发：

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
docker compose ps
```

生产部署：

```bash
cp .env.production.example .env.production
./deploy.sh
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

检查项：

- [ ] `docker compose config` 通过。
- [ ] `postgres` 容器启动。
- [ ] `redis` 容器启动。
- [ ] `backend` 容器启动并 healthy。
- [ ] `worker` 容器启动。
- [ ] `nginx` 容器启动。
- [ ] 未在日志中发现启动失败或迁移失败。

## 3. 数据库检查

```bash
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-tiantong}" -d "${POSTGRES_DB:-tiantong_ai}"
```

检查项：

- [ ] PostgreSQL healthy。
- [ ] Alembic migration 已执行。
- [ ] `/api/health` 返回 `"database": true`。
- [ ] 数据库账号未使用文档示例弱密码进入生产。
- [ ] 生产环境已配置数据库备份方案。

## 4. Redis 检查

```bash
docker compose exec -T redis redis-cli ping
```

检查项：

- [ ] Redis 返回 `PONG`。
- [ ] `/api/health` 返回 `"redis": true`。
- [ ] worker 可连接 Redis。
- [ ] 生产环境 Redis 已设置密码。

## 5. 后端检查

```bash
curl -fsS http://127.0.0.1/api/health
curl -fsS http://127.0.0.1/api/ready
```

检查项：

- [ ] `/api/health` 返回 `status=running`。
- [ ] `/api/ready` 返回 `status=ready`。
- [ ] 登录接口可用。
- [ ] Boss Dashboard API 可用。
- [ ] Task Center API 可用。
- [ ] AI Workforce API 可用。
- [ ] AI Employee Detail API 可用。
- [ ] Orchestrator API 可用。

## 6. 前端检查

访问：

```text
http://127.0.0.1/
http://127.0.0.1/login.html
http://127.0.0.1/ai-workforce.html
http://127.0.0.1/ai-employee-detail.html
http://127.0.0.1/task-center.html
http://127.0.0.1/orchestrator.html
```

检查项：

- [ ] 登录页可打开。
- [ ] Boss Dashboard 可打开。
- [ ] AI员工中心可打开。
- [ ] 员工详情页可打开。
- [ ] Task Center 可打开。
- [ ] Orchestrator 可打开。
- [ ] 页面无明显 404。
- [ ] 页面空数据状态可理解。
- [ ] 页面错误提示可理解。

## 7. 测试检查

安全测试：

```bash
python -m pytest tests/test_auth.py
```

完整测试：

```bash
python -m pytest tests/
```

Docker Python 3.12 完整测试：

```bash
docker run --rm \
  -v "$PWD:/app" \
  -w /app \
  -e DATABASE_URL=sqlite:///./test.db \
  -e REDIS_URL=redis://redis:6379/0 \
  -e JWT_SECRET=tiantong-test-secret-32-bytes-minimum \
  tiantong-ai-cloud-backend \
  python -m pytest tests/
```

检查项：

- [ ] `tests/test_auth.py` 通过。
- [ ] 完整 `pytest tests/` 通过。
- [ ] 不存在根目录真实 `.env` 导致的安全测试失败。
- [ ] 测试产生的本地临时文件已清理。

## 8. 安全检查

检查项：

- [ ] 根目录没有提交 `.env`。
- [ ] 根目录没有提交 `.env.production`。
- [ ] 未提交真实 API Key。
- [ ] 未提交云厂商 AccessKey。
- [ ] `.env.example` 不包含真实密钥。
- [ ] `.env.production.example` 只包含占位符。
- [ ] AI员工中心保留 `readonly=true`。
- [ ] 高风险动作保留 `boss_confirm=true`。
- [ ] 高风险动作保留 `security_audited=true`。
- [ ] V1 未接入 OpenClaw。
- [ ] V1 未接入 n8n。
- [ ] V1 未新增自动执行入口。

## 9. 发布结论

全部检查通过后标记：

```text
V1 READY = YES
```

如任一安全测试失败，标记：

```text
V1 READY = NO
```
