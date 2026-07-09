# Sprint30 Roadmap: v0.1.0-MVP to v1.0

## 1. Baseline

- Current stable version: `v0.1.0-mvp`
- Current release commit: `c8e326a`
- Current mode: production MVP stabilized
- Sprint30 mode: planning only

Sprint30 starts from the existing v0.1.0-MVP architecture. The upgrade path must preserve the current Task Center, AI employee system, Orchestrator, Execution Engine, Tool Permission, Deploy Center, and production deployment baseline.

## 2. Current Real Architecture

### 2.1 Runtime Architecture

```text
Browser
  |
  | HTTPS
  v
Nginx
  |-- static HTML frontend from /frontend
  |-- /api/* reverse proxy
  v
FastAPI backend
  |-- auth/session/JWT
  |-- business routers
  |-- AI employee modules
  |-- Task Center
  |-- Orchestrator
  |-- Brain Execution
  |-- Tool Center / Tool Router
  |-- Knowledge / Review / Archive centers
  |
  | SQLAlchemy
  v
PostgreSQL

FastAPI backend / worker
  |
  | Redis sessions, heartbeat, queues, runtime state
  v
Redis

Worker
  |-- backend.worker
  |-- queue consumption
  |-- execution heartbeat
  |-- AI employee execution MVP
```

### 2.2 Backend Modules

```text
backend/
  main.py                         FastAPI app, router registration, static page serving, health/ready
  auth.py                         session cookie, JWT, role permission helpers
  config.py                       env-based config
  database.py                     SQLAlchemy engine/session and Redis client
  models.py                       core users, stores, metrics, AI employees, Task Center models
  routers/                        primary HTTP API layer
  core/orchestrator.py            unified event entry
  workflow/router.py              source-to-target workflow routing
  brain_execution/                Brain Execution Center and runtime state machine
  brain_orchestrator/             Brain Center to Orchestrator dry-run task graph
  brain_tool_router/              Brain to Tool Router planning
  tool_center/                    tool registry/gateway/defaults
  tool_router/                    tool route matching and dry-run routing
  ai_capabilities/                AI employee capability registry
  employee_execution/             TianShang execution contract/planner/executor
  workers/                        AI employee worker implementation
  archive_sync/                   project archive draft system
  knowledge_center/               long-term knowledge center
  learning_center/                execution learning center
  security/tian_shen/             approval/firewall policy layer
  security/tian_brain/            audit analysis and risk prediction
```

### 2.3 Frontend Pages

```text
frontend/
  index.html                      boss dashboard
  task-center.html                AI Task Center
  orchestrator.html               AI任务编排中心
  auto-dispatch-center.html       AI自动派单中心
  ai-employees.html               AI employee roster
  employee-workspace.html         AI employee workspace
  employee-capabilities.html      capability profile
  employee-evolution-center.html  employee growth center
  review-learning-center.html     review learning center
  knowledge-center.html           knowledge center
  tiancang.html                   TianCang knowledge assets
  tool-center.html                tool center
  tool-router.html                tool router
  brain-center.html               Brain Center
  brain-orchestrator.html         Brain Orchestrator
  ai-execution.html               Brain Execution Center
  deploy-center.html              Deploy Center
  release-center.html             Release Center
  jd-dashboard.html               JD dashboard
  jd-integrations.html            JD integration center
  dashboard/                      employee command dashboard pages
```

### 2.4 Database and Migration Baseline

Alembic migration chain currently reaches:

```text
0026_sprint26_ai_employee_execution_mvp
```

Major database domains already present:

- Auth and roles: `users`, `roles`, `permissions`, `role_permissions`
- Stores and metrics: stores, brands, store groups, daily metrics, JD integration tables
- Task Center: task records, task logs, reviews, audits
- AI employees: employee roster, capability and runtime-related records
- Deploy Center: deployment and health check records
- Orchestrator: analysis records and task links
- Auto Dispatch: employee capability, routing rules, dispatch records
- Execution Engine: execution logs, worker/runtime records
- Review/Learning/Evolution: task reviews, employee scores, growth and skill suggestions
- Release Center: release versions
- Tool Center/Tool Router: tool registry, bindings, logs, routes
- Brain Center: task graph, execution logs, runtime runs/events
- Sprint26 employee execution MVP: employee execution contracts and TianShang execution data

