# V2 Sprint 4 实施报告

日期：2026-07-12

## 1. Sprint 目标

本 Sprint 建立了“天藏知识资产中心与企业长期记忆基础”，完成知识资产、版本、来源证据、审核、Chunk、基础检索、引用记录与前端页面的最小闭环。

## 2. 基线

- 基线分支：`origin/develop-v2`
- 基线 Commit：`7f847e903802494e89e55716cb0ae7ee4ad96f5e`
- 当前工作分支：`feature/v2-knowledge-asset-center`

## 3. 实现内容

后端：

- 新增 `backend/knowledge_center/` 模块
- 新增知识资产、版本、来源关联、审核、标签、Chunk、引用模型
- 新增知识中心 API
- 新增权限与 Feature Flag
- 新增本地全文检索
- 新增知识候选提交与版本恢复

前端：

- 新增 `知识资产中心` 页面
- 新增 `知识详情` 页面

迁移：

- `0030_v2_knowledge_asset_center`
- `0031_v2_research_topic_index`

## 4. 安全边界

已落实：

- 真实向量检索默认关闭
- 不接入外部 Embedding API
- 不向生产 Qdrant 写入
- 未审核内容不能直接发布
- 天采不能自批自发
- 敏感信息写入前脱敏
- Prompt Injection 不作为系统指令

## 5. 验证结果

专项测试：

- `tests/test_agent_runtime_pages.py`
- `tests/test_knowledge_asset_center.py`

全量验证：

- `python -m pytest -q`：`791 passed, 82 warnings`
- PostgreSQL `alembic upgrade head`：通过
- PostgreSQL `alembic check`：通过

## 6. 非阻塞警告

当前存在非阻塞警告：

- Alembic `path_separator` 相关 deprecation warning
- FastAPI `on_event` deprecation warning

这些警告不影响当前功能正确性，也不阻塞发布。

## 7. 结论

知识资产中心基础已完成，企业知识可进入“候选—审核—发布—版本化—引用”闭环，且生产默认保持关闭。

