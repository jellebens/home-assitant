"""Service entry point: forecast -> optimize -> (actuate) -> report.

Runs one cycle per ``run.interval_minutes``. Each cycle:
  1. read live SoC,
  2. fetch the day-ahead price curve over the horizon,
  3. forecast house load (and solar, if configured) over the horizon,
  4. solve the dispatch LP,
  5. publish the plan and (Phase 3) actuate the current slot,
  6. compute realized savings for today and publish + write a report.

Designed to be safe by default: with ``run.dry_run: true`` (the shipped
default) it never sends a command to the battery.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import metrics
from .config import Config, load_config
from .controller import Controller
from .forecaster import build_forecaster, counter_history_to_energy, power_history_to_energy
from .ha_client import HAClient, history_to_series
from .optimizer import DispatchInputs, optimize_dispatch
from .prices import get_prices
from .reporter import MqttPublisher, compute_arbitrage_savings, compute_savings, result_to_dict

log = logging.getLogger("zeus")


def _slot_aligned_now(tz: ZoneInfo, slot: timedelta) -> datetime:
    """Current time floored to the start of the active slot, in local tz."""
    now = datetime.now(tz)
    if slot >= timedelta(hours=1):
        return now.replace(minute=0, second=0, microsecond=0)
    minutes = (now.minute // int(slot.total_seconds() // 60)) * int(slot.total_seconds() // 60)
    return now.replace(minute=minutes, second=0, microsecond=0)


def _load_energy_series(
    ha: HAClient, entity: str, start: datetime, end: datetime, slot: timedelta,
    is_counter: bool = False,
):
    """Fetch an HA sensor's history and return per-slot energy (kWh).

    Power sensors (W) are integrated over the slot; cumulative energy counters
    (kWh) are differenced when ``is_counter`` is set.
    """
    if not entity:
        return None
    raw = ha.get_history(entity, start, end)
    grid = history_to_series(raw, start, end, slot)
    if is_counter:
        return counter_history_to_energy(grid)
    return power_history_to_energy(grid, slot)


def _safe_mqtt(label: str, fn, *args) -> None:
    """Run a best-effort MQTT publish; log and swallow broker errors."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - MQTT is non-critical surfacing
        log.warning("MQTT %s failed (continuing): %s", label, exc)


def run_once(cfg: Config, ha: HAClient, mqtt: MqttPublisher | None) -> dict:
    tz = ZoneInfo(cfg.reporting.timezone)
    slot = timedelta(minutes=cfg.optimizer.slot_minutes)
    n = cfg.optimizer.num_slots
    start = _slot_aligned_now(tz, slot)

    # 1. Live battery state.
    soc_pct = ha.get_float(cfg.entities.soc, default=cfg.battery.soc_min_pct)
    soc0_kwh = cfg.battery.pct_to_kwh(soc_pct)

    # 2. Prices over the horizon.
    price_slots = get_prices(cfg.prices, ha, start, n, slot)
    import_price = [p.import_price for p in price_slots]
    export_price = [p.export_price for p in price_slots]

    # 3. Load (and solar) forecast over the horizon.
    hist_start = start - timedelta(days=cfg.forecast.history_days)
    load_hist = _load_energy_series(
        ha, cfg.entities.house_load_power, hist_start, start, slot,
        cfg.entities.house_load_is_counter,
    )
    forecaster = build_forecaster(cfg.forecast.model)
    if load_hist is not None and not load_hist.empty:
        forecaster.fit(load_hist)
    slot_starts = [start + i * slot for i in range(n)]
    load_kwh = forecaster.predict(slot_starts)

    solar_kwh = [0.0] * n
    if cfg.entities.solar_power:
        solar_hist = _load_energy_series(ha, cfg.entities.solar_power, hist_start, start, slot)
        if solar_hist is not None and not solar_hist.empty:
            solar_fc = build_forecaster(cfg.forecast.model)
            solar_fc.fit(solar_hist)
            solar_kwh = solar_fc.predict(slot_starts)

    # 4. Optimize.
    plan = optimize_dispatch(
        DispatchInputs(load_kwh, solar_kwh, import_price, export_price, soc0_kwh),
        cfg.battery,
        cfg.optimizer,
    )
    log.info(
        "plan status=%s cost=%.3f charge[0]=%.2fkW discharge[0]=%.2fkW soc=%.0f%%",
        plan.status, plan.total_cost, plan.charge_kw[0], plan.discharge_kw[0], soc_pct,
    )

    # 5. Publish + actuate. MQTT is best-effort: a broker outage must not abort
    # the optimization/actuation cycle.
    if mqtt is not None:
        _safe_mqtt("publish_plan", mqtt.publish_plan, plan.charge_kw, plan.discharge_kw)
    controller = Controller(ha, cfg.control, cfg.battery, cfg.run.dry_run)
    action = controller.apply(plan.charge_kw[0], plan.discharge_kw[0], soc_pct)

    # 6. Realized savings for today (local midnight -> now).
    savings = _todays_savings(cfg, ha, tz, slot)
    if savings is not None:
        if mqtt is not None:
            _safe_mqtt("publish_savings", mqtt.publish_savings, "today", savings)
        _write_report(cfg, tz, savings)

    # 7. Prometheus metrics.
    metrics.SOC.set(soc_pct)
    metrics.TARGET_CHARGE.set(plan.charge_kw[0])
    metrics.TARGET_DISCHARGE.set(plan.discharge_kw[0])
    metrics.PLAN_COST.set(plan.total_cost)
    metrics.IMPORT_PRICE.set(import_price[0])
    metrics.set_working_mode(_intent(plan.charge_kw[0], plan.discharge_kw[0], cfg))
    if savings is not None:
        metrics.SAVINGS_TODAY.set(savings.savings)
        metrics.BASELINE_TODAY.set(savings.baseline_cost)
        metrics.ACTUAL_TODAY.set(savings.actual_cost)
        metrics.CHARGED_TODAY.set(savings.energy_charged_kwh)
        metrics.DISCHARGED_TODAY.set(savings.energy_discharged_kwh)
    metrics.LAST_CYCLE.set_to_current_time()

    return {
        "status": plan.status,
        "action": action,
        "savings_today": result_to_dict(savings) if savings else None,
    }


