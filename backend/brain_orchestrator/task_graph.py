from __future__ import annotations

import hashlib

from ..tool_center.gateway import clean_text
from .schemas import TaskGraph, TaskGraphEdge, TaskGraphNode


EMPLOYEE_CATALOG = {
    "tiancai_data": ("天采", "数据采集"),
    "tianshu": ("天数", "数据分析"),
    "tianshang": ("天商", "商品分析"),
    "tiantou": ("天投", "广告分析"),
    "tianyu": ("天誉", "GEO/市场分析"),
    "tiance_strategy": ("天策", "策略分析"),
    "tianjian_test": ("天检", "结果验收"),
}

DEFAULT_NODE_SPECS = [
    ("collect_data", "数据采集", "tiancai_data", ["database_read", "excel_analyzer"], "采集销售、订单、访客、转化数据"),
    ("analyze_sales", "销量分析", "tianshu", ["excel_analyzer"], "分析销量下降趋势和关键指标变化"),
    ("product_review", "商品分析", "tianshang", ["database_read", "excel_analyzer"], "分析商品结构、价格、库存和转化问题"),
    ("ad_review", "广告分析", "tiantou", ["excel_analyzer"], "检查广告消耗、ROI 和投放异常"),
    ("market_review", "市场分析", "tianyu", ["browser_search"], "评估市场、GEO、竞品和外部趋势"),
    ("strategy_summary", "策略建议", "tiance_strategy", ["excel_analyzer"], "汇总原因并生成策略建议"),
    ("acceptance_review", "结果验收", "tianjian_test", ["excel_analyzer"], "验收分析结论和风险边界"),
]

HIGH_RISK_KEYWORDS = ("部署", "删库", "删除", "付款", "购买", "支付", "提交代码", "改权限", "shell", "docker")
MEDIUM_RISK_KEYWORDS = ("联网", "搜索", "外部", "浏览器", "广告", "市场", "竞品", "GEO", "geo")


def build_task_graph(request_text: str) -> TaskGraph:
    goal = clean_text(request_text)[:2000]
    risk_level = infer_graph_risk(goal)
    nodes = build_nodes(goal, risk_level)
    edges = build_edges(nodes)
    return TaskGraph(
        graph_id=build_graph_id(goal),
        goal=goal,
        task_type=infer_task_type(goal),
        risk_level=risk_level,
        approval_required=risk_level in {"medium", "high"} or any(node.approval_required for node in nodes),
        estimated_cost_level=infer_cost_level(nodes),
        dry_run=True,
        nodes=nodes,
        edges=edges,
    )


def build_nodes(goal: str, graph_risk: str) -> list[TaskGraphNode]:
    selected_specs = select_node_specs(goal)
    nodes = []
    for index, (node_id, node_name, employee_code, tools, task_goal) in enumerate(selected_specs, start=1):
        employee_name, employee_role = EMPLOYEE_CATALOG[employee_code]
        risk_level = node_risk_level(node_id, tools, graph_risk)
        nodes.append(
            TaskGraphNode(
                node_id=node_id,
                node_name=node_name,
                node_type="ai_employee",
                employee_code=employee_code,
                employee_name=employee_name,
                employee_role=employee_role,
                task_goal=f"{task_goal}: {goal}",
                required_tools=tools,
                risk_level=risk_level,
                approval_required=risk_level in {"medium", "high"},
                estimated_cost_level="medium" if "browser_search" in tools else "low",
                sequence_order=index,
                status="waiting_approval" if risk_level == "high" else "planned",
            )
        )
    return nodes


def select_node_specs(goal: str) -> list[tuple[str, str, str, list[str], str]]:
    text = goal.lower()
    specs = DEFAULT_NODE_SPECS[:]
    if not any(word in text for word in ("广告", "投放", "roi")):
        specs = [row for row in specs if row[0] != "ad_review"]
    if not any(word in text for word in ("市场", "竞品", "geo", "搜索", "趋势")):
        specs = [row for row in specs if row[0] != "market_review"]
    return specs or DEFAULT_NODE_SPECS[:3]


def build_edges(nodes: list[TaskGraphNode]) -> list[TaskGraphEdge]:
    edges = []
    for source, target in zip(nodes, nodes[1:]):
        edges.append(
            TaskGraphEdge(
                source_node_id=source.node_id,
                target_node_id=target.node_id,
                description=f"{source.node_name}结果传递给{target.node_name}",
            )
        )
    return edges


def infer_task_type(goal: str) -> str:
    text = goal.lower()
    if any(word in text for word in ("销量", "销售", "转化", "订单")):
        return "sales_diagnosis"
    if any(word in text for word in ("广告", "投放", "roi")):
        return "ad_diagnosis"
    return "business_analysis"


def infer_graph_risk(goal: str) -> str:
    text = goal.lower()
    if any(word in text for word in HIGH_RISK_KEYWORDS):
        return "high"
    if any(word.lower() in text for word in MEDIUM_RISK_KEYWORDS):
        return "medium"
    return "low"


def node_risk_level(node_id: str, tools: list[str], graph_risk: str) -> str:
    if graph_risk == "high":
        return "high"
    if "browser_search" in tools or node_id in {"market_review", "ad_review"}:
        return "medium"
    return "low"


def infer_cost_level(nodes: list[TaskGraphNode]) -> str:
    if any("browser_search" in node.required_tools for node in nodes):
        return "medium"
    return "low"


def build_graph_id(goal: str) -> str:
    digest = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:12]
    return f"graph-{digest}"

