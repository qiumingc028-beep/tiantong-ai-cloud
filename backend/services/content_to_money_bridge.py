from __future__ import annotations


def bind_content_to_product(content: dict, ecommerce_signal: dict | None = None) -> dict:
    signal = ecommerce_signal or {}
    sku = signal.get("sku") or signal.get("selected_product") or "SKU-AUTO-PROFIT"
    product_name = signal.get("product_name") or signal.get("name") or "AI增长商品"
    return {
        "bridge": "content_to_money",
        "sku": sku,
        "product_name": product_name,
        "content_title": extract_title(content),
        "landing_strategy": "内容种草 -> 商品承接 -> 数据回流",
        "conversion_goal": "traffic_to_order",
        "auto_bind": True,
        "external_publish": False,
    }


def extract_title(content: dict) -> str:
    script = content.get("script") if isinstance(content, dict) else {}
    note = content.get("note") if isinstance(content, dict) else {}
    if isinstance(script, dict) and script.get("title"):
        return script["title"]
    if isinstance(note, dict) and note.get("title"):
        return note["title"]
    return "AI商业增长内容"
