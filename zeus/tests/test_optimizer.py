"""Optimizer behavior tests.

These pin the economic intuition (charge cheap, discharge expensive) and the
hard constraints (power + SoC limits), which is what we most need to trust.
"""

from __future__ import annotations

import pytest

from zeus.config import BatteryConfig, OptimizerConfig
from zeus.optimizer import DispatchInputs, optimize_dispatch


def make_battery(**kw) -> BatteryConfig:
    base = dict(
        usable_capacity_kwh=10.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        soc_min_pct=10.0,
        soc_max_pct=100.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
    )
    base.update(kw)
    return BatteryConfig(**base)


def make_opt(**kw) -> OptimizerConfig:
    base = dict(horizon_hours=4, slot_minutes=60, cycle_penalty=0.0, terminal_value_price=0.0)
    base.update(kw)
    return OptimizerConfig(**base)


def test_charges_when_cheap_discharges_when_expensive():
    # Two cheap hours, then two expensive hours; flat 1 kWh/h load.
    prices = [0.05, 0.05, 0.40, 0.40]
    inp = DispatchInputs(
        load_kwh=[1.0] * 4,
        solar_kwh=[0.0] * 4,
        import_price=prices,
        export_price=[0.0] * 4,
        soc0_kwh=1.0,  # = soc_min (10% of 10 kWh)
    )
    plan = optimize_dispatch(inp, make_battery(), make_opt())

    assert plan.status == "Optimal"
    # Charges during the cheap hours...
    assert sum(plan.charge_kw[:2]) > 0
    # ...and discharges during the expensive hours.
    assert sum(plan.discharge_kw[2:]) > 0
    # No discharging while it is cheap.
    assert plan.discharge_kw[0] == pytest.approx(0.0, abs=1e-6)


def test_respects_power_limits():
    prices = [0.05, 0.40]
    inp = DispatchInputs([1.0, 1.0], [0.0, 0.0], prices, [0.0, 0.0], soc0_kwh=1.0)
    battery = make_battery(max_charge_kw=1.5, max_discharge_kw=1.0)
    plan = optimize_dispatch(inp, battery, make_opt(horizon_hours=2))

    assert all(c <= 1.5 + 1e-6 for c in plan.charge_kw)
    assert all(d <= 1.0 + 1e-6 for d in plan.discharge_kw)


def test_respects_soc_bounds():
    prices = [0.05, 0.05, 0.40, 0.40]
    inp = DispatchInputs([0.5] * 4, [0.0] * 4, prices, [0.0] * 4, soc0_kwh=5.0)
    battery = make_battery(usable_capacity_kwh=6.0, soc_min_pct=10.0, soc_max_pct=90.0)
    plan = optimize_dispatch(inp, battery, make_opt())

    lo = battery.soc_min_kwh - 1e-6
    hi = battery.soc_max_kwh + 1e-6
    assert all(lo <= s <= hi for s in plan.soc_kwh)


def test_efficiency_losses_discourage_useless_cycling():
    # Flat price, with terminal energy valued at that price: there is no reason
    # to charge or to drain the battery, so the optimizer should leave it alone.
    prices = [0.20] * 4
    inp = DispatchInputs([1.0] * 4, [0.0] * 4, prices, [0.0] * 4, soc0_kwh=5.0)
    battery = make_battery(charge_efficiency=0.9, discharge_efficiency=0.9)
    plan = optimize_dispatch(inp, battery, make_opt(cycle_penalty=0.001, terminal_value_price=0.20))

    assert sum(plan.charge_kw) == pytest.approx(0.0, abs=1e-6)
    assert sum(plan.discharge_kw) == pytest.approx(0.0, abs=1e-6)


def test_solar_surplus_charges_battery():
    # Midday solar exceeds load; cheap to store surplus rather than export at 0.
    inp = DispatchInputs(
        load_kwh=[0.2, 0.2],
        solar_kwh=[2.0, 0.0],
        import_price=[0.30, 0.30],
        export_price=[0.0, 0.0],
        soc0_kwh=1.0,
    )
    plan = optimize_dispatch(inp, make_battery(), make_opt(horizon_hours=2, terminal_value_price=0.30))
    # Surplus solar in slot 0 should be stored, then used in slot 1.
    assert plan.charge_kw[0] > 0
