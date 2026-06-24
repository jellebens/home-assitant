"""Savings computation and publishing.

The realized saving for a period is the difference between what the grid would
have cost WITHOUT the battery and what it actually cost WITH it:

    baseline_cost = sum_t  price_in[t] * max(0, load - solar)
                         -  price_out[t] * max(0, solar - load)     (export credit)

    actual_cost   = sum_t  price_in[t] * grid_import[t]
                         -  price_out[t] * grid_export[t]

    savings       = baseline_cost - actual_cost

where grid_import/export already reflect the battery's charge/discharge. This is
the same accounting the optimizer minimizes, so modeled and realized numbers are
directly comparable.

Results are written to a CSV/markdown report and published to Home Assistant as
MQTT-discovery sensors so they appear on a dashboard.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from .config import MqttConfig

log = logging.getLogger(__name__)


@dataclass
class SavingsResult:
    baseline_cost: float       # EUR, grid cost with no battery
    actual_cost: float         # EUR, grid cost with the battery
    savings: float             # EUR, baseline - actual
    energy_charged_kwh: float
    energy_discharged_kwh: float
    self_consumption_kwh: float  # solar used directly or via battery

    @property
    def savings_pct(self) -> float:
        return 100.0 * self.savings / self.baseline_cost if self.baseline_cost else 0.0


def compute_arbitrage_savings(
    charge_kwh: list[float],
    discharge_kwh: list[float],
    import_price: list[float],
) -> SavingsResult:
    """Savings for a grid-charged battery that only powers (critical) loads.

    The battery charges from the grid and later discharges to loads that would
    otherwise be served from the grid. So:

        value   = sum_t discharge_kwh[t] * price[t]   (grid import avoided)
        cost    = sum_t charge_kwh[t]    * price[t]   (paid to charge)
        savings = value - cost

    Round-trip losses are captured implicitly (charge_kwh > discharge_kwh). No
    house-load or solar input is needed. ``baseline_cost`` is the would-be grid
    cost of the served loads (= value); ``actual_cost`` is the charging cost.
    """
    n = len(charge_kwh)
    for name, seq in (("discharge_kwh", discharge_kwh), ("import_price", import_price)):
        if len(seq) != n:
            raise ValueError(f"compute_arbitrage_savings: {name} length {len(seq)} != {n}")
    value = sum(discharge_kwh[t] * import_price[t] for t in range(n))
    cost = sum(charge_kwh[t] * import_price[t] for t in range(n))
    return SavingsResult(
        baseline_cost=round(value, 4),
        actual_cost=round(cost, 4),
        savings=round(value - cost, 4),
        energy_charged_kwh=round(sum(charge_kwh), 3),
        energy_discharged_kwh=round(sum(discharge_kwh), 3),
        self_consumption_kwh=0.0,
    )


def compute_savings(
    load_kwh: list[float],
    solar_kwh: list[float],
    charge_kwh: list[float],
    discharge_kwh: list[float],
    import_price: list[float],
    export_price: list[float],
) -> SavingsResult:
    """Compute baseline vs actual grid cost over a series of slots.

    All sequences are per-slot energy (kWh) / price (EUR/kWh) and must be the
    same length. ``charge_kwh``/``discharge_kwh`` are the energy that flowed
    into/out of the battery at the AC side in each slot.
    """
    n = len(load_kwh)
    for name, seq in (
        ("solar_kwh", solar_kwh),
        ("charge_kwh", charge_kwh),
        ("discharge_kwh", discharge_kwh),
        ("import_price", import_price),
        ("export_price", export_price),
    ):
        if len(seq) != n:
            raise ValueError(f"compute_savings: {name} length {len(seq)} != {n}")

    baseline = 0.0
    actual = 0.0
    self_consumption = 0.0
    for t in range(n):
        net = load_kwh[t] - solar_kwh[t]  # >0 demand, <0 surplus
        # No-battery baseline.
        baseline += import_price[t] * max(0.0, net) - export_price[t] * max(0.0, -net)
        # With-battery actual.
        net_with = net + charge_kwh[t] - discharge_kwh[t]
        actual += import_price[t] * max(0.0, net_with) - export_price[t] * max(0.0, -net_with)
        # Solar that did not go to the grid.
        self_consumption += min(solar_kwh[t], load_kwh[t]) + min(
            charge_kwh[t], max(0.0, -net)
        )

    return SavingsResult(
        baseline_cost=round(baseline, 4),
        actual_cost=round(actual, 4),
        savings=round(baseline - actual, 4),
        energy_charged_kwh=round(sum(charge_kwh), 3),
        energy_discharged_kwh=round(sum(discharge_kwh), 3),
        self_consumption_kwh=round(self_consumption, 3),
    )


class MqttPublisher:
    """Publishes optimizer outputs/savings as HA MQTT-discovery sensors.

    Sensor unique_ids follow the repo convention (snake_case, no domain prefix)
    documented in AGENTS.md.
    """

    def __init__(self, cfg: MqttConfig):
        self.cfg = cfg
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        import paho.mqtt.client as mqtt

        client = mqtt.Client()
        if self.cfg.username:
            client.username_pw_set(self.cfg.username, self.cfg.password or "")
        client.connect(self.cfg.host, self.cfg.port, keepalive=60)
        client.loop_start()
        self._client = client
        return client

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    def _publish_discovery(self, key: str, name: str, unit: str, device_class: str | None) -> str:
        base = self.cfg.base_topic
        state_topic = f"{base}/{key}/state"
        config_topic = f"{self.cfg.discovery_prefix}/sensor/{base}_{key}/config"
        payload = {
            "name": name,
            "unique_id": f"{base}_{key}",
            "state_topic": state_topic,
            "unit_of_measurement": unit,
            "device": {
                "identifiers": [base],
                "name": "Zeus",
                "manufacturer": "zeus",
            },
        }
        if device_class:
            payload["device_class"] = device_class
            payload["state_class"] = "measurement"
        self._connect().publish(config_topic, json.dumps(payload), retain=True)
        return state_topic

    def publish_savings(self, period: str, result: SavingsResult) -> None:
        """Publish a savings result. ``period`` is e.g. 'today' or 'total'."""
        metrics = [
            (f"savings_{period}", f"Battery Savings {period.title()}", "EUR", "monetary"),
            (f"baseline_cost_{period}", f"Baseline Cost {period.title()}", "EUR", "monetary"),
            (f"actual_cost_{period}", f"Actual Cost {period.title()}", "EUR", "monetary"),
        ]
        values = {
            f"savings_{period}": result.savings,
            f"baseline_cost_{period}": result.baseline_cost,
            f"actual_cost_{period}": result.actual_cost,
        }
        for key, name, unit, dclass in metrics:
            topic = self._publish_discovery(key, name, unit, dclass)
            self._connect().publish(topic, values[key], retain=True)

    def publish_plan(self, charge_kw: list[float], discharge_kw: list[float]) -> None:
        """Publish the current-slot setpoints and the full schedule as JSON."""
        now_charge = charge_kw[0] if charge_kw else 0.0
        now_discharge = discharge_kw[0] if discharge_kw else 0.0
        for key, name, value in (
            ("target_charge_power", "Target Charge Power", now_charge),
            ("target_discharge_power", "Target Discharge Power", now_discharge),
        ):
            topic = self._publish_discovery(key, name, "kW", "power")
            self._connect().publish(topic, round(value, 3), retain=True)
        # Full schedule for charting.
        topic = self._publish_discovery("schedule", "Optimizer Schedule", "", None)
        self._connect().publish(
            topic,
            json.dumps({"charge_kw": charge_kw, "discharge_kw": discharge_kw}),
            retain=True,
        )


def result_to_dict(result: SavingsResult) -> dict:
    d = asdict(result)
    d["savings_pct"] = round(result.savings_pct, 2)
    return d
