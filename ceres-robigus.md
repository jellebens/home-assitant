# Ceres — Robigus alerts in Home Assistant

Runbook for [`packages/ceres_robigus.yaml`](packages/ceres_robigus.yaml)
(ceres card #293; design: ceres `docs/architecture.md` §8 R2, ADR-0009 §6).

## What it is

**Robigus** is Ceres's plant-health watch — one service in the `ceres`
namespace that watches every hydroponic unit and publishes each unit's active
conditions on retained MQTT `ceres/<unit_id>/sys/alerts`, and the fleet's
critical ones on `ceres/sys/alerts`. It raises what Vertumnus cannot say
about itself (`vertumnus_offline`, `node_offline`, `readings_stale`, `no_config`,
`actuator_loss`) and mirrors what Vertumnus says about the tank
(`pump_not_running`, `reagent_low_*`, `dosing_unusual_*`, `light_low`,
`wtemp_high`, `ph_low`, `ec_high`). Severity `critical` = kills plants in
hours. This package only *shows and notifies*; nothing here actuates.

## Entities

| entity | source | state |
|---|---|---|
| `sensor.ceres_pomona_0001_alerts` | `ceres/pomona-0001/sys/alerts` | number of active conditions; attributes `alerts`, `conditions`, `critical`, `ts` |
| `sensor.ceres_fleet_critical_alerts` | `ceres/sys/alerts` | number of critical conditions fleet-wide; attributes `alerts`, `units` |
| `sensor.ceres_robigus_status` | `ceres/sys/status/robigus` | `online` / `offline` (Robigus's own LWT) |
| `sensor.ceres_pomona_0001_advice` | `ceres/pomona-0001/sys/advice` | number of recommendations; attributes `advice`, `kinds`, `doses` (the advise-role brain's "add x ml by hand") |

Automations: a persistent notification (id `ceres_fleet_critical`) when the
fleet's critical count rises, dismissed when it reaches 0; one per-unit
notification (`ceres_pomona_0001`) refreshed on every change of the
tower's condition set, dismissed when clear. A third notification
(`ceres_pomona_0001_advice`) lists Robigus's recommendations (1.1.0, ceres
#294): a plant that does not fit the unit's targets, the suggested compromise,
a hand dose Vertumnus asks for in the `advise` role. A phone push is a commented
`notify.mobile_app_…` line — name your device and uncomment.

## Install (vesta)

1. **Broker ACL:** the `homeassistant` EMQX user needs `subscribe ceres/#`
   (live rule via the admin API; the DR mirror is gitops
   `platform/mqtt/files/acl.conf`). Without it the sensors stay `unknown`.
2. Copy `packages/ceres_robigus.yaml` to `/config/packages/` on vesta
   (packages are included by `homeassistant: packages: !include_dir_named packages`).
3. Check configuration, reload MQTT entities + automations (or restart).
4. Verify: `sensor.ceres_robigus_status` reads `online` once Robigus has
   its sealed broker creds (gitops `landingzones/ceres`, card #293);
   `sensor.ceres_pomona_0001_alerts` shows the tower's current conditions
   (on 2026-09-12 that includes Vertumnus's `no_response_streak` block).

Adding a unit: copy the `pomona-0001` sensor and its automation, change the
id (`<name>-NNNN`, ceres ADR-0009).
