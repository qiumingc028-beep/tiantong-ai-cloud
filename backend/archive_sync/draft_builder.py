from __future__ import annotations

from .safety import redact_sensitive_text, safety_payload
from .schemas import DraftResponse, SprintRecord, SprintSummaryPayload
from .sprint_record import build_sprint_record


def build_archive_drafts(payload: SprintSummaryPayload) -> DraftResponse:
    record = build_sprint_record(payload)
    codex_summary = redact_sensitive_text(payload.codex_output)
    drafts = {
        "changelog": build_changelog_draft(record, codex_summary),
        "project_status": build_project_status_draft(record),
        "decision_log": build_decision_log_draft(record),
    }
    return DraftResponse(
        sprint_record=record,
        drafts=drafts,
        saved=False,
        requires_boss_confirmation=True,
        safety=safety_payload(),
    )


def build_changelog_draft(record: SprintRecord, codex_summary: str = "") -> str:
    return "\n".join(
        [
            f"## {record.sprint_version}",
            "",
            f"Sprint: {record.sprint_name}",
            f"负责人: {', '.join(record.owner) or '待补充'}",
            f"Commit ID: `{record.commit_id or '待补充'}`",
            f"测试结果: {record.test_result or '待补充'}",
            f"部署状态: {record.deployment_status or '待补充'}",
            "",
            "修改文件:",
            *[f"- `{item}`" for item in record.changed_files],
            "",
            "风险记录:",
            *[f"- {item}" for item in (record.risk_notes or ['无阻断风险'])],
            "",
            "Codex摘要:",
            codex_summary or "待补充",
            "",
            "安全边界: 本草稿未自动写入 docs，等待老板确认后保存。",
        ]
    )


def build_project_status_draft(record: SprintRecord | None = None) -> str:
    if record is None:
        record = SprintRecord(
            id="draft",
            sprint_name="待补充",
            sprint_version="待补充",
            owner=[],
        )
    return "\n".join(
        [
            "## PROJECT_STATUS 更新建议",
            "",
            f"当前版本: {record.sprint_version}",
            f"当前Sprint: {record.sprint_name}",
            "已完成:",
            f"- {record.sprint_version}: {record.sprint_name}",
            "进行中:",
            "- 等待老板确认归档草稿",
            "下一步:",
            "- 天检验收归档内容",
            "- 天监检查敏感信息",
            "风险:",
            *[f"- {item}" for item in (record.risk_notes or ['无阻断风险'])],
            "禁止事项:",
            "- 禁止自动修改项目文档",
            "- 禁止自动提交 Git",
            "- 禁止自动部署",
        ]
    )


def build_decision_log_draft(record: SprintRecord | None = None) -> str:
    if record is None:
        record = SprintRecord(id="draft", sprint_name="待补充", sprint_version="待补充", owner=[])
    return "\n".join(
        [
            f"## 决策草稿：{record.sprint_version}",
            "",
            f"主题: {record.sprint_name}",
            "决策: 本次 Sprint 完成后先生成项目档案草稿，必须老板确认后再保存。",
            "原因: 避免自动改写项目长期记忆造成错误沉淀。",
            "影响范围:",
            "- CHANGELOG 草稿",
            "- PROJECT_STATUS 更新建议",
            "- DECISION_LOG 记录建议",
            "安全边界:",
            "- 不自动写 docs",
            "- 不自动提交 Git",
            "- 不自动部署",
        ]
    )
