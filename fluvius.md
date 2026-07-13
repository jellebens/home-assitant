# Fluvius integration (cloud polling) — behavior and downstream consumers

The HA instance on **vesta.local (192.168.50.18)** runs the Fluvius integration
for the digital meter `1SAG1100121989`. It is **UI-configured** (Settings →
Devices & Services) — there is deliberately **no fluvius YAML in this repo**,
so don't go looking for a config file to fix; this doc is the reference.

## What it is

A **cloud polling** integration: it fetches meter data from the Mijn Fluvius
cloud API, it does NOT read the meter locally. Fluvius publishes meter data in
delayed batches, so the integration's entities update only a handful of times
per day.

Entities (all `sensor.fluvius_meter_1sag1100121989_*`):

- `peak_power` — the meter's **running monthly billed-peak** register (kW,
  Belgian capacity tariff). **Load-bearing:** the LIVE jupiter lar (tervuren
  battery controller) reads it every 15-min cycle as its `capacity_peak`
  input for the peak-shaving charge guard; zeus (the demoted cross-check)
  reads the same entity.
- `consumption_high_tariff`, `consumption_low_tariff`, `total_consumption`,
  `consumption_quarter_hourly`
- `injection_high_tariff`, `injection_low_tariff`, `total_injection`,
  `injection_quarter_hourly`

## Measured behavior (card #185 investigation, 2026-07-12)

From the InfluxDB `homeassistant` bucket (org `zeus`, 7-day window):

- All nine entities refresh **together, only ~6x/day**, at ~:25 past
  scattered hours — the cadence is **integration-wide**, not per-entity.
- Between successful cloud refreshes the entities spend **multi-hour
  stretches `unavailable`**. Consumers polling in a gap get an unusable
  state ~50% of the time (measured: the lar's 15-min reads failed ~2/hr on
  average, in bursts of 4/hr).
- This is **inherent** to the cloud integration + Fluvius's delayed batch
  publication. It is not a vesta/recorder/template problem and there is
  nothing in this repo to fix.

## Consumer guidance

- Any automation/template reading `fluvius_*` MUST tolerate
  `unavailable`/`unknown` (the repo's standard `availability:` guard) and
  should hold last-good rather than treating a gap as data.
- The jupiter lar does exactly that (month-peak LOCF guard, jupiter card
  #180) and a sustained hard-down (>~10h of failed reads) alerts via
  `JupiterLarCapacityPeakReadsFailing` — shipped in the gitops repo,
  `landingzones/jupiter-tervuren/templates/prometheusrule.yaml`, with the
  full root-cause write-up in that landing zone's README (card #185).
- If the entities are unavailable for **days**, check the integration's
  cloud login/token on vesta (Settings → Devices & Services → Fluvius) —
  that is the failure mode that actually needs a human.
