"""Linear-program battery dispatch optimizer.

Given an hourly (or sub-hourly) forecast of house load, optional solar, and
import/export prices over a horizon, decide how much to charge and discharge
the battery in each slot to minimize total grid cost, subject to the battery's
power and state-of-charge limits.

The model is a continuous LP (no binaries): simultaneous charge+discharge is
never optimal because of round-trip efficiency losses, so we do not need an
integer constraint to forbid it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

from .config import BatteryConfig, OptimizerConfig


@dataclass
class DispatchInputs:
    """One value per slot. All sequences must share the same length."""

    load_kwh: list[float]          # forecast house consumption per slot (kWh)
    solar_kwh: list[float]         # forecast PV production per slot (kWh)
    import_price: list[float]      # all-in import price per slot (EUR/kWh)
    export_price: list[float]      # value of exported energy per slot (EUR/kWh)
    soc0_kwh: float                # battery energy at start of horizon (kWh)

    def __post_init__(self) -> None:
        n = len(self.load_kwh)
        for name in ("solar_kwh", "import_price", "export_price"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"DispatchInputs.{name} length {len(getattr(self, name))} != {n}")

    @property
    def num_slots(self) -> int:
        return len(self.load_kwh)


@dataclass
class DispatchPlan:
    """Optimizer output. One value per slot unless noted."""

    charge_kw: list[float]         # grid -> battery power per slot
    discharge_kw: list[float]      # battery -> load power per slot
    soc_kwh: list[float]           # battery energy at the END of each slot
    grid_import_kwh: list[float]
    grid_export_kwh: list[float]
    total_cost: float              # objective value (EUR), incl. penalties/terminal value
    status: str                    # solver status, e.g. "Optimal"


def optimize_dispatch(
    inputs: DispatchInputs,
    battery: BatteryConfig,
    opt: OptimizerConfig,
) -> DispatchPlan:
    """Solve the dispatch LP and return the optimal plan.

    Sign/energy conventions (per slot of length ``dt`` hours):
      stored gained from charging   = charge_kw * dt * charge_efficiency
      stored spent for discharging  = discharge_kw * dt / discharge_efficiency
      grid_import - grid_export     = load - solar + charge_kw*dt - discharge_kw*dt
    """
    n = inputs.num_slots
    if n == 0:
        return DispatchPlan([], [], [], [], [], 0.0, "Empty")

    dt = opt.slot_hours
    eta_c = battery.charge_efficiency
    eta_d = battery.discharge_efficiency
    soc_min = battery.soc_min_kwh
    soc_max = battery.soc_max_kwh

    prob = pulp.LpProblem("battery_dispatch", pulp.LpMinimize)

    charge = [pulp.LpVariable(f"charge_{t}", 0, battery.max_charge_kw) for t in range(n)]
    discharge = [pulp.LpVariable(f"discharge_{t}", 0, battery.max_discharge_kw) for t in range(n)]
    soc = [pulp.LpVariable(f"soc_{t}", soc_min, soc_max) for t in range(n)]
    imp = [pulp.LpVariable(f"import_{t}", 0) for t in range(n)]
    exp = [pulp.LpVariable(f"export_{t}", 0) for t in range(n)]

    prev_soc = inputs.soc0_kwh
    for t in range(n):
        # Battery energy balance.
        prob += (
            soc[t] == prev_soc
            + charge[t] * dt * eta_c
            - discharge[t] * dt / eta_d
        ), f"soc_balance_{t}"
        # Grid balance: everything the house needs that the battery/solar do not
        # cover is imported; any surplus is exported.
        prob += (
            imp[t] - exp[t]
            == inputs.load_kwh[t] - inputs.solar_kwh[t]
            + charge[t] * dt - discharge[t] * dt
        ), f"grid_balance_{t}"
        prev_soc = soc[t]

    # Value any energy left in the battery at the end of the horizon so the
    # optimizer does not drain it for free in the final slots.
    if opt.terminal_value_price is not None:
        terminal_price = opt.terminal_value_price
    else:
        terminal_price = sum(inputs.import_price) / n
    terminal_value = soc[n - 1] * eta_d * terminal_price

    cost = pulp.lpSum(
        imp[t] * inputs.import_price[t]
        - exp[t] * inputs.export_price[t]
        + (charge[t] + discharge[t]) * dt * opt.cycle_penalty
        for t in range(n)
    ) - terminal_value

    prob += cost

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[prob.status]

    def vals(vars_: list[pulp.LpVariable]) -> list[float]:
        return [float(v.value() or 0.0) for v in vars_]

    return DispatchPlan(
        charge_kw=vals(charge),
        discharge_kw=vals(discharge),
        soc_kwh=vals(soc),
        grid_import_kwh=vals(imp),
        grid_export_kwh=vals(exp),
        total_cost=float(pulp.value(prob.objective) or 0.0),
        status=status,
    )