### 2.5 Docker and Production Runtime

```text
docker-compose.yml
  local/default runtime
  postgres, redis, backend, worker, nginx

docker-compose.prod.yml
  production runtime
  postgres with env-based admin credentials
  redis with requirepass
  backend from Dockerfile.backend
  worker from Dockerfile.worker
  nginx from Dockerfile.frontend and nginx/production.conf
  TLS cert/key mounted from env-configured paths

nginx/production.conf
  server_name cloud.tiantongai.com
  HTTPS/TLS
  gzip
  rate limiting
  security headers
  /api proxy to backend
  static frontend serving
```

### 2.6 Current System Boundaries

Current v0.1.0-MVP strengths:

- Modular backend with clear business routers.
- Static frontend pages are simple and operationally reliable.
- Auth, permissions, sessions, health checks, and production HTTPS are working.
- AI employee system, Task Center, Orchestrator, Brain Execution, Tool Router, and archive sync exist.
- Production deployment runbooks and acceptance reports are archived.

Current v0.1.0-MVP constraints:

- Several advanced AI/business modules are simulation or dry-run first.
- Frontend is page-based static HTML, not a shared component system.
- External data integrations are partial and need stronger production boundaries.
- Knowledge/RAG foundation exists, but vector search/file intelligence is not yet a full pipeline.
- AI employee execution is MVP-level and must remain approval-gated.

## 3. v1.0 Product Direction

v1.0 should turn the MVP from a production-accessible AI management platform into a daily operating system for the boss:

```text
Global market awareness
  -> business opportunity discovery
  -> AI task planning
  -> employee assignment
  -> approval and audit
  -> execution / dry-run / human-confirmed action
  -> result review
  -> knowledge asset accumulation
  -> next decision
```

The recommended principle for v1.0:

- First aggregate and analyze.
- Then recommend and plan.
- Then execute only safe internal actions.
- High-risk or external actions remain boss-confirmed and security-audited.

## 4. Sprint30 Priority Plan

### P0: Stabilize Daily Boss Operations

Goal:

- Make the boss dashboard the daily command entry.
- Reduce scattered navigation and make operational status obvious.

Deliverables:

- Dashboard unified data API v2.
- Today operations panel v2.
- Pending confirmations panel v2.
- AI employee activity summary.
- Risk and exception summary.

Affected areas:

- `backend/routers/ceo_dashboard.py`
- `frontend/index.html`
- Tests: `tests/test_ceo_dashboard.py`, `tests/test_ceo_daily_operations.py`, `tests/test_ceo_daily_summary.py`

### P1: Build v1.0 Data Awareness Centers

Goal:

- Introduce read-only intelligence centers for global and business context.

Recommended centers:

- Global Hotspot Center
- AI News Center
- Financial Market Center
- A-share Market Center
- AI Business Data Center

First phase mode:

- Read-only.
- No auto trading.
- No paid API call by default.
- External API adapters must be disabled until approved.
- Mock/static/manual-import data allowed.

### P1: Upgrade AI Employee System

Goal:

- Make AI employees easier to understand, assign, review, and improve.

Focus:

- Skill taxonomy.
- Employee task matching.
- Execution records.
- Result archive.
- Knowledge learning loop.

Expected user value:

- The boss can see what each AI employee can do, what it did today, what failed, and what improved.

### P1: TianCang Knowledge Asset Center

Goal:

- Turn scattered project/task outputs into reusable enterprise knowledge.

Knowledge domains:

- SOP library.
- Prompt library.
- Bug case library.
- Business case library.
- Enterprise knowledge base.
- RAG-ready document chunks and metadata.

First phase should remain:

- Knowledge ingestion and retrieval.
- No automatic production prompt replacement.
- No automatic rule changes.

### P2: TianCai Ecommerce Data Center

Goal:

- Build a reliable ecommerce data foundation for JD 60 stores.