def _intent(charge_kw: float, discharge_kw: float, cfg: Config) -> str:
    thr = cfg.control.working_mode.intent_threshold_kw
    if charge_kw >= thr and charge_kw >= discharge_kw:
        return "charging"
    if discharge_kw >= thr:
        return "discharging"
    return "passthrough"


def _todays_savings(cfg: Config, ha: HAClient, tz: ZoneInfo, slot: timedelta):
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n = int((now - midnight) / slot)
    if n < 1:
        return None  # not enough of today yet

    def series_or_zeros(entity, is_counter=False):
        if not entity:
            return [0.0] * n
        s = _load_energy_series(ha, entity, midnight, now, slot, is_counter)
        if s is None or s.empty:
            return [0.0] * n
        vals = list(s.to_numpy()[:n])
        return vals + [0.0] * (n - len(vals))

    charge = series_or_zeros(cfg.entities.grid_input_power)
    discharge = series_or_zeros(cfg.entities.ac_output_power)

    price_hist = ha.get_history(cfg.entities.current_price, midnight, now)
    price_series = history_to_series(price_hist, midnight, now, slot)
    import_price = [v + cfg.prices.import_markup for _, v in price_series][:n]
    if len(import_price) < n:
        import_price += [import_price[-1] if import_price else cfg.prices.import_markup] * (
            n - len(import_price)
        )

    if cfg.reporting.mode == "arbitrage":
        # Grid-charged battery powering (critical) loads: savings = value
        # discharged - cost charged. No house-load sensor required.
        return compute_arbitrage_savings(charge, discharge, import_price)

    # Whole-home self-consumption model.
    load = series_or_zeros(cfg.entities.house_load_power, cfg.entities.house_load_is_counter)
    if not any(load):
        return None
    solar = series_or_zeros(cfg.entities.solar_power)
    export_price = [cfg.prices.export_price] * n
    return compute_savings(load, solar, charge, discharge, import_price, export_price)


def _write_report(cfg: Config, tz: ZoneInfo, savings) -> None:
    out_dir = Path(cfg.reporting.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    d = result_to_dict(savings)
    path = out_dir / f"savings-{today}.md"
    path.write_text(
        f"# Savings report {today}\n\n"
        f"- Baseline cost (no battery): €{d['baseline_cost']:.2f}\n"
        f"- Actual cost (with battery): €{d['actual_cost']:.2f}\n"
        f"- **Savings: €{d['savings']:.2f} ({d['savings_pct']:.1f}%)**\n"
        f"- Energy charged: {d['energy_charged_kwh']:.2f} kWh\n"
        f"- Energy discharged: {d['energy_discharged_kwh']:.2f} kWh\n"
        f"- Self-consumption: {d['self_consumption_kwh']:.2f} kWh\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bluetti battery optimizer")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    ha = HAClient(
        cfg.home_assistant.base_url, cfg.home_assistant.token, cfg.home_assistant.verify_ssl
    )
    mqtt = MqttPublisher(cfg.mqtt) if cfg.mqtt.host else None

    if cfg.metrics.enabled:
        metrics.serve(cfg.metrics.port)

    try:
        if args.once:
            run_once(cfg, ha, mqtt)
            return
        interval = cfg.run.interval_minutes * 60
        while True:
            try:
                run_once(cfg, ha, mqtt)
            except Exception:  # noqa: BLE001 - keep the loop alive across transient errors
                metrics.CYCLE_FAILURES.inc()
                log.exception("cycle failed; retrying next interval")
            time.sleep(interval)
    finally:
        if mqtt is not None:
            mqtt.disconnect()


if __name__ == "__main__":
    main()
