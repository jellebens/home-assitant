# Bluetti Battery Optimizer

Price-aware charge/discharge optimizer for the Bluetti (Buzzbrick) home battery.
It forecasts household consumption, optimizes a charge/discharge schedule against
day-ahead electricity prices, optionally actuates the battery, and reports the
euros saved back into Home Assistant.

> Anker is out of scope; this project targets the Bluetti only.

## How it works

```
HA history / prices ─▶ forecaster ─▶ optimizer (LP) ─▶ controller (Phase 3)
                                          │
                                          └▶ reporter ─▶ HA MQTT sensors + reports/
```

- **forecaster** — predicts house load per hour. Default is a robust
  hour-of-week median baseline; an optional LightGBM model (`pip install
  '.[ml]'`) is available for Phase 4.
- **optimizer** — a linear program (PuLP/CBC) that minimizes grid cost over a
  36-hour horizon subject to power limits, SoC bounds, and round-trip
  efficiency. Charges when cheap, discharges when expensive.
- **controller** — Phase 3 actuation with safety guards. Disabled by default.
- **reporter** — realized savings = (no-battery baseline cost) − (actual cost),
  published as HA MQTT-discovery sensors and written to `reports/`.

## Phased rollout

| Phase | What runs | Battery control |
|-------|-----------|-----------------|
| 0 | `zeus-discover` | none (read-only probe) |
| 1 | reporting | none |
| 2 | optimizer (advisory schedule) | none |
| 3 | closed-loop control | yes, gated on a control path |
| 4 | LightGBM forecasting + backtest | yes |

## Setup

```bash
pip install -e '.[dev]'          # add ,ml for LightGBM
cp config.example.yaml config.yaml
# fill in HA token, MQTT creds, battery specs, entity IDs
export HA_TOKEN=... MQTT_USER=... MQTT_PASS=...
```

### Phase 0 — discover your setup

```bash
python -m zeus.discover --config config.yaml
```

Writes `DISCOVERY.md`: which Bluetti entities are writable (control path),
whether your price sensor exposes a forecast, and whether recorder history is
available. Use it to finish filling in `config.yaml` (especially `control.*` and
`prices.*`).

### Run

```bash
zeus --config config.yaml --once   # single cycle
zeus --config config.yaml          # loop on run.interval_minutes
```

`run.dry_run: true` (the default) computes and reports but never commands the
battery. Flip it to `false` and set `control.enabled: true` only after Phase 0
confirms a control path.

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t zeus .
docker run --rm -v "$PWD/config.yaml:/config/config.yaml" -v "$PWD/reports:/app/reports" \
  -e HA_TOKEN -e MQTT_USER -e MQTT_PASS zeus --once
```

## Kubernetes / GitOps

A Helm chart and an Argo CD `Application` example live in [`deploy/`](deploy/).
The chart renders `config.yaml` into a ConfigMap, injects secrets from a
Kubernetes Secret, and runs the loop as a single `Deployment`. See
[deploy/README.md](deploy/README.md).

## Configuration

All tunables live in `config.yaml` (see `config.example.yaml` for the annotated
template). The most important section is `battery:` — the optimizer treats those
power and SoC numbers as hard constraints, so get them right for your unit.
