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
| `sensor.ceres_pomona_0001_alerts` | `ceres/pomona-0001/sys/alerts` | number of active conditions; attributes `alerts`, `conditions`, `critical`, `ts`, `traceparent` |
| `sensor.ceres_fleet_critical_alerts` | `ceres/sys/alerts` | number of critical conditions fleet-wide; attributes `alerts`, `units`, `traceparent` |
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
   and, since 1.3.0, `publish ceres/+/sys/alerts/ack`, `ceres/+/sys/advice/ack`
   and `ceres/sys/alerts/ack` (live rule via the admin API; the DR mirror is
   gitops `platform/mqtt/files/acl.conf`; the contract is ceres ADR-0008's ACL
   table). Without the subscribe the sensors stay `unknown`; without the
   publish the notifications still work and only the acks are refused.
2. Copy `packages/ceres_robigus.yaml` to `/config/packages/` on vesta
   (packages are included by `homeassistant: packages: !include_dir_named packages`).
3. Check configuration, reload MQTT entities + automations (or restart).
4. Verify: `sensor.ceres_robigus_status` reads `online` once Robigus has
   its sealed broker creds (gitops `landingzones/ceres`, card #293);
   `sensor.ceres_pomona_0001_alerts` shows the tower's current conditions
   (on 2026-09-12 that includes Vertumnus's `no_response_streak` block).

Adding a unit: copy the `pomona-0001` sensor and its automation, change the
id (`<name>-NNNN`, ceres ADR-0009).

## Tracing (1.3.0, ceres card #302)

Home Assistant has no OpenTelemetry integration, so it does what the tower's
firmware does for a dose: it **echoes**. Every Ceres document carries a W3C
`traceparent` while a trace is live; the sensors keep it as an attribute, and
after each notification (created or dismissed) the automation publishes a
small non-retained ack — `ceres/<unit>/sys/alerts/ack`, `…/sys/advice/ack`,
`ceres/sys/alerts/ack` — with `by`, `action`, `notification_id`, the
conditions and the echoed `traceparent`. Robigus opens a `robigus.notified`
span under the tick that raised the condition and counts
`robigus_notified_total{unit,what,by}`, so Jaeger (service `ceres-robigus`)
shows "alert published, HA notified" as one trace. With tracing off in the
Ceres zone the attribute is `null` and the acks simply carry no context.

When a `rest_command` to a Ceres API is added (none yet; the APIs are
in-cluster only), pass the same attribute as the `traceparent` HTTP header —
the API's server span joins the trace. The pattern is in the package header.