Data domains:

- JD 60-store operations data.
- Shangzhi data.
- Jingzhuntong data.
- Manual upload/import data.
- Sales, profit, traffic, ads, conversion, refund, inventory indicators.

First phase:

- Normalize schemas.
- Import validation.
- Daily dashboard.
- AI-readable summary API.

### P2: TianTong AI Control Center

Goal:

- Consolidate Brain Center, Orchestrator, Task Center, approval, and audit flows.

Target flow:

```text
Boss goal
  -> Brain analysis
  -> Task graph
  -> AI employee recommendation
  -> Tool Router dry-run
  -> risk classification
  -> boss approval
  -> security audit
  -> execution queue
  -> result log
  -> review and knowledge archive
```

## 5. Roadmap from v0.1.0-MVP to v1.0

### Sprint30: v1.0 Blueprint and Readiness Layer

Purpose:

- Finalize product architecture and prepare schema/API contracts for v1.0.

Output:

- Current architecture map.
- v1.0 data model plan.
- API contracts for new intelligence centers.
- Frontend navigation plan.
- Security boundary matrix.

### Sprint31: Boss Dashboard v2

Purpose:

- Make dashboard the daily operating cockpit.

Backend:

- `GET /api/ceo-dashboard/v2/overview`
- `GET /api/ceo-dashboard/v2/alerts`
- `GET /api/ceo-dashboard/v2/pending-actions`
- `GET /api/ceo-dashboard/v2/employee-summary`
- `GET /api/ceo-dashboard/v2/task-summary`

Frontend:

- Upgrade `frontend/index.html`.
- Add clearer sections for daily operations, alerts, employees, tasks, and confirmations.

Database:

- Prefer no new table in first phase.
- Read from existing Task Center, AI employees, approval center, execution logs, deploy health.

### Sprint32: Market Awareness Centers

Purpose:

- Add read-only global/news/financial/A-share centers.

Backend:

- New module: `backend/market_intelligence/`
- New router: `backend/routers/market_intelligence.py`

APIs:

- `GET /api/market-intelligence/overview`
- `GET /api/market-intelligence/global-hotspots`
- `GET /api/market-intelligence/ai-news`
- `GET /api/market-intelligence/financial-markets`
- `GET /api/market-intelligence/a-share`
- `GET /api/market-intelligence/business-signals`

Frontend:

- `frontend/market-intelligence.html`
- Dashboard entry cards for global hotspots, AI news, financial markets, and A-share.

Database:

- `market_signals`
- `market_news_items`
- `market_watchlists`
- `market_signal_snapshots`

Safety:

- No automatic trading.
- No paid external API until Tool Permission and boss approval are connected.

### Sprint33: AI Employee Skill System v2

Purpose:

- Unify employee skills, task matching, execution results, and learning.

Backend:

- Extend existing `ai_capabilities`, `employee_capability`, `employee_execution`, and `employee_evolution` domains.

APIs:

- `GET /api/employee-skills/catalog`
- `GET /api/employee-skills/employees/{code}`
- `POST /api/employee-skills/recommend`
- `GET /api/employee-skills/task-matches`
- `GET /api/employee-skills/performance`

Database:

- `skill_catalog`
- `employee_skill_bindings`
- `skill_evaluation_records`
- `task_skill_requirements`

Safety:

- Skill changes are suggestions by default.
- Any production skill activation requires boss approval and TianShen audit.

### Sprint34: TianCang Knowledge Asset Center v2

Purpose:

- Build enterprise knowledge base foundation and RAG-ready structure.

Backend:

- Extend `backend/knowledge_center/` and `backend/routers/knowledge_center.py`.

APIs:

- `GET /api/knowledge/assets`
- `POST /api/knowledge/assets`
- `GET /api/knowledge/sops`
- `GET /api/knowledge/prompts`
- `GET /api/knowledge/bug-cases`
- `POST /api/knowledge/search`
- `POST /api/knowledge/rag/dry-run`

Database:

- `knowledge_assets`
- `knowledge_collections`
- `knowledge_chunks`
- `prompt_library`
- `sop_library`
- `bug_case_library`
- `knowledge_tags`

