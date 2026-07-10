# 天统AI云中台 V1 冻结检查清单

## 1. 冻结目标

冻结版本：

```text
v1.0.0
```

冻结原则：

- 不新增业务功能。
- 不修改数据库结构。
- 不创建 migration。
- 不接入 OpenClaw。
- 不接入 n8n。
- 不新增自动执行入口。
- 保持 `readonly=true`、`boss_confirm=true`、`security_audited=true`。

## 2. 登录系统

- [ ] `/login.html` 可访问。
- [ ] `POST /api/login` 正常。
- [ ] `GET /api/me` 需要登录。
- [ ] Boss / Owner 登录正常。
- [ ] Viewer 权限受限。
- [ ] 登录响应不暴露 password。
- [ ] 登录响应不暴露 password_hash。

## 3. Boss Dashboard

- [ ] `/index.html` 可访问。
- [ ] 页面显示 `老板驾驶舱`。
- [ ] 页面能展示系统状态。
- [ ] 页面能展示任务概况。
- [ ] 页面能展示 AI员工概览。
- [ ] 页面能进入 AI员工相关入口。
- [ ] 无未授权用户访问。

## 4. AI员工中心

- [ ] `/ai-workforce.html` 可访问。
- [ ] 首屏显示 `你的AI员工正在帮你工作`。
- [ ] 能看到 AI员工数量。
- [ ] 能看到正在工作的员工数量。
- [ ] 员工卡片只展示头像、名字、负责什么、当前状态。
- [ ] 员工卡片可进入详情。
- [ ] 保留 `readonly=true`。
- [ ] 保留 `boss_confirm=true`。
- [ ] 保留 `security_audited=true`。
- [ ] 不显示技术字段、API、数据库字段、JSON。
- [ ] 不提供自动执行入口。

## 5. AI员工详情

- [ ] `/ai-employee-detail.html` 可访问。
- [ ] 可从 AI员工中心进入。
- [ ] 可返回 AI员工中心。
- [ ] 页面展示 `我的身份：`。
- [ ] 页面展示 `我负责：`。
- [ ] 页面展示 `今天完成：`。
- [ ] 页面展示 `我正在学习：`。
- [ ] 页面展示 `我的成长：`。
- [ ] 不显示 employee_id。
- [ ] 不显示 API。
- [ ] 不显示数据库字段。
- [ ] 不显示 JSON。
- [ ] 不显示技术日志。
- [ ] 不提供自动升级入口。
- [ ] 不提供修改权限入口。

## 6. Task Center

- [ ] `/task-center.html` 可访问。
- [ ] 任务列表可展示。
- [ ] 任务详情可展示。
- [ ] 创建任务流程清晰。
- [ ] 分配 AI员工流程清晰。
- [ ] 提交结果流程清晰。
- [ ] 验收流程清晰。
- [ ] 审计流程清晰。
- [ ] 未新增绕过人工确认的自动执行入口。

## 7. Orchestrator

- [ ] `/orchestrator.html` 可访问。
- [ ] 回复分析功能可用。
- [ ] Prompt 草稿功能可用。
- [ ] 任务草稿功能可用。
- [ ] Task Center 来源链路可用。
- [ ] 输出仍需人工确认。
- [ ] 不直接调用 Execution Engine。
- [ ] 不接入 OpenClaw。
- [ ] 不接入 n8n。

## 8. Docker

本地开发检查：

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
docker compose ps
```

- [ ] `docker compose config` 通过。
- [ ] `backend` 运行。
- [ ] `worker` 运行。
- [ ] `nginx` 运行。
- [ ] `postgres` 运行。
- [ ] `redis` 运行。

生产部署检查：

```bash
cp .env.production.example .env.production
./deploy.sh
```

- [ ] `.env.production` 已替换占位符。
- [ ] `docker-compose.prod.yml` config 通过。
- [ ] TLS 证书路径正确。
- [ ] Nginx 健康检查通过。

## 9. PostgreSQL

- [ ] PostgreSQL 容器 healthy。
- [ ] `/api/health` 返回 `"database": true`。
- [ ] Alembic migration 已执行。
- [ ] 数据库备份方案可执行。
- [ ] 生产数据库账号不是示例弱密码。

## 10. Redis

- [ ] Redis 容器 healthy。
- [ ] Redis `PING` 返回 `PONG`。
- [ ] `/api/health` 返回 `"redis": true`。
- [ ] Worker 可连接 Redis。
- [ ] 生产 Redis 已配置密码。

## 11. 测试

核心测试：

```bash
python -m pytest tests/test_auth.py
python -m pytest tests/test_ceo_dashboard.py tests/test_task_center.py
python -m pytest tests/test_ai_workforce.py tests/test_ai_employee_detail.py tests/test_ai_employee_detail_frontend.py
```

完整测试：

```bash
python -m pytest tests/
```

Docker Python 3.12 测试：

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

- [ ] `tests/test_auth.py` 通过。
- [ ] 核心流程测试通过。
- [ ] 完整测试通过。
- [ ] 测试后未遗留 `.env`。
- [ ] 测试后未遗留 `test.db`。

## 12. Git 冻结

- [ ] 当前分支确认。
- [ ] 当前 commit 确认。
- [ ] 未提交文件分类完成。
- [ ] V1 相关文件已提交。
- [ ] 历史报告未删除。
- [ ] `v1.0.0` tag 不存在或已确认可覆盖。
- [ ] 创建 tag 前完整测试通过。
- [ ] 创建 tag 后记录 tag commit。

建议 tag 命令：

```bash
git tag -a v1.0.0 -m "release: tiantong ai cloud v1.0.0"
git show v1.0.0 --stat
```

## 13. 冻结结论

全部检查通过后标记：

```text
V1 FREEZE = PASS
V1.0.0 BASELINE READY = YES
```
