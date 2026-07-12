# V2 天藏知识资产中心架构说明

日期：2026-07-12

## 1. 目标

天藏知识资产中心用于沉淀经过审核的企业知识资产，统一管理研究报告、SOP、运营经验、客服知识、技术文档与业务规则，并提供版本化、引用追踪、分段索引与基础检索能力。

本 Sprint 只建立基础能力，不启用真实向量检索，不接入外部 Embedding API，不向生产 Qdrant 写入数据。

## 2. 分层架构

知识写入与使用路径如下：

天采 / 其他 AI 员工  
→ 研究报告或知识候选  
→ 天藏接收  
→ 来源与证据校验  
→ 安全与敏感信息检查  
→ 审核  
→ 发布正式知识资产  
→ 版本与 Chunk 生成  
→ 基础全文检索  
→ 被其他 AI 员工引用  
→ 引用记录与审计

关键边界：

- 未审核内容不能直接成为正式知识。
- 已发布版本不能原地覆盖。
- 普通员工只能读取有权限且已发布的知识。
- 真实向量索引默认关闭。

## 3. 后端模块

新增模块目录：

- `backend/knowledge_center/`

主要职责：

- `models.py`：知识资产、版本、标签、Chunk、审核、引用、来源关联模型。
- `schemas.py`：API 请求与响应结构。
- `workflow.py`：提交、审核、批准、发布、归档、回退、证据关联。
- `service.py`：业务门面与查询服务。
- `versioning.py`：版本号生成与版本流转。
- `chunking.py`：确定性分段。
- `search.py`：本地关键词检索与预留向量接口。
- `citation.py`：引用记录与查询文本哈希。
- `sanitizer.py`：敏感信息脱敏与 HTML 噪声清理。
- `permissions.py`：权限与 Feature Flag 判断。
- `exceptions.py`：领域异常。
- `constants.py`：类型、状态、标签与默认建议。

## 4. 数据模型

核心模型包括：

- `KnowledgeAsset`
- `KnowledgeVersion`
- `KnowledgeSourceLink`
- `KnowledgeReview`
- `KnowledgeTag`
- `KnowledgeTagRelation`
- `KnowledgeChunk`
- `KnowledgeCitation`

设计原则：

- 资产与版本分离。
- 正式内容通过版本推进。
- 来源、证据、审核、引用均可追溯。
- 历史版本永久保留。

## 5. 检索设计

本 Sprint 实现：

- 标题检索
- 摘要检索
- 正文检索
- 分类筛选
- 标签筛选
- 类型筛选
- 状态筛选
- 部门筛选
- 可信度筛选

预留：

- `LocalKeywordKnowledgeIndex`
- `QdrantKnowledgeIndex`
- `EmbeddingProvider`

默认行为：

- `KNOWLEDGE_LOCAL_SEARCH_ENABLED=false`
- `KNOWLEDGE_VECTOR_SEARCH_ENABLED=false`

## 6. 审核与权限

权限角色分工：

- 天藏：知识接收、审核、发布、归档、版本管理。
- 天采：提交知识候选、补充来源与证据，不能直接发布。
- 其他员工：仅能访问已发布且授权可见的知识。

高风险知识必须满足额外审批约束。

## 7. 安全边界

知识中心默认启用的安全策略包括：

- 敏感信息脱敏。
- Prompt Injection 视为不可信外部内容。
- 审计记录保留来源、版本、引用和审核动作。
- 不保存密码、Token、Cookie、Secret、私钥明文。
- 真实向量检索默认关闭。
- 生产环境默认关闭知识中心 Feature Flag。

