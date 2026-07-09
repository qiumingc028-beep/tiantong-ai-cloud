# Sprint29.24 MVP Release Report

## A. Release Summary

- Release version: `v0.1.0-mvp`
- Release scope: Sprint29.19-Sprint29.23 production deployment, acceptance, stability follow-up, and MVP baseline freeze
- Release date: 2026-07-09
- Production domain: `cloud.tiantongai.com`
- Production ECS: `120.24.79.232`
- Result: Ready for MVP stable baseline archive

This release is a version archive and stability freeze. No new business capability was added in Sprint29.24.

## B. Included Changes

### Production deployment and acceptance documents

Included Sprint29 reports:

- `docs/SPRINT29_17_PRE_PRODUCTION_CHECK.md`
- `docs/SPRINT29_17_5_SERVER_VERIFY.md`
- `docs/SPRINT29_18_PREPARE_REPORT.md`
- `docs/SPRINT29_18_1_PRODUCTION_CONFIG_REPORT.md`
- `docs/SPRINT29_18_2_SECURITY_CONFIG_REPORT.md`
- `docs/SPRINT29_18_3_TLS_BACKUP_REPORT.md`
- `docs/SPRINT29_18_4_TLS_CERT_REPORT.md`
- `docs/SPRINT29_18_5_DOMAIN_TLS_READY_REPORT.md`
- `docs/SPRINT29_18_6_DOMAIN_CERT_READY_REPORT.md`
- `docs/SPRINT29_18_7_DOMAIN_BIND_REPORT.md`
- `docs/SPRINT29_19_PRODUCTION_CONFIG_PLAN.md`
- `docs/SPRINT29_19_DEPLOY_CHECK_REPORT.md`
- `docs/SPRINT29_19_HTTPS_DEPLOY_REPORT.md`
- `docs/SPRINT29_20_SAAS_ACCEPTANCE_REPORT.md`
- `docs/SPRINT29_21_INTERNAL_TEST_REPORT.md`
- `docs/SPRINT29_22_BOSS_ACCEPTANCE_REPORT.md`
- `docs/SPRINT29_23_STABILITY_REPORT.md`
- `docs/SPRINT29_24_MVP_RELEASE_REPORT.md`

### Configuration and UI stability fixes

- `nginx/production.conf`
  - Production `server_name` set to `cloud.tiantongai.com`.
- `frontend/orchestrator.html`
  - Page naming unified as `AI任务编排中心`.
  - No Task Center, Orchestrator, Execution Engine, or permission logic was changed.

## C. Verification Summary

Sprint29.23 production checks confirmed:

- `/api/health`: 200
- `/api/ready`: 200
- `/orchestrator.html`: 200
- Boss login: 200
- `/api/me`: 200
- `/api/task-center/tasks`: 200
- `/api/ai-employees/runtime-status`: 200
- `/api/approval-center/pending`: 200
- Docker services:
  - `backend`: healthy
  - `nginx`: healthy
  - `postgres`: healthy
  - `redis`: healthy
  - `worker`: running

## D. Safety Boundary

Confirmed unchanged:

- No business feature added
- No database schema changed
- No data deletion
- No Task Center core flow changed
- No Orchestrator rule changed
- No Execution Engine logic changed
- No permission core changed
- No automatic deployment feature added

## E. Release Tag

Release tag:

- `v0.1.0-mvp`

The tag should point to the final commit that contains this report and the Sprint29.19-Sprint29.23 release archive.

## F. Residual Risks

Risk level: Low

Known residual item:

- Some local network environments may resolve `cloud.tiantongai.com` to `198.18.0.233`; public DNS resolvers return the production ECS IP `120.24.79.232`.

## G. Conclusion

Sprint29.24 completes the MVP stable version archive.

The current codebase can be treated as the `v0.1.0-mvp` baseline after the final commit and Git tag are pushed to GitHub.
