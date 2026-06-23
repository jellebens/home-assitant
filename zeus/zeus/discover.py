"""Phase 0 discovery: probe the live Home Assistant instance.

Answers the three questions the plan left open, read-only:
  1. Control path  -- which Bluetti entities are writable (number/switch/select)?
  2. Price forecast -- does the price sensor expose a future-prices attribute?
  3. History       -- is recorder history available for the load/SoC sensors?

Writes findings to DISCOVERY.md next to the config. Makes no changes to HA.

Usage:
    python -m zeus.discover --config config.yaml
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_config
from .ha_client import HAClient

# Domains whose entities can be commanded (candidate control surfaces).
WRITABLE_DOMAINS = ("number", "switch", "select", "input_number", "input_select")
# Attribute names dynamic-tariff integrations commonly use for future prices.
FORECAST_ATTRS = ("forecast", "raw_today", "raw_tomorrow", "prices", "today", "tomorrow")


def discover(cfg_path: str) -> str:
    cfg = load_config(cfg_path)
    ha = HAClient(
        cfg.home_assistant.base_url, cfg.home_assistant.token, cfg.home_assistant.verify_ssl
    )
    lines: list[str] = ["# Phase 0 Discovery", ""]
    lines.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_\n")

    if not ha.ping():
        return "Could not reach Home Assistant API. Check base_url and token."

    states = ha.list_states()
    lines += _section_control(states)
    lines += _section_prices(ha, states, cfg.entities.current_price)
    lines += _section_history(ha, cfg.entities)
    return "\n".join(lines)


def _section_control(states: list[dict]) -> list[str]:
    out = ["## 1. Control surface (writable Bluetti entities)", ""]
    candidates = [
        s for s in states
        if s["entity_id"].split(".")[0] in WRITABLE_DOMAINS
        and any(
            kw in (s["entity_id"] + s.get("attributes", {}).get("friendly_name", "")).lower()
            for kw in ("buzzbrick", "bluetti", "apex")
        )
    ]
    if not candidates:
        out += [
            "No writable `number/switch/select` entities matched buzzbrick/bluetti.",
            "=> No HA control path found. Keep `control.enabled: false`; check whether",
            "   the integration exposes control, or plan an MQTT/BLE write path.",
            "",
        ]
        return out
    out.append("Found candidate control entities:")
    out.append("")
    for s in candidates:
        attrs = s.get("attributes", {})
        extra = ""
        if "min" in attrs and "max" in attrs:
            extra = f" range [{attrs['min']}, {attrs['max']}] step {attrs.get('step')}"
        elif "options" in attrs:
            extra = f" options {attrs['options']}"
        out.append(f"- `{s['entity_id']}` = {s['state']}{extra}")
    out.append("")
    out.append("=> Map the charge/discharge ones into `control.*` in config.yaml.")
    out.append("")
    return out


def _section_prices(ha: HAClient, states: list[dict], price_entity: str) -> list[str]:
    out = ["## 2. Price forecast", ""]
    target = next((s for s in states if s["entity_id"] == price_entity), None)
    if target is None:
        out += [f"Price entity `{price_entity}` not found.", ""]
        return out
    attrs = target.get("attributes", {})
    found = [a for a in FORECAST_ATTRS if isinstance(attrs.get(a), list) and attrs.get(a)]
    out.append(f"Price entity `{price_entity}` = {target['state']}")
    out.append(f"Attributes present: {sorted(attrs.keys())}")
    if found:
        sample = attrs[found[0]][:2]
        out.append(f"=> Forecast attribute(s): {found}. Sample of `{found[0]}`:")
        out.append("```json")
        out.append(json.dumps(sample, indent=2, default=str))
        out.append("```")
        out.append(f"Set prices.source=ha_forecast, forecast_attribute={found[0]}.")
    else:
        out.append("=> No forecast attribute found. Use prices.source=entsoe (or another")
        out.append("   day-ahead source) to get future prices.")
    out.append("")
    return out


def _section_history(ha: HAClient, entities) -> list[str]:
    out = ["## 3. History availability", ""]
    start = datetime.now(timezone.utc) - timedelta(hours=24)
    for label, entity in (("house load", entities.house_load_power), ("SoC", entities.soc)):
        if not entity:
            continue
        try:
            points = ha.get_history(entity, start)
            out.append(f"- {label} `{entity}`: {len(points)} points in last 24h")
        except Exception as exc:  # noqa: BLE001 - report, don't crash discovery
            out.append(f"- {label} `{entity}`: history error: {exc}")
    out.append("")
    out.append("=> If counts are healthy, recorder history is usable for training.")
    out.append("")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Bluetti optimizer Phase 0 discovery")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", default="DISCOVERY.md")
    args = parser.parse_args()

    report = discover(args.config)
    Path(args.out).write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
