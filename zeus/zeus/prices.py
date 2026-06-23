"""Day-ahead electricity price retrieval and normalization.

Produces a list of ``PriceSlot`` covering the optimizer horizon, with the all-in
import price (raw market price + configured markup) and an export price, aligned
to the run's slot grid.

Two sources are supported:
  - ha_forecast: read a list of future prices from an attribute on an HA price
    sensor (most dynamic-tariff integrations expose one, e.g. ``forecast`` or
    ``raw_today``/``raw_tomorrow``).
  - entsoe: query the ENTSO-E transparency API for day-ahead prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from .config import PricesConfig
from .ha_client import HAClient

log = logging.getLogger(__name__)


@dataclass
class PriceSlot:
    start: datetime           # slot start (timezone-aware)
    import_price: float       # all-in EUR/kWh
    export_price: float       # EUR/kWh


def get_prices(
    cfg: PricesConfig, ha: HAClient, start: datetime, num_slots: int, slot: timedelta
) -> list[PriceSlot]:
    """Return ``num_slots`` price slots starting at ``start``."""
    if cfg.source == "ha_forecast":
        raw = _from_ha_forecast(cfg, ha)
    elif cfg.source == "entsoe":
        raw = _from_entsoe(cfg, start, num_slots, slot)
    else:
        raise ValueError(f"unknown prices.source: {cfg.source}")
    return _align(raw, cfg, start, num_slots, slot)


def _from_ha_forecast(cfg: PricesConfig, ha: HAClient) -> list[tuple[datetime, float]]:
    """Pull (start, raw_price) pairs from an HA sensor's forecast attribute.

    Accepts the common shapes seen in the wild:
      [{"start": iso, "price": x}, ...]
      [{"from": iso, "value": x}, ...]
      [{"datetime": iso, "price": x}, ...]
    """
    fc = cfg.ha_forecast
    state = ha.get_state(fc.entity)
    attr = state.get("attributes", {})
    series = attr.get(fc.forecast_attribute)
    if not series:
        # Fall back to today+tomorrow raw lists if present.
        series = (attr.get("raw_today") or []) + (attr.get("raw_tomorrow") or [])
    if not series:
        raise ValueError(
            f"no forecast on {fc.entity}.{fc.forecast_attribute}; "
            "run discovery to find the right attribute or switch prices.source"
        )

    out: list[tuple[datetime, float]] = []
    for item in series:
        ts = item.get("start") or item.get("from") or item.get("datetime") or item.get("hour")
        price = item.get("price")
        if price is None:
            price = item.get("value")
        if ts is None or price is None:
            continue
        out.append((_parse_dt(ts), float(price)))
    out.sort(key=lambda x: x[0])
    return out


def _from_entsoe(
    cfg: PricesConfig, start: datetime, num_slots: int, slot: timedelta
) -> list[tuple[datetime, float]]:
    """Fetch day-ahead prices (EUR/MWh) from ENTSO-E and convert to EUR/kWh."""
    e = cfg.entsoe
    if not e.api_token or not e.area_code:
        raise ValueError("prices.source=entsoe requires entsoe.api_token and area_code")
    period_start = start.astimezone(timezone.utc).strftime("%Y%m%d%H00")
    period_end = (start + num_slots * slot).astimezone(timezone.utc).strftime("%Y%m%d%H00")
    params = {
        "securityToken": e.api_token,
        "documentType": "A44",  # price document
        "in_Domain": e.area_code,
        "out_Domain": e.area_code,
        "periodStart": period_start,
        "periodEnd": period_end,
    }
    resp = requests.get("https://web-api.tp.entsoe.eu/api", params=params, timeout=30)
    resp.raise_for_status()
    return _parse_entsoe_xml(resp.text)


def _parse_entsoe_xml(xml_text: str) -> list[tuple[datetime, float]]:
    """Parse ENTSO-E A44 XML into (start, EUR/kWh) hourly points."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    ns = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

    def find(el, tag):
        return el.find(f"ns:{tag}", ns) if ns else el.find(tag)

    def findall(el, tag):
        return el.findall(f"ns:{tag}", ns) if ns else el.findall(tag)

    out: list[tuple[datetime, float]] = []
    for ts in findall(root, "TimeSeries"):
        period = find(ts, "Period")
        if period is None:
            continue
        interval = find(period, "timeInterval")
        start_txt = find(interval, "start").text
        period_start = _parse_dt(start_txt)
        resolution = find(period, "resolution").text  # e.g. PT60M
        step_min = 60 if "60M" in resolution else (15 if "15M" in resolution else 60)
        for point in findall(period, "Point"):
            position = int(find(point, "position").text)
            price_mwh = float(find(point, "price.amount").text)
            ts_start = period_start + timedelta(minutes=step_min * (position - 1))
            out.append((ts_start, price_mwh / 1000.0))  # EUR/MWh -> EUR/kWh
    out.sort(key=lambda x: x[0])
    return out


def _align(
    raw: list[tuple[datetime, float]],
    cfg: PricesConfig,
    start: datetime,
    num_slots: int,
    slot: timedelta,
) -> list[PriceSlot]:
    """Map raw (start, price) points onto the optimizer's slot grid via LOCF."""
    if not raw:
        raise ValueError("no price points available for the requested horizon")
    raw.sort(key=lambda x: x[0])
    slots: list[PriceSlot] = []
    idx = 0
    last = raw[0][1]
    t = start
    for _ in range(num_slots):
        while idx < len(raw) and raw[idx][0] <= t:
            last = raw[idx][1]
            idx += 1
        slots.append(
            PriceSlot(
                start=t,
                import_price=last + cfg.import_markup,
                export_price=cfg.export_price,
            )
        )
        t += slot
    return slots


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
