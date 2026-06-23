"""Controller safety + working-mode mapping tests."""

from __future__ import annotations

from zeus.config import BatteryConfig, ControlConfig, WorkingModeConfig
from zeus.controller import Controller


class FakeHA:
    def __init__(self):
        self.calls = []

    def call_service(self, domain, service, payload):
        self.calls.append((domain, service, payload))


def make_control(enabled=True) -> ControlConfig:
    return ControlConfig(
        enabled=enabled,
        mode="working_mode",
        working_mode=WorkingModeConfig(
            entity="select.apex_300_working_mode",
            charge_option="Grid Charge",
            discharge_option="Self Use",
            idle_option="Standby",
            intent_threshold_kw=0.1,
        ),
    )


BATT = BatteryConfig(soc_min_pct=10, soc_max_pct=100, max_charge_kw=3.84, max_discharge_kw=3.84)


def test_dry_run_never_calls_ha():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(enabled=True), BATT, dry_run=True)
    result = ctrl.apply(charge_kw=3.0, discharge_kw=0.0, soc_pct=50)
    assert result.startswith("advisory")
    assert ha.calls == []


def test_charge_intent_selects_charge_option():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(), BATT, dry_run=False)
    ctrl.apply(charge_kw=3.0, discharge_kw=0.0, soc_pct=50)
    assert ha.calls[-1] == (
        "select", "select_option",
        {"entity_id": "select.apex_300_working_mode", "option": "Grid Charge"},
    )


def test_discharge_intent_selects_discharge_option():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(), BATT, dry_run=False)
    ctrl.apply(charge_kw=0.0, discharge_kw=2.0, soc_pct=50)
    assert ha.calls[-1][2]["option"] == "Self Use"


def test_idle_when_below_threshold():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(), BATT, dry_run=False)
    ctrl.apply(charge_kw=0.05, discharge_kw=0.0, soc_pct=50)
    assert ha.calls[-1][2]["option"] == "Standby"


def test_soc_floor_blocks_discharge():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(), BATT, dry_run=False)
    # At the floor, a discharge intent must become idle, not discharge.
    ctrl.apply(charge_kw=0.0, discharge_kw=2.0, soc_pct=10)
    assert ha.calls[-1][2]["option"] == "Standby"


def test_redundant_mode_switch_is_skipped():
    ha = FakeHA()
    ctrl = Controller(ha, make_control(), BATT, dry_run=False)
    ctrl.apply(charge_kw=3.0, discharge_kw=0.0, soc_pct=50)
    ctrl.apply(charge_kw=3.0, discharge_kw=0.0, soc_pct=55)  # same intent
    assert len(ha.calls) == 1  # second call skipped
