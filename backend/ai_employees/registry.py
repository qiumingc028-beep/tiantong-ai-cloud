from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AiEmployeeProfile:
    code: str
    name: str
    department: str
    task_type: str


TIANCAI_DATA = "tiancai_data"
TIANSHU = "tianshu"
TIANCE_STRATEGY = "tiance_strategy"
TIANBO = "tianbo"
TIANCHUANG = "tianchuang"
TIANSHANG = "tianshang"
TIANTOU = "tiantou"
TIANJIAN_TEST = "tianjian_test"
TIANDUN_OPS = "tiandun_ops"

DEFAULT_COLLECTOR_EMPLOYEE = TIANCAI_DATA
DEFAULT_STRATEGY_EMPLOYEE = TIANCE_STRATEGY

AI_EMPLOYEE_REGISTRY: dict[str, AiEmployeeProfile] = {
    TIANCAI_DATA: AiEmployeeProfile(TIANCAI_DATA, "天采：数据采集平台", "数据资产军团", "data_collection"),
    TIANSHU: AiEmployeeProfile(TIANSHU, "天数：数据分析中心", "数据资产军团", "data_analysis"),
    TIANCE_STRATEGY: AiEmployeeProfile(TIANCE_STRATEGY, "天策：策略分析中心", "经营策略军团", "strategy_planning"),
    TIANBO: AiEmployeeProfile(TIANBO, "天播：视频中心", "内容创意军团", "video_script"),
    TIANCHUANG: AiEmployeeProfile(TIANCHUANG, "天创：设计中心", "内容创意军团", "creative_design"),
    TIANSHANG: AiEmployeeProfile(TIANSHANG, "天商：商品中心", "电商经营军团", "ecommerce_operation"),
    TIANTOU: AiEmployeeProfile(TIANTOU, "天投：广告投放中心", "增长投放军团", "ad_analysis"),
    TIANJIAN_TEST: AiEmployeeProfile(TIANJIAN_TEST, "天检：测试验收中心", "质量验收军团", "quality_acceptance"),
    TIANDUN_OPS: AiEmployeeProfile(TIANDUN_OPS, "天盾：部署运维修复", "部署运维军团", "ops_safety_review"),
}

EMPLOYEE_CODE_ALIASES = {
    "tian_cai": TIANCAI_DATA,
    "tiancai": TIANCAI_DATA,
    "tian-cai": TIANCAI_DATA,
    "tian_ce": TIANCE_STRATEGY,
    "tiance": TIANCE_STRATEGY,
    "tian-ce": TIANCE_STRATEGY,
    "tian_chuang": TIANCHUANG,
    "tian-chuang": TIANCHUANG,
    "tian_shang": TIANSHANG,
    "tian-shang": TIANSHANG,
    "tian_tou": TIANTOU,
    "tian-tou": TIANTOU,
    "tian_jian": TIANJIAN_TEST,
    "tianjian": TIANJIAN_TEST,
    "tian-jian": TIANJIAN_TEST,
    "tian_dun": TIANDUN_OPS,
    "tiandun": TIANDUN_OPS,
    "tian-dun": TIANDUN_OPS,
}

FLOW_EMPLOYEE_CODES = (TIANCAI_DATA, TIANSHU, TIANCE_STRATEGY, TIANBO)
FLOW_TASK_TYPES = {code: AI_EMPLOYEE_REGISTRY[code].task_type for code in FLOW_EMPLOYEE_CODES}


def normalize_employee_code(code: str | None) -> str | None:
    if code is None:
        return None
    clean = code.strip()
    return EMPLOYEE_CODE_ALIASES.get(clean, clean)


def employee_name(code: str | None) -> str | None:
    normalized = normalize_employee_code(code)
    if normalized is None:
        return None
    profile = AI_EMPLOYEE_REGISTRY.get(normalized)
    return profile.name if profile else normalized
