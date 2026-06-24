"""Prometheus metrics for Zeus.

Exposes a /metrics endpoint (via prometheus_client) that kube-prometheus-stack
scrapes through a ServiceMonitor. Gauges are refreshed once per optimization
cycle; the HTTP server is started once at startup.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, start_http_server

log = logging.getLogger(__name__)

# Battery / plan state (current slot).
SOC = Gauge("zeus_soc_percent", "Battery state of charge (percent)")
TARGET_CHARGE = Gauge("zeus_target_charge_kw", "Optimizer target charge power, current slot (kW)")
TARGET_DISCHARGE = Gauge("zeus_target_discharge_kw", "Optimizer target discharge power, current slot (kW)")
PLAN_COST = Gauge("zeus_plan_cost_eur", "Optimizer objective value over the horizon (EUR)")
IMPORT_PRICE = Gauge("zeus_import_price_eur_per_kwh", "All-in import price, current slot (EUR/kWh)")
WORKING_MODE = Gauge("zeus_working_mode", "Active working mode (1=active)", ["mode"])

# Realized savings (today).
SAVINGS_TODAY = Gauge("zeus_savings_today_eur", "Realized savings so far today (EUR)")
BASELINE_TODAY = Gauge("zeus_baseline_cost_today_eur", "Baseline (no-battery) cost today (EUR)")
ACTUAL_TODAY = Gauge("zeus_actual_cost_today_eur", "Actual cost today (EUR)")
CHARGED_TODAY = Gauge("zeus_energy_charged_today_kwh", "Energy charged today (kWh)")
DISCHARGED_TODAY = Gauge("zeus_energy_discharged_today_kwh", "Energy discharged today (kWh)")

# Health.
LAST_CYCLE = Gauge("zeus_last_cycle_timestamp_seconds", "Unix time of the last completed cycle")
CYCLE_FAILURES = Counter("zeus_cycle_failures_total", "Optimization cycles that raised an error")

_MODES = ("charging", "discharging", "passthrough")


def serve(port: int) -> None:
    start_http_server(port)
    log.info("Prometheus metrics on :%d/metrics", port)


def set_working_mode(active: str) -> None:
    """active is one of charging/discharging/passthrough (or '' to clear)."""
    for m in _MODES:
        WORKING_MODE.labels(mode=m).set(1.0 if m == active else 0.0)
