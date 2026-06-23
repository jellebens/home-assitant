"""Battery actuation with safety guards (Phase 3).

Translates the first slot of an optimizer plan into a concrete command to the
Bluetti. Every command is clamped to the configured limits and refused outright
in unsafe states, and the whole module is a no-op unless ``control.enabled`` is
set and ``run.dry_run`` is false. Until Phase 0 confirms a writable control
surface, leave control disabled and rely on the advisory schedule.
"""

from __future__ import annotations

import logging

from .config import BatteryConfig, ControlConfig
from .ha_client import HAClient

log = logging.getLogger(__name__)


class Controller:
    def __init__(
        self, ha: HAClient, control: ControlConfig, battery: BatteryConfig, dry_run: bool
    ):
        self.ha = ha
        self.control = control
        self.battery = battery
        self.dry_run = dry_run
        self._last_option: str | None = None  # avoid redundant select switches

    def apply(self, charge_kw: float, discharge_kw: float, soc_pct: float) -> str:
        """Apply the desired setpoints. Returns a human-readable action string.

        Safety guards (fail closed -> no battery action):
          - never charge at/above soc_max, never discharge at/below soc_min
          - clamp power to configured maxima
          - never charge and discharge simultaneously
        """
        charge_kw, discharge_kw = self._guarded_setpoints(charge_kw, discharge_kw, soc_pct)

        if self.control.mode == "working_mode":
            option = self._intent_option(charge_kw, discharge_kw)
            desc = f"working_mode -> {option!r} (charge={charge_kw:.2f} discharge={discharge_kw:.2f}kW)"
        else:
            desc = f"charge={charge_kw:.2f}kW discharge={discharge_kw:.2f}kW"

        if not self.control.enabled or self.dry_run:
            log.info("[advisory] would set %s (control disabled / dry-run)", desc)
            return f"advisory: {desc}"

        if self.control.mode == "working_mode":
            self._apply_working_mode(charge_kw, discharge_kw)
        elif self.control.mode == "ha_service":
            self._apply_ha_service((charge_kw, discharge_kw))
        else:
            raise NotImplementedError(f"control.mode={self.control.mode} not implemented")
        log.info("applied %s", desc)
        return f"applied: {desc}"

    def _intent_option(self, charge_kw: float, discharge_kw: float) -> str:
        """Map guarded setpoints to the working-mode option to select."""
        wm = self.control.working_mode
        thr = wm.intent_threshold_kw
        if charge_kw >= thr and charge_kw >= discharge_kw:
            return wm.charge_option
        if discharge_kw >= thr:
            return wm.discharge_option
        return wm.idle_option

    def _apply_working_mode(self, charge_kw: float, discharge_kw: float) -> None:
        wm = self.control.working_mode
        option = self._intent_option(charge_kw, discharge_kw)
        if not option:
            raise ValueError(
                "control.working_mode option is empty for the chosen intent; "
                "fill charge_option/discharge_option/idle_option in config"
            )
        if option == self._last_option:
            return  # already in the desired mode
        self.ha.call_service("select", "select_option", {"entity_id": wm.entity, "option": option})
        self._last_option = option

    def _guarded_setpoints(
        self, charge_kw: float, discharge_kw: float, soc_pct: float
    ) -> tuple[float, float]:
        charge_kw = max(0.0, min(charge_kw, self.battery.max_charge_kw))
        discharge_kw = max(0.0, min(discharge_kw, self.battery.max_discharge_kw))

        if soc_pct >= self.battery.soc_max_pct:
            charge_kw = 0.0
        if soc_pct <= self.battery.soc_min_pct:
            discharge_kw = 0.0
        # Forbid simultaneous charge+discharge: keep the larger intent only.
        if charge_kw > 0 and discharge_kw > 0:
            if charge_kw >= discharge_kw:
                discharge_kw = 0.0
            else:
                charge_kw = 0.0
        return charge_kw, discharge_kw

    def _apply_ha_service(self, setpoints: tuple[float, float]) -> None:
        charge_kw, discharge_kw = setpoints
        c_domain, c_service = self.control.set_charge_service.split("/", 1)
        d_domain, d_service = self.control.set_discharge_service.split("/", 1)
        self.ha.call_service(
            c_domain, c_service,
            {"entity_id": self.control.set_charge_entity, "value": round(charge_kw * 1000)},
        )
        self.ha.call_service(
            d_domain, d_service,
            {"entity_id": self.control.set_discharge_entity, "value": round(discharge_kw * 1000)},
        )
