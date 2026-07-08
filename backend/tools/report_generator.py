from __future__ import annotations


def generate_product_report(goal: str, market_data: dict, analysis: dict) -> dict:
    return {
        "tool": "report_generator",
        "mode": "internal_mock",
        "title": "未来30天男士机械表新品建议",
        "goal": goal,
        "summary": "建议优先开发 800-1500 元商务通勤机械表，辅以礼盒装和透明背设计。",
        "recommendations": [
            "主推价格带：800-1500 元，定位商务通勤。",
            "产品卖点：自动机械、蓝宝石镜面、透底机芯、礼盒套装。",
            "备选价格带：300-699 元，定位入门礼品款。",
            "视觉方向：深蓝/银白表盘，强调质感和职场场景。",
        ],
        "supporting_data": {
            "market": market_data,
            "analysis": analysis,
        },
        "next_actions": [
            "人工确认供应链成本。",
            "人工确认竞品详情页差异。",
            "进入天创生成视觉方案前需老板确认。",
        ],
        "safety_boundary": [
            "不自动上架商品",
            "不自动修改价格",
            "不自动投放广告",
            "不调用外部 API",
        ],
    }
