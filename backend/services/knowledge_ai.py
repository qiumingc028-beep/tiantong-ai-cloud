from __future__ import annotations

from typing import Optional
import json
import urllib.request

from ..config import get_settings


def summarize_material(filename: str, text: str) -> dict:
    prompt = f"请总结资料《{filename}》，输出适合企业知识库的摘要、要点和风险提醒。\n\n{text[:6000]}"
    result = call_ai(prompt)
    if result:
        return {"summary": result}
    clean = compact_text(text)
    return {
        "summary": f"{filename} 的核心内容已整理：{clean[:180] or '资料内容较少，建议补充上下文。'}",
        "key_points": [
            "提炼资料中的关键流程、标准和经验结论。",
            "沉淀为可搜索、可发布、可培训的知识资产。",
            "后续可接入真实模型生成更细的 SOP、Prompt 和课程。",
        ],
        "mock": True,
    }


def classify_material(filename: str, text: str) -> dict:
    prompt = f"请将资料《{filename}》分类为：运营、客服、广告、数据、设计、系统、培训、Bug案例、Prompt、SOP，并给出标签。\n\n{text[:4000]}"
    result = call_ai(prompt)
    if result:
        return {"category": "AI分类", "tags": ["AI生成"], "reason": result}

    source = f"{filename} {text}".lower()
    rules = [
        ("Bug案例", ("bug", "error", "报错", "异常", "修复")),
        ("Prompt", ("prompt", "提示词", "指令")),
        ("SOP", ("sop", "流程", "步骤", "规范")),
        ("广告", ("广告", "投放", "roi", "转化")),
        ("客服", ("客服", "售后", "退款", "工单")),
        ("课程", ("课程", "培训", "大纲", "lesson")),
    ]
    category = "知识库"
    for name, keywords in rules:
        if any(keyword in source for keyword in keywords):
            category = name
            break
    return {"category": category, "tags": [category, "自动分类"], "reason": "根据文件名和正文关键词完成模拟分类。", "mock": True}


def generate_assets(filename: str, text: str, summary: Optional[str], category: Optional[str]) -> dict:
    prompt = (
        f"基于资料《{filename}》生成企业知识库文章、SOP、Prompt、Bug案例和课程大纲。"
        "请用清晰标题和可执行内容输出。\n\n"
        f"分类：{category or '未分类'}\n摘要：{summary or ''}\n正文：{text[:6000]}"
    )
    result = call_ai(prompt)
    if result:
        article_content = result
    else:
        basis = summary or compact_text(text)[:260] or "该资料已进入天藏知识资产中心。"
        article_content = (
            f"## 背景\n{basis}\n\n"
            "## 可复用经验\n1. 明确资料适用场景。\n2. 将关键动作转成标准流程。\n3. 把可复制话术沉淀为 Prompt。\n\n"
            "## 执行建议\n先由业务负责人审核，再发布到后台知识库供团队搜索和培训使用。"
        )
    title = title_from_filename(filename)
    category = category or "知识库"
    return {
        "article": {
            "title": title,
            "summary": summary or f"{title} 的自动知识化整理结果。",
            "content": article_content,
            "category": category,
            "tags": ["天藏", category],
        },
        "sop": {
            "title": f"{title} SOP",
            "category": category,
            "steps": "1. 阅读原始资料并确认适用场景\n2. 提取关键动作和检查标准\n3. 按岗位执行并记录结果\n4. 每月复盘并更新知识库",
        },
        "prompt": {
            "title": f"{title} Prompt",
            "category": category,
            "prompt_text": f"你是天统AI云中台知识助理，请基于《{title}》生成可执行方案、检查清单和风险提醒。",
            "usage_notes": "适合用于资料复盘、员工培训、知识库文章二次生成。",
        },
        "bug_case": {
            "title": f"{title} Bug案例",
            "category": category,
            "symptom": "资料中涉及的问题、异常或执行偏差需要被记录。",
            "root_cause": "MVP 阶段由 AI 模拟归因，后续接入真实模型和人工审核。",
            "solution": "沉淀处理步骤，发布后供团队搜索复用。",
        },
        "course": {
            "title": f"{title} 课程大纲",
            "category": category,
            "outline": "第一课：背景和目标\n第二课：标准流程\n第三课：案例演练\n第四课：检查清单和复盘",
            "target_audience": "运营、客服、管理者和新员工",
        },
        "mock": result is None,
    }


def call_ai(prompt: str) -> Optional[str]:
    settings = get_settings()
    provider = (settings.AI_PROVIDER or "mock").lower()
    if provider == "deepseek" and settings.DEEPSEEK_API_KEY:
        return chat_completion(
            "https://api.deepseek.com/chat/completions",
            settings.DEEPSEEK_API_KEY,
            "deepseek-chat",
            prompt,
        )
    if provider == "openai" and settings.OPENAI_API_KEY:
        return chat_completion(
            "https://api.openai.com/v1/chat/completions",
            settings.OPENAI_API_KEY,
            "gpt-4o-mini",
            prompt,
        )
    return None


def chat_completion(url: str, api_key: str, model: str, prompt: str) -> Optional[str]:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是企业知识资产整理助手，回答要结构清晰、可执行。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def compact_text(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def title_from_filename(filename: str) -> str:
    base = filename.rsplit(".", 1)[0].strip()
    return base or "未命名知识文章"
