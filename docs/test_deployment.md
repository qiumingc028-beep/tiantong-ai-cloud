# Test-only deployment

This entry runs the reviewed checkout as a loopback-only backend for test/UAT. It is forbidden for production use and never calls `deploy.sh`.

## Requirements

- A clean Git worktree at `EXPECTED_COMMIT_SHA`.
- `TIANTONG_ENV=test`.
- The existing project Python runtime through `TEST_PYTHON` (default: `/Users/chenqiuming/.openclaw/runtimes/tiantong-test-r1/bin/python`). Dependencies come from the repository `requirements.txt`; the deployment command never installs or downloads packages.
- Dedicated, labelled test PostgreSQL and Redis containers bound to `127.0.0.1`.
- A database name matching `tiantong_v2_test_[a-z0-9_]+`.

Required connection variables are `TEST_POSTGRES_CONTAINER`, `TEST_POSTGRES_HOST`, `TEST_POSTGRES_PORT`, `TEST_POSTGRES_USER`, `TEST_POSTGRES_PASSWORD`, `TEST_REDIS_CONTAINER`, `TEST_REDIS_HOST`, and `TEST_REDIS_PORT`. Optional variables include `TEST_POSTGRES_ADMIN_DB` (default `postgres`), `TEST_REDIS_DB` (default `0`), `TEST_BACKEND_PORT` (default `59200`), and `TEST_PYTHON`.

Do not write credentials to this repository, command output, tickets, or evidence. Supply them through the process environment.

## Start and status

```bash
TIANTONG_ENV=test \
EXPECTED_COMMIT_SHA="$(git rev-parse HEAD)" \
TEST_RUNTIME_ID=r167-uat \
TEST_DATABASE_NAME=tiantong_v2_test_r167_uat \
TEST_POSTGRES_CONTAINER=tiantong-v2-s1-r70-postgres \
TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=<dynamic-test-port> \
TEST_POSTGRES_USER=<test-user> TEST_POSTGRES_PASSWORD=<from-secure-environment> \
TEST_REDIS_CONTAINER=tiantong-v2-s1-r70-redis \
TEST_REDIS_HOST=127.0.0.1 TEST_REDIS_PORT=<dynamic-test-port> \
bash scripts/deploy_test.sh
```

The backend binds only `http://127.0.0.1:<TEST_BACKEND_PORT>`. PID, metadata, migrations, assets, and logs live under `/tmp/tiantong-test-deploy-<TEST_RUNTIME_ID>/`. Repeating the same command returns `ALREADY_RUNNING` instead of starting a duplicate.

Check `/api/health` and `/api/ready`, or run the guarded smoke suite:

```bash
TEST_BASE_URL=http://127.0.0.1:59200 \
TIANTONG_ENV=test EXPECTED_COMMIT_SHA="$(git rev-parse HEAD)" \
TEST_RUNTIME_ID=r167-uat TEST_DATABASE_NAME=tiantong_v2_test_r167_uat \
<the same dedicated PostgreSQL and Redis variables> \
bash scripts/smoke_test.sh
```

## Stop and recovery

```bash
TIANTONG_ENV=test EXPECTED_COMMIT_SHA="$(git rev-parse HEAD)" TEST_RUNTIME_ID=r167-uat bash scripts/stop_test.sh
```

The stop command verifies PID, checkout, commit, working directory, and exact `uvicorn backend.main:app` command before sending `SIGTERM`. It never uses `killall`, never stops Docker/system services, and does not delete the database. On failure, inspect the private runtime logs, correct the test-only configuration, and rerun the same guarded command. Never fall back to production `deploy.sh`.