Infrastructure:

- Prepare Qdrant and MinIO integration plan.
- Do not require production deployment in the first v2 knowledge sprint unless approved.

Safety:

- No automatic prompt replacement.
- No automatic SOP enforcement.
- No unapproved external model calls.

### Sprint35: TianCai Ecommerce Data Center

Purpose:

- Create JD 60-store data hub and AI-readable operations layer.

Backend:

- Extend `jd_collection`, `jd_integrations`, `metrics`, and ecommerce service modules.

APIs:

- `GET /api/ecommerce-data/overview`
- `GET /api/ecommerce-data/jd60/stores`
- `GET /api/ecommerce-data/sales`
- `GET /api/ecommerce-data/ads`
- `GET /api/ecommerce-data/conversion`
- `POST /api/ecommerce-data/import`
- `GET /api/ecommerce-data/ai-summary`

Database:

- `ecommerce_daily_metrics`
- `jd_store_snapshots`
- `shangzhi_snapshots`
- `jzt_ad_snapshots`
- `ecommerce_import_batches`
- `ecommerce_data_quality_issues`

Safety:

- Data import validates and stores.
- No automatic account login.
- No automatic ad spending.
- No automatic price changes.

### Sprint36: TianTong AI Control Center v2

Purpose:

- Combine Brain, Orchestrator, Task Center, Tool Router, approval, and execution into a more coherent command flow.

Backend:

- Add a unified facade instead of replacing existing modules.
- New router: `backend/routers/control_center_v2.py`

APIs:

- `POST /api/control-center/v2/analyze-goal`
- `POST /api/control-center/v2/create-task-graph`
- `POST /api/control-center/v2/request-approval`
- `POST /api/control-center/v2/start-approved-run`
- `GET /api/control-center/v2/runs/{id}`
- `GET /api/control-center/v2/audit-trail`

Frontend:

- `frontend/control-center-v2.html`
- Keep existing `control.html`, `brain-center.html`, `brain-orchestrator.html`, and `task-center.html`.

Safety:

- High risk remains blocked without boss confirmation and TianShen audit.
- Tool calls remain routed through Tool Router.
- External actions stay dry-run until explicitly approved.

## 6. Database Change Plan

Recommended migration sequence:

```text
0027_sprint31_dashboard_v2_optional_views
0028_sprint32_market_intelligence
0029_sprint33_employee_skill_system
0030_sprint34_knowledge_assets_v2
0031_sprint35_ecommerce_data_center
0032_sprint36_control_center_v2
```

Migration principles:

- Additive only.
- No destructive migrations.
- Do not rename existing tables in v1.0 path.
- Prefer new tables and compatibility views.
- Existing APIs must continue to pass tests.

## 7. API Planning Summary

### Dashboard v2

- `GET /api/ceo-dashboard/v2/overview`
- `GET /api/ceo-dashboard/v2/alerts`
- `GET /api/ceo-dashboard/v2/pending-actions`
- `GET /api/ceo-dashboard/v2/employee-summary`
- `GET /api/ceo-dashboard/v2/task-summary`

### Market intelligence

- `GET /api/market-intelligence/overview`
- `GET /api/market-intelligence/global-hotspots`
- `GET /api/market-intelligence/ai-news`
- `GET /api/market-intelligence/financial-markets`
- `GET /api/market-intelligence/a-share`
- `GET /api/market-intelligence/business-signals`

### Employee skills

- `GET /api/employee-skills/catalog`
- `GET /api/employee-skills/employees/{code}`
- `POST /api/employee-skills/recommend`
- `GET /api/employee-skills/task-matches`
- `GET /api/employee-skills/performance`

### Knowledge assets

- `GET /api/knowledge/assets`
- `POST /api/knowledge/assets`
- `GET /api/knowledge/sops`
- `GET /api/knowledge/prompts`
- `GET /api/knowledge/bug-cases`
- `POST /api/knowledge/search`
- `POST /api/knowledge/rag/dry-run`

### Ecommerce data

