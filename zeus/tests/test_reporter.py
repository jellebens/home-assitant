"""Savings accounting tests."""

from __future__ import annotations

import pytest

from zeus.reporter import compute_savings


def test_discharge_at_peak_saves_money():
    # 1 kWh load both hours. Battery discharges 1 kWh during the expensive hour
    # and is charged 1 kWh during the cheap hour.
    result = compute_savings(
        load_kwh=[1.0, 1.0],
        solar_kwh=[0.0, 0.0],
        charge_kwh=[1.0, 0.0],
        discharge_kwh=[0.0, 1.0],
        import_price=[0.10, 0.40],
        export_price=[0.0, 0.0],
    )
    # Baseline: 1*0.10 + 1*0.40 = 0.50
    assert result.baseline_cost == pytest.approx(0.50)
    # Actual: hour0 imports load+charge = 2*0.10 = 0.20; hour1 import 0 = 0.00
    assert result.actual_cost == pytest.approx(0.20)
    assert result.savings == pytest.approx(0.30)
    assert result.savings_pct == pytest.approx(60.0)


def test_no_battery_means_zero_savings():
    result = compute_savings(
        load_kwh=[1.0, 1.0],
        solar_kwh=[0.0, 0.0],
        charge_kwh=[0.0, 0.0],
        discharge_kwh=[0.0, 0.0],
        import_price=[0.10, 0.40],
        export_price=[0.0, 0.0],
    )
    assert result.savings == pytest.approx(0.0)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_savings([1.0, 1.0], [0.0], [0.0, 0.0], [0.0, 0.0], [0.1, 0.1], [0.0, 0.0])
