from __future__ import annotations

from typing import Any


DEFAULT_BUSINESS_SNAPSHOT = {
    "store": "京东60店",
    "sales_change_pct": -0.18,
    "conversion_change_pct": -0.22,
    "ad_roi_change_pct": -0.16,
    "product_issue_count": 3,
    "customer_issue_count": 5,
}


def detect_business_signals(snapshot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = snapshot if isinstance(snapshot, dict) else DEFAULT_BUSINESS_SNAPSHOT
    store = str(data.get("store") or "unknown_store")
    signals: list[dict[str, Any]] = []
    add_drop_signal(signals, data, store, "sales_change_pct", "sales_decline", "销量下降")
    add_drop_signal(signals, data, store, "conversion_change_pct", "conversion_decline", "转化下降")
    add_drop_signal(signals, data, store, "ad_roi_change_pct", "ad_anomaly", "广告异常")

    product_issue_count = safe_int(data.get("product_issue_count"))
    if product_issue_count > 0:
        signals.append(
            make_signal(
                store=store,
                signal_type="product_issue",
                title="商品问题",
                severity="medium" if product_issue_count < 5 else "high",
                value=product_issue_count,
                threshold=0,
                evidence=f"发现 {product_issue_count} 个商品问题",
            )
        )

    customer_issue_count = safe_int(data.get("customer_issue_count"))
    if customer_issue_count > 0:
        signals.append(
            make_signal(
                store=store,
                signal_type="customer_service_issue",
                title="客服问题",
                severity="medium" if customer_issue_count < 8 else "high",
                value=customer_issue_count,
                threshold=0,
                evidence=f"发现 {customer_issue_count} 个客服问题",
            )
        )
    return signals


def add_drop_signal(signals: list[dict[str, Any]], data: dict[str, Any], store: str, key: str, signal_type: str, title: str) -> None:
    value = safe_float(data.get(key))
    if value <= -0.1:
        severity = "high" if value <= -0.2 else "medium"
        signals.append(
            make_signal(
                store=store,
                signal_type=signal_type,
                title=title,
                severity=severity,
                value=value,
                threshold=-0.1,
                evidence=f"{title} {abs(round(value * 100, 2))}%",
            )
        )


def make_signal(store: str, signal_type: str, title: str, severity: str, value: int | float, threshold: int | float, evidence: str) -> dict[str, Any]:
    return {
        "store": store,
        "signal_type": signal_type,
        "title": title,
        "severity": severity,
        "value": value,
        "threshold": threshold,
        "evidence": evidence,
        "lifecycle_stage": "discovered",
    }


def safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
