"""Thin Home Assistant REST client.

Covers the three things the optimizer needs:
  - read a current state (and its attributes),
  - pull historical state series for training/reporting,
  - call a service (Phase 3 actuation).

Uses the REST API only; a long-lived access token is required. The WebSocket
API is intentionally avoided to keep the dependency surface small -- polling
states on the run interval is sufficient for hourly optimization.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

log = logging.getLogger(__name__)


class HAError(RuntimeError):
    pass


class HAClient:
    def __init__(self, base_url: str, token: str, verify_ssl: bool = True, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._session.get(
            f"{self.base_url}{path}", params=params, timeout=self.timeout, verify=self.verify_ssl
        )
        if resp.status_code >= 400:
            raise HAError(f"GET {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        resp = self._session.post(
            f"{self.base_url}{path}", json=payload, timeout=self.timeout, verify=self.verify_ssl
        )
        if resp.status_code >= 400:
            raise HAError(f"POST {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    # -- reads ---------------------------------------------------------------

    def ping(self) -> bool:
        return self._get("/api/")["message"] == "API running."

    def get_state(self, entity_id: str) -> dict[str, Any]:
        """Return the full state object for an entity (state + attributes)."""
        return self._get(f"/api/states/{entity_id}")

    def get_float(self, entity_id: str, default: float = 0.0) -> float:
        """Return an entity's state coerced to float, or ``default`` if unusable."""
        try:
            state = self.get_state(entity_id)["state"]
        except HAError:
            return default
        if state in (None, "", "unknown", "unavailable"):
            return default
        try:
            return float(state)
        except (TypeError, ValueError):
            return default

    def list_states(self) -> list[dict[str, Any]]:
        """All entity states -- used by the discovery script."""
        return self._get("/api/states")

    def get_history(
        self, entity_id: str, start: datetime, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return raw state-change history for one entity in [start, end].

        The response is a list of {state, last_changed} points. Callers convert
        these into an evenly-spaced series via ``resample_power_to_energy``.
        """
        params = {"filter_entity_id": entity_id, "minimal_response": "true"}
        if end is not None:
            params["end_time"] = end.isoformat()
        data = self._get(f"/api/history/period/{start.isoformat()}", params=params)
        return data[0] if data else []

    # -- writes (Phase 3) ----------------------------------------------------

    def call_service(self, domain: str, service: str, payload: dict[str, Any]) -> Any:
        """Call ``domain.service`` with ``payload`` (e.g. entity_id + value)."""
        return self._post(f"/api/services/{domain}/{service}", payload)


def history_to_series(
    points: list[dict[str, Any]], start: datetime, end: datetime, slot: timedelta
) -> list[tuple[datetime, float]]:
    """Resample step-wise HA history points onto a fixed grid of slot starts.

    Each grid slot takes the last numeric value that was in effect at the slot
    start (last-observation-carried-forward), which is the correct semantics for
    a power reading that holds until the next state change.
    """
    parsed: list[tuple[datetime, float]] = []
    for p in points:
        raw = p.get("state")
        if raw in (None, "", "unknown", "unavailable"):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        ts = datetime.fromisoformat(p["last_changed"].replace("Z", "+00:00"))
        parsed.append((ts, value))
    parsed.sort(key=lambda x: x[0])

    series: list[tuple[datetime, float]] = []
    idx = 0
    last_val = 0.0
    t = start
    while t < end:
        while idx < len(parsed) and parsed[idx][0] <= t:
            last_val = parsed[idx][1]
            idx += 1
        series.append((t, last_val))
        t += slot
    return series
