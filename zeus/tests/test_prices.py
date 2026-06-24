"""Price retrieval/normalization tests (Nord Pool ha_forecast shape)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zeus.config import HaForecastConfig, PricesConfig
from zeus.prices import get_prices


class FakeHA:
    def __init__(self, attributes):
        self._attrs = attributes

    def get_state(self, entity_id):
        return {"state": "0", "attributes": self._attrs}


def _hourly(day, cents):
    return [
        {"start": (day + timedelta(hours=h)).isoformat(), "value": c}
        for h, c in enumerate(cents)
    ]


def test_nordpool_scale_and_today_tomorrow_combine():
    day0 = datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc)
    day1 = day0 + timedelta(days=1)
    ha = FakeHA({
        "raw_today": _hourly(day0, [10.0] * 24),     # c/kWh
        "raw_tomorrow": _hourly(day1, [40.0] * 24),
    })
    cfg = PricesConfig(
        source="ha_forecast",
        ha_forecast=HaForecastConfig(entity="sensor.nordpool", forecast_attribute="raw_today"),
        price_scale=0.01,   # c/kWh -> EUR/kWh
        import_markup=0.05,
    )
    slots = get_prices(cfg, ha, day0, num_slots=36, slot=timedelta(hours=1))

    assert len(slots) == 36
    # Today hours: 0.10 + 0.05 markup = 0.15
    assert round(slots[0].import_price, 2) == 0.15
    # Hour 25 falls into tomorrow (0.40 -> 0.40 + 0.05 = 0.45): proves combine.
    assert round(slots[25].import_price, 2) == 0.45
