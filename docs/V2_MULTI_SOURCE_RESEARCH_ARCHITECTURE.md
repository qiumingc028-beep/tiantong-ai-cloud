# V2 多来源公开数据研究架构

## 1. 目标

本 Sprint 建立“多来源公开信息研究工作流”，面向已授权 AI 员工“天采”，在受控、只读、可审计的前提下完成：

- 多查询拆解
- 统一搜索
- 浏览器只读采集
- 内容去重
- 交叉验证
- 证据链保存
- 中文研究报告生成
- Task Center 回写

## 2. 分层架构

研究流程遵循固定链路：

老板 / Orchestrator
→ Task Center 研究任务
→ AI 员工（默认天采）
→ Agent Runtime
→ 能力注册表
→ 权限与风险判断
→ 研究规划器
→ 统一搜索适配器
→ 候选来源过滤
→ 浏览器只读执行器
→ 内容提取与清洗
→ 去重与交叉验证
→ 证据链生成
→ 中文研究报告
→ Task Center 回写
→ 审计日志

禁止绕过 Agent Runtime 直接访问搜索、浏览器或外部数据。

## 3. 模块边界

后端新增研究运行时模块：

- `backend/research_runtime/planner.py`
- `backend/research_runtime/query_builder.py`
- `backend/research_runtime/search_registry.py`
- `backend/research_runtime/search_executor.py`
- `backend/research_runtime/source_ranker.py`
- `backend/research_runtime/deduplicator.py`
- `backend/research_runtime/verifier.py`
- `backend/research_runtime/evidence.py`
- `backend/research_runtime/report_builder.py`
- `backend/research_runtime/models.py`
- `backend/research_runtime/service.py`
- `backend/research_runtime/prompt_guard.py`

新增能力标识：

- `research.public.multi_source`

## 4. 核心能力

### 4.1 研究规划器

负责根据研究主题、目标和限制条件生成：

- 研究问题列表
- 查询词列表
- 推荐来源类型
- 最低来源数量
- 交叉验证规则
- 停止条件
- 最大执行时间

规划结果必须为中文，并限制查询数量和来源数量，禁止无限递归拆分。

### 4.2 统一搜索适配器

定义统一搜索接口：

- `validate_query()`
- `search()`
- `cancel()`
- `health_check()`
- `get_metadata()`

本 Sprint 提供：

- `MockSearchProvider`
- 受控公开搜索适配器占位实现

真实搜索默认关闭。

### 4.3 候选来源过滤

在进入浏览器只读执行器前再次校验：

- URL 协议
- 域名白名单
- 域名黑名单
- 私有 IP
- 内网地址
- 云 Metadata
- 重定向风险
- 登录页、付费墙、下载页、可执行文件链接

复用浏览器只读安全策略，不重复实现弱化版本。

### 4.4 内容提取与去重

浏览器只读执行器负责：

- GET/HEAD 读取
- 页面标题提取
- HTML / JSON / 纯文本提取
- 来源 URL 记录
- 内容 Hash 生成

研究运行时负责：

- URL 规范化
- 重复来源合并
- 主来源与重复来源记录
- 不同来源观点保留

### 4.5 交叉验证

对关键结论执行交叉验证，输出：

- 支持来源
- 冲突来源
- 证据数量
- 验证状态
- 置信等级

### 4.6 证据链

每次研究都会保存：

- execution_id
- task_id
- source_id
- claim_id
- 原始 URL
- 脱敏 URL
- 页面标题
- 来源类型
- 来源可信度
- 引用摘要
- 内容 Hash
- 采集时间
- 发布时间
- 支持或反对关系
- 验证状态
- Trace ID

## 5. 数据模型

新增表：

- `research_executions`
- `research_queries`
- `research_sources`
- `research_claims`
- `research_evidence`

新增迁移：

- `0029_v2_public_research_workflow`

## 6. API

新增 API：

- `GET /api/v2/research/health`
- `GET /api/v2/research/executions`
- `GET /api/v2/research/executions/{execution_id}`
- `GET /api/v2/research/executions/{execution_id}/sources`
- `GET /api/v2/research/executions/{execution_id}/claims`
- `GET /api/v2/research/executions/{execution_id}/evidence`

任务创建与执行仍通过 Agent Runtime 和 Task Center 既有链路完成。

## 7. 权限与审批

默认规则：

- 仅允许已授权员工“天采”
- 默认关闭公开研究能力
- 默认关闭真实搜索
- 低风险只读能力不需要老板审批
- 高风险与真实执行器能力不在本 Sprint 启用

## 8. Feature Flag

新增或延续配置：

- `PUBLIC_RESEARCH_ENABLED=false`
- `PUBLIC_SEARCH_ENABLED=false`
- `BROWSER_READONLY_ENABLED=false`
- `BROWSER_CONTROL_ENABLED=false`

生产环境默认全部关闭。

## 9. 安全边界

网页内容被视为不可信外部数据，禁止：

- 登录
- 表单提交
- Cookie / Session 保存
- Shell 执行
- 文件读取
- 真实执行器绕过

## 10. 后续扩展边界

后续可在不破坏当前边界的前提下接入：

- 更强的搜索提供者
- 更复杂的浏览器自动化
- 更强的证据评分模型

但任何真实外部执行能力都必须继续经过 Agent Runtime、权限和审计链路。
