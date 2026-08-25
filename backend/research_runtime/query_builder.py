from __future__ import annotations

from .schemas import ResearchPlan


def build_queries(plan: ResearchPlan) -> list[str]:
    return plan.queries[: plan.max_queries]