- `GET /api/ecommerce-data/overview`
- `GET /api/ecommerce-data/jd60/stores`
- `GET /api/ecommerce-data/sales`
- `GET /api/ecommerce-data/ads`
- `GET /api/ecommerce-data/conversion`
- `POST /api/ecommerce-data/import`
- `GET /api/ecommerce-data/ai-summary`

### Control Center v2

- `POST /api/control-center/v2/analyze-goal`
- `POST /api/control-center/v2/create-task-graph`
- `POST /api/control-center/v2/request-approval`
- `POST /api/control-center/v2/start-approved-run`
- `GET /api/control-center/v2/runs/{id}`
- `GET /api/control-center/v2/audit-trail`

## 8. Frontend Page Plan

New or upgraded pages:

- Upgrade: `frontend/index.html`
- New: `frontend/market-intelligence.html`
- New: `frontend/employee-skills.html`
- Upgrade: `frontend/knowledge-center.html`
- New: `frontend/ecommerce-data-center.html`
- New: `frontend/control-center-v2.html`

Navigation principles:

- Keep existing pages available.
- Add v2 pages gradually.
- Avoid a full UI rewrite before v1.0.
- Keep pages read-only unless workflow explicitly requires boss confirmation.

## 9. Security and Approval Model

### Always allowed

- Read-only dashboards.
- Internal summaries.
- Dry-run planning.
- Manual imports with validation.
- Knowledge search.

### Requires boss confirmation

- Starting execution from an approved plan.
- Skill activation.
- Prompt production update.
- External API connector enablement.
- Data export.

### Requires boss confirmation plus TianShen audit

- Price changes.
- Ad budget changes.
- External account login.
- Public content publishing.
- Tool calls that spend money.
- Production rule changes.
- Permission changes.
- Deployment actions.

### Blocked for v1.0 unless separately approved

- Shell execution from AI workflow.
- Automatic code modification and push.
- Automatic production deployment.
- Automatic payment.
- Automatic unknown plugin installation.
- Automatic external browser account operation.

## 10. Test Strategy

Each sprint from Sprint31 onward should include:

- Router permission tests:
  - 401 unauthenticated.
  - 403 insufficient role.
  - 200 owner/admin/boss.
- Data isolation tests for AI employee roles.
- Sensitive field filtering tests.
- Regression tests:
  - Task Center.
  - Orchestrator.
  - Execution Engine.
  - Tool Permission.
  - Deploy Center.
- Frontend smoke tests:
  - page exists.
  - API paths match.
  - no dangerous buttons for read-only pages.
- `git diff --check`.

## 11. Key Risks

### Risk 1: Too many modules without a single product surface

Mitigation:

- Make Dashboard v2 and Control Center v2 the primary navigation anchors.
- Keep existing pages as specialized centers.

### Risk 2: External data integration can create security and cost exposure

Mitigation:

- Start with manual upload/static/mock/read-only adapters.
- Require Tool Permission and approval before real connectors.

### Risk 3: Knowledge/RAG can leak sensitive information

Mitigation:

- Add document classification, redaction, and access control before vector search production.
- Never index secrets, passwords, tokens, cookies, or private keys.

### Risk 4: AI execution may bypass approval paths

Mitigation:

- Keep all executable paths behind approval records and TianShen checks.
- Add tests proving high-risk paths are blocked.

### Risk 5: Database complexity grows quickly

Mitigation:

- Additive migrations only.
- Maintain compatibility with v0.1.0-MVP tables.
- Introduce clear ownership per data domain.

## 12. Sprint30 Acceptance Criteria

Sprint30 is complete when:

- Current v0.1.0-MVP architecture is documented.
- v1.0 upgrade route is approved.
- Sprint31-Sprint36 sequence is clear.
- Database/API/frontend planning is reviewed.
- Security boundaries are explicit.
- No business code has been modified during planning.

## 13. Recommendation

Recommended next step:

Start Sprint31 with Boss Dashboard v2.

Reason:

- It improves daily usability immediately.
- It reuses existing data.
- It creates the control surface needed before adding more data centers and AI execution capabilities.
