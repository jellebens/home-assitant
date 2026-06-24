"""Typed configuration loaded from YAML with ${ENV} expansion.

The dataclasses here are the single source of truth for every tunable in the
service. Nothing else should read raw YAML or os.environ for configuration.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import yaml

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} references in strings using os.environ."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class HomeAssistantConfig:
    base_url: str = "http://homeassistant.local:8123"
    token: str = ""
    verify_ssl: bool = True


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    discovery_prefix: str = "homeassistant"
    base_topic: str = "zeus"


@dataclass
class BatteryConfig:
    usable_capacity_kwh: float = 5.0
    max_charge_kw: float = 2.0
    max_discharge_kw: float = 2.0
    soc_min_pct: float = 10.0
    soc_max_pct: float = 100.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95

    @property
    def soc_min_kwh(self) -> float:
        return self.usable_capacity_kwh * self.soc_min_pct / 100.0

    @property
    def soc_max_kwh(self) -> float:
        return self.usable_capacity_kwh * self.soc_max_pct / 100.0

    def pct_to_kwh(self, pct: float) -> float:
        return self.usable_capacity_kwh * pct / 100.0


@dataclass
class EntitiesConfig:
    soc: str = ""
    grid_input_power: str = ""
    ac_output_power: str = ""
    house_load_power: str = ""
    # True if house_load_power is a cumulative energy counter (kWh, e.g. a P1
    # meter total_consumption) rather than an instantaneous power sensor (W).
    # In counter mode per-slot consumption is the difference of readings.
    house_load_is_counter: bool = False
    solar_power: str | None = None
    current_price: str = ""


@dataclass
class WorkingModeConfig:
    """Select-based control: switch the battery's working-mode selector between
    options that mean 'charge from grid', 'discharge / self-powered', and 'idle'.
    Fill the *_option fields with the EXACT labels the select exposes."""

    entity: str = ""
    charge_option: str = ""
    discharge_option: str = ""
    idle_option: str = ""
    # A slot counts as charge/discharge intent only above this power (kW).
    intent_threshold_kw: float = 0.1


@dataclass
class ControlConfig:
    enabled: bool = False
    # "working_mode" = drive a select entity; "ha_service" = set number entities.
    mode: str = "working_mode"
    working_mode: WorkingModeConfig = field(default_factory=WorkingModeConfig)
    set_charge_service: str = "number/set_value"
    set_charge_entity: str = ""
    set_discharge_service: str = "number/set_value"
    set_discharge_entity: str = ""


@dataclass
class HaForecastConfig:
    entity: str = ""
    forecast_attribute: str = "forecast"


@dataclass
class EntsoeConfig:
    api_token: str = ""
    area_code: str = ""


@dataclass
class PricesConfig:
    source: str = "ha_forecast"
    ha_forecast: HaForecastConfig = field(default_factory=HaForecastConfig)
    entsoe: EntsoeConfig = field(default_factory=EntsoeConfig)
    # Multiply raw ha_forecast prices by this before markup (e.g. 0.01 to
    # convert a Nord Pool c/kWh sensor to EUR/kWh).
    price_scale: float = 1.0
    import_markup: float = 0.0
    export_price: float = 0.0


@dataclass
class OptimizerConfig:
    horizon_hours: int = 36
    slot_minutes: int = 60
    cycle_penalty: float = 0.002
    terminal_value_price: float | None = None

    @property
    def slot_hours(self) -> float:
        return self.slot_minutes / 60.0

    @property
    def num_slots(self) -> int:
        return int(round(self.horizon_hours / self.slot_hours))


@dataclass
class ForecastConfig:
    model: str = "baseline"
    history_days: int = 30


@dataclass
class ReportingConfig:
    timezone: str = "Europe/Brussels"
    output_dir: str = "reports"
    # "arbitrage": grid-charged battery powering (critical) loads -> savings =
    # discharge value - charge cost (no house-load sensor needed).
    # "self_consumption": whole-home model (load/solar/grid baseline).
    mode: str = "self_consumption"


@dataclass
class RunConfig:
    interval_minutes: int = 60
    dry_run: bool = True


@dataclass
class Config:
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    entities: EntitiesConfig = field(default_factory=EntitiesConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    prices: PricesConfig = field(default_factory=PricesConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    run: RunConfig = field(default_factory=RunConfig)


def _from_dict(cls: type, data: Any) -> Any:
    """Construct a (possibly nested) dataclass from a plain dict.

    Unknown keys are ignored so the config file can carry comments/extras, and
    missing keys fall back to the dataclass defaults.
    """
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    # `from __future__ import annotations` stores field types as strings, so
    # resolve them to real types before inspecting for nested dataclasses.
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        ftype = hints.get(f.name, f.type)
        # Unwrap Optional[...] to its inner dataclass type if present.
        if get_origin(ftype) is not None:
            inner = [a for a in get_args(ftype) if a is not type(None)]
            ftype = inner[0] if inner else ftype
        if isinstance(ftype, type) and is_dataclass(ftype) and isinstance(raw, dict):
            kwargs[f.name] = _from_dict(ftype, raw)
        else:
            kwargs[f.name] = raw
    return cls(**kwargs)


def load_config(path: str | Path) -> Config:
    """Load and validate configuration from a YAML file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw = _expand_env(raw)
    cfg = _from_dict(Config, raw)
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    b = cfg.battery
    if b.usable_capacity_kwh <= 0:
        raise ValueError("battery.usable_capacity_kwh must be > 0")
    if not (0 <= b.soc_min_pct < b.soc_max_pct <= 100):
        raise ValueError("battery soc_min_pct/soc_max_pct out of range")
    for name, eff in (("charge", b.charge_efficiency), ("discharge", b.discharge_efficiency)):
        if not (0 < eff <= 1):
            raise ValueError(f"battery.{name}_efficiency must be in (0, 1]")
    if cfg.optimizer.slot_minutes <= 0 or 60 % cfg.optimizer.slot_minutes != 0:
        raise ValueError("optimizer.slot_minutes must be a positive divisor of 60")
    if cfg.control.enabled and cfg.run.dry_run:
        # Not fatal, but worth refusing the ambiguity loudly.
        raise ValueError("control.enabled is true but run.dry_run is true; pick one")
