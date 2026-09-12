# Demeter — Robigus alerts in Home Assistant

Runbook for [`packages/demeter_robigus.yaml`](packages/demeter_robigus.yaml)
(demeter card #293; design: demeter `docs/architecture.md` §8 R2, ADR-0009 §6).

## What it is

**Robigus** is Demeter's plant-health watch — one service in the `demeter`
namespace that watches every hydroponic unit and publishes each unit's active
conditions on retained MQTT `demeter/<unit_id>/sys/alerts`, and the fleet's
critical ones on `demeter/sys/alerts`. It raises what a brain cannot say
about itself (`brain_offline`, `node_offline`, `readings_stale`, `no_config`,
`actuator_loss`) and mirrors what the brain says about the tank
(`pump_not_running`, `reagent_low_*`, `dosing_unusual_*`, `light_low`,
`wtemp_high`, `ph_low`, `ec_high`). Severity `critical` = kills plants in
hours. This package only *shows and notifies*; nothing here actuates.

## Entities

| entity | source | state |
|---|---|---|
| `sensor.demeter_pomona_0001_alerts` | `demeter/pomona-0001/sys/alerts` | number of active conditions; attributes `alerts`, `conditions`, `critical`, `ts` |
| `sensor.demeter_fleet_critical_alerts` | `demeter/sys/alerts` | number of critical conditions fleet-wide; attributes `alerts`, `units` |
| `sensor.demeter_robigus_status` | `demeter/sys/status/robigus` | `online` / `offline` (Robigus's own LWT) |

Automations: a persistent notification (id `demeter_fleet_critical`) when the
fleet's critical count rises, dismissed when it reaches 0; one per-unit
notification (`demeter_pomona_0001`) refreshed on every change of the
tower's condition set, dismissed when clear. A phone push is a commented
`notify.mobile_app_…` line — name your device and uncomment.

## Install (vesta)

1. **Broker ACL:** the `homeassistant` EMQX user needs `subscribe demeter/#`
   (live rule via the admin API; the DR mirror is gitops
   `platform/mqtt/files/acl.conf`). Without it the sensors stay `unknown`.
2. Copy `packages/demeter_robigus.yaml` to `/config/packages/` on vesta
   (packages are included by `homeassistant: packages: !include_dir_named packages`).
3. Check configuration, reload MQTT entities + automations (or restart).
4. Verify: `sensor.demeter_robigus_status` reads `online` once Robigus has
   its sealed broker creds (gitops `landingzones/demeter`, card #293);
   `sensor.demeter_pomona_0001_alerts` shows the tower's current conditions
   (on 2026-09-12 that includes the brain's `no_response_streak` block).

Adding a unit: copy the `pomona-0001` sensor and its automation, change the
id (`<name>-NNNN`, demeter ADR-0009).
