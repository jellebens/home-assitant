"""Energy-series conversion tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from zeus.forecaster import counter_history_to_energy, power_history_to_energy


def _grid(values, step_min=60):
    t0 = datetime(2026, 6, 24, 0, 0)
    return [(t0 + i * timedelta(minutes=step_min), v) for i, v in enumerate(values)]


def test_power_to_energy_watts():
    # 1000 W held for 1 h = 1 kWh per slot.
    s = power_history_to_energy(_grid([1000.0, 1000.0]), timedelta(hours=1))
    assert list(s) == pytest.approx([1.0, 1.0])


def test_counter_diff_gives_per_slot_energy():
    # Monotonic kWh counter: deltas are per-slot consumption; last slot dropped.
    s = counter_history_to_energy(_grid([100.0, 100.4, 101.0, 101.1]))
    assert list(s) == pytest.approx([0.4, 0.6, 0.1])


def test_counter_reset_clamped_to_zero():
    # A decrease (meter reset/rollover) must not produce negative consumption.
    s = counter_history_to_energy(_grid([5.0, 5.2, 0.0, 0.3]))
    assert list(s) == pytest.approx([0.2, 0.0, 0.3])


def test_counter_too_short_is_empty():
    assert counter_history_to_energy(_grid([1.0])).empty
