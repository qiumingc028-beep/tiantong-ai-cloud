# V2 知识版本策略

日期：2026-07-12

## 1. 版本原则

- 每次正式修改都生成新版本。
- 已发布版本不能原地覆盖。
- 历史版本必须可追溯。
- 版本差异必须可审阅。

## 2. 版本字段

关键字段：

- version_id
- knowledge_id
- version_number
- title
- summary
- content
- content_format
- change_summary
- change_reason
- source_type
- source_execution_id
- source_report_id
- content_hash
- created_by
- reviewed_by
- approved_by
- created_at
- approved_at

## 3. Chunk 策略

每个版本可生成多个 Chunk：

- 保留标题层级
- 尽量不切断句子
- 表格和列表尽量整体保留
- 每段有上限
- 每段有稳定 Hash
- 重复生成时稳定

## 4. 版本回退

回退采用“创建新版本”的方式实现：

- 不能覆盖历史版本
- 不能物理删除已发布版本
- 不能跳过审核直接恢复为正式内容

## 5. 版本检索

版本检索优先使用：

- 当前版本
- 历史版本
- 版本 Hash
- 变更摘要

