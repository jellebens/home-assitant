"""Household load forecasting.

Defines a small ``LoadForecaster`` protocol and two implementations:

  - ``BaselineForecaster``: predicts each future slot as the median historical
    consumption for that (day-of-week, hour) bucket. Robust, no dependencies,
    works from day one. This is the Phase 1/2 default.
  - ``LightGBMForecaster``: a gradient-boosted model over calendar + lag
    features, enabled in Phase 4 via the ``ml`` extra. Falls back to the
    baseline if lightgbm is not installed or there is too little history.

Both consume an evenly-spaced history of (timestamp, energy_kwh_in_slot) and
produce a list of predicted kWh for the requested future slot starts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class LoadForecaster(Protocol):
    def fit(self, history: pd.Series) -> "LoadForecaster": ...
    def predict(self, slot_starts: list[datetime]) -> list[float]: ...


def _bucket(ts: datetime) -> tuple[int, int]:
    return ts.weekday(), ts.hour


class BaselineForecaster:
    """Median consumption per (weekday, hour) bucket."""

    def __init__(self) -> None:
        self._by_bucket: dict[tuple[int, int], float] = {}
        self._by_hour: dict[int, float] = {}
        self._global: float = 0.0

    def fit(self, history: pd.Series) -> "BaselineForecaster":
        if history.empty:
            log.warning("BaselineForecaster.fit got empty history; predicting zeros")
            return self
        idx = pd.DatetimeIndex(history.index)
        df = pd.DataFrame({"value": history.to_numpy()}, index=idx)
        df["weekday"] = idx.weekday
        df["hour"] = idx.hour
        self._global = float(df["value"].median())
        self._by_hour = df.groupby("hour")["value"].median().to_dict()
        self._by_bucket = (
            df.groupby(["weekday", "hour"])["value"].median().to_dict()
        )
        return self

    def predict(self, slot_starts: list[datetime]) -> list[float]:
        out = []
        for ts in slot_starts:
            key = _bucket(ts)
            if key in self._by_bucket:
                out.append(float(self._by_bucket[key]))
            elif ts.hour in self._by_hour:
                out.append(float(self._by_hour[ts.hour]))
            else:
                out.append(self._global)
        return out


class LightGBMForecaster:
    """Gradient-boosted load model. Lazily imports lightgbm so the dependency
    is only needed when this model is actually selected."""

    def __init__(self) -> None:
        self._model = None
        self._fallback = BaselineForecaster()

    def fit(self, history: pd.Series) -> "LightGBMForecaster":
        self._fallback.fit(history)
        try:
            import lightgbm as lgb
        except ImportError:
            log.warning("lightgbm not installed; LightGBMForecaster falls back to baseline")
            return self
        if len(history) < 24 * 14:  # need at least ~2 weeks of hourly data
            log.warning("insufficient history for lightgbm (%d rows); using baseline", len(history))
            return self
        x, y = self._features(pd.DatetimeIndex(history.index), history.to_numpy())
        self._model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31)
        self._model.fit(x, y)
        return self

    def predict(self, slot_starts: list[datetime]) -> list[float]:
        if self._model is None:
            return self._fallback.predict(slot_starts)
        x, _ = self._features(pd.DatetimeIndex(slot_starts), None)
        preds = self._model.predict(x)
        return [max(0.0, float(p)) for p in preds]

    @staticmethod
    def _features(index: pd.DatetimeIndex, y: np.ndarray | None):
        feat = pd.DataFrame(index=index)
        feat["hour"] = index.hour
        feat["weekday"] = index.weekday
        feat["is_weekend"] = (index.weekday >= 5).astype(int)
        feat["month"] = index.month
        feat["hour_sin"] = np.sin(2 * np.pi * index.hour / 24)
        feat["hour_cos"] = np.cos(2 * np.pi * index.hour / 24)
        return feat, y


def build_forecaster(model: str) -> LoadForecaster:
    if model == "lightgbm":
        return LightGBMForecaster()
    return BaselineForecaster()


def power_history_to_energy(
    series: list[tuple[datetime, float]], slot: timedelta, power_unit_w: bool = True
) -> pd.Series:
    """Convert a slot grid of average power readings into energy-per-slot (kWh).

    ``series`` is the LOCF-resampled output of ``ha_client.history_to_series``.
    Power is assumed in watts (the HA default) unless ``power_unit_w`` is False.
    """
    if not series:
        return pd.Series(dtype=float)
    hours = slot.total_seconds() / 3600.0
    factor = (1.0 / 1000.0 if power_unit_w else 1.0) * hours
    index = [ts for ts, _ in series]
    values = [max(0.0, v) * factor for _, v in series]
    return pd.Series(values, index=pd.DatetimeIndex(index))
