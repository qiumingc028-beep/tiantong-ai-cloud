from datetime import date

import pytest

from backend.models import JdAd, JdDailyMetric, JdOrder, JdProduct
from backend.services import jd_collectors as collectors

COMPLETE_ROWS = {
    "metrics": {"gmv": 1, "profit_amount": 1, "visitors_count": 1, "paid_orders_count": 1,
                "ad_spend": 1, "roi": 1, "refunds_count": 0, "after_sales_count": 0,
                "favorites_count": 0, "cart_add_count": 0, "conversion_rate": 1},
    "orders": {"order_no": "required-order", "paid_amount": 1, "profit_amount": 1},
    "products": {"sku_id": "required-sku", "stock_quantity": 1, "sales_amount": 1,
                 "sales_quantity": 1, "visitors_count": 1, "conversion_rate": 1},
    "ads": {"campaign_id": "required-campaign", "ad_spend": 1, "clicks": 1, "impressions": 1,
            "roi": 1, "cpa": 1, "deal_amount": 1},
}


def complete_row(dataset, **values):
    """Known synthetic observations, not a production missing-value fallback."""
    return {**COMPLETE_ROWS[dataset], **values}


@pytest.mark.parametrize("dataset,missing", [(dataset, field) for dataset, row in COMPLETE_ROWS.items() for field in row])
def test_missing_required_observation_never_becomes_a_persisted_zero(test_db, dataset, missing):
    row = dict(COMPLETE_ROWS[dataset])
    del row[missing]
    with test_db() as db:
        calls = {
            "metrics": lambda: collectors.save_jd_daily_metric(db, 1, date(2026, 9, 7), row, "jd_smart"),
            "orders": lambda: collectors.save_order(db, 1, row),
            "products": lambda: collectors.save_product(db, 1, row),
            "ads": lambda: collectors.save_ad(db, 1, None, date(2026, 9, 7), row),
        }
        with pytest.raises(collectors.JdCollectorError):
            calls[dataset]()
        db.commit()
        model = {"metrics": JdDailyMetric, "orders": JdOrder, "products": JdProduct, "ads": JdAd}[dataset]
        assert db.query(model).count() == 0
