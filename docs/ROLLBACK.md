# V1.0.1 回滚说明

## 回滚原则

- 先保护数据，再回滚服务。
- 不删除数据库 Volume。
- 不删除 Redis 数据。
- 不覆盖生产备份。

## 回滚命令

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --no-deps backend worker nginx
```

如需要恢复上一版本镜像，请回到上一个稳定 tag 对应镜像。

## 数据库

- 仅在确认迁移或数据损坏时使用备份恢复。
- 先验证备份可读，再执行恢复。
