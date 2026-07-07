from __future__ import annotations


def generate_video_script(payload: dict, trend: dict | None = None) -> dict:
    topic = payload.get("topic") or payload.get("product_name") or (trend or {}).get("keyword") or "AI商业增长"
    product = payload.get("product_name") or payload.get("sku") or "主推商品"
    return {
        "format": "short_video_script",
        "title": f"{topic}：3个值得关注的增长信号",
        "hook": f"如果你正在关注{product}，先看这三个数据点。",
        "scenes": [
            {"shot": 1, "content": "提出痛点和场景。"},
            {"shot": 2, "content": "展示数据/趋势信号。"},
            {"shot": 3, "content": "给出商品或策略建议。"},
            {"shot": 4, "content": "提示人工确认后再执行。"},
        ],
        "cta": "进入人工复核后发布。",
        "auto_publish": False,
    }


def generate_xiaohongshu_note(payload: dict, trend: dict | None = None) -> dict:
    topic = payload.get("topic") or payload.get("product_name") or (trend or {}).get("keyword") or "AI商业增长"
    return {
        "format": "xiaohongshu_note",
        "title": f"{topic}｜真实数据下的选择建议",
        "paragraphs": [
            "先说结论：这个方向值得进入小规模测试。",
            "核心原因：数据表现、用户场景和内容转化存在联动空间。",
            "执行建议：先人工复核，再安排内容测试和商品承接。",
        ],
        "tags": ["AI经营", "增长策略", "选品观察"],
        "auto_publish": False,
    }
