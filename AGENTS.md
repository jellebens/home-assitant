# AGENTS.md

This repository stores Home Assistant operations docs and YAML templates for battery economics.

**Package versioning (owner rule, 2026-09-03):** every file under `packages/`
carries a `# version: x.y.z` header with a short history. Bump it on EVERY
change that gets applied to vesta — patch for fixes, minor for features — and
add a history line. The repo does not sync to vesta by itself; deploy with
`scripts/deploy.sh [package]` (scp to `/config/packages`, config check on
vesta, reload — card #299), which prints the git and vesta headers side by
side. The header is how you tell which behavior is actually live:
`scripts/deploy.sh --check` before debugging anything.

## Project Map

- Main stabilization docs:
  - [7-day-home-assistant-stabilization-checklist.md](7-day-home-assistant-stabilization-checklist.md)
  - [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)
  - [home-assistant-stabilization-daily-log-template.md](home-assistant-stabilization-daily-log-template.md)
- Battery economics retirement notice (package removed; zeus is source of truth):
  - [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md)
- BLE to MQTT prototype script:
  - [anker_ble.py](anker_ble.py)
- ESPHome config:
  - [anker.yaml](anker.yaml)
- Fluvius cloud integration (UI-configured on vesta, NOT in this repo; the
  `peak_power` entity feeds the LIVE jupiter lar's capacity guard):
  - [fluvius.md](fluvius.md)
- Jupiter-sourced battery-savings sensor (replaces the zeus MQTT-discovery
  `sensor.zeus_battery_savings_today` ahead of the zeus decommission #169):
  - [jupiter-savings-sensor.md](jupiter-savings-sensor.md) — runbook
  - [templates/jupiter_savings_sensor.yaml](templates/jupiter_savings_sensor.yaml) — drop-in package
- Bluetti telemetry self-heal (auto-reloads the Bluetti cloud integration when
  its battery telemetry freezes stale-but-present, so a transient blip can't
  wedge it for hours — #212):
  - [bluetti-selfheal.md](bluetti-selfheal.md) — runbook
  - [packages/bluetti_selfheal.yaml](packages/bluetti_selfheal.yaml) — drop-in package
- Ceres — Robigus plant-health alerts + advice as HA sensors + notifications (one
  source of every hydroponic unit's conditions; ceres cards #293/#294), and the
  trace through HA (ceres #302, ADR-0013): every sensor keeps the document's
  `traceparent`, every notification is acknowledged on `…/sys/alerts/ack` /
  `…/sys/advice/ack` with the rendered title + message, so Jaeger shows
  "alert → HA notified" as one trace (package 1.4.0; the `homeassistant` broker
  user needs publish on the three ack topics):
  - [ceres-robigus.md](ceres-robigus.md) - runbook
  - [packages/ceres_robigus.yaml](packages/ceres_robigus.yaml) - drop-in package
- Pomona tower pump + grow-light scheduling (first automation in the Pomona
  project; control lives in HA smart plugs, deliberately NOT in the GIGA
  firmware, which reboots for OTA):
  - [pomona-schedule.md](pomona-schedule.md) - runbook
  - [packages/pomona_schedule.yaml](packages/pomona_schedule.yaml) - drop-in package (2.0.0: the v2 wire `ceres/pomona-0001/…`, ceres #295)
  - [packages/pomona_telemetry.yaml](packages/pomona_telemetry.yaml) - tower
    telemetry into HA over MQTT (no firmware change needed - the GIGA already
    publishes) plus the level interlock; note the probe is a TOP-UP gauge and
    is blind below 8.2 L, so this is not true dry-run protection
- Bluetti battery optimizer (price-aware charge/discharge + ML + savings reporting):
  - [zeus/](zeus/) — standalone Python service; see its [README.md](zeus/README.md)

## How To Work In This Repo

- Treat this as a config/documentation repo; there is no build system, package manager, or automated test suite in-tree.
- Keep edits narrowly scoped. Do not rename Home Assistant entities unless the user asks for a coordinated migration.
- When changing template sensors, preserve consistency across:
  - sensor names and unique IDs
  - setup instructions in [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md)
- Prefer updating existing markdown docs over adding new overlapping documentation.

### Template Sensor Patterns

All Home Assistant template sensors follow this structure:
```yaml
template:
  - sensor:
      - name: Sensor Display Name
        unique_id: entity_slug_format
        unit_of_measurement: <unit>
        state_class: measurement|total|total_increasing
        availability: >
          {{ states('sensor.required_entity') not in ['unknown', 'unavailable'] }}
        state: >
          {% set var = states('sensor.entity') | float(0) %}
          {{ (calculation) | round(2) }}
```

Key conventions:
- `unique_id` uses snake_case without prefixes (Home Assistant auto-prefixes with "sensor.")
- `availability` checks both 'unknown' and 'unavailable' states
- `state_class` must match the sensor's data type (use 'measurement' for rates, 'total' for accumulated values)
- All state values are templated with fallback `| float(0)` to prevent errors

### Entity Naming Conventions

Device-specific entities use device aliases:
- **Buzzbrick**: `buzzbrick_*` (physical Bluetti device sensors from the Bluetti integration, e.g. grid/AC power). The `buzzbrick_*` economics template package was retired — see [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md).
- **Anker**: `anker_*` (BLE/MQTT integration, anker_ble.py, anker.yaml)
- **Market Price**: `current_electricity_market_price`

When adding new device templates, follow this pattern: use a short device identifier with snake_case sensor names.

## Validation Expectations

- For YAML edits, verify structure and indentation carefully (2-space indentation is used in current YAML files).
- For Home Assistant template changes, ensure each referenced entity exists or is clearly documented as required input.
- If you modify battery economics entities, verify setup docs still reference valid entity IDs.

## Security And Secrets

- Do not expose or rotate credentials unless explicitly requested.
- Treat values in [anker.yaml](anker.yaml) as sensitive configuration.

## Stabilization Process

The repository includes a 7-day structured stabilization process for Home Assistant instances:
- **Daily workflow**: [7-day-home-assistant-stabilization-checklist.md](7-day-home-assistant-stabilization-checklist.md)
- **Daily logging template**: [home-assistant-stabilization-daily-log-template.md](home-assistant-stabilization-daily-log-template.md)
- **MCP prompt pack**: [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)

Use the prompts with Home Assistant MCP server for entity discovery, availability analysis, and remediation planning.

## Battery Economics (retired)

The Buzzbrick `bluetti_battery_economics.yaml` package was removed in commit
`7177749`; its economics sensors diverged from zeus and are no longer used.
Battery economics now live entirely in [zeus/](zeus/) and its Grafana dashboard.
See [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md) for
the retirement notice and the physical sensors that remain.

## Related Docs

- Operational prompt pack: [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)
- Battery setup walkthrough: [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md)