# AGENTS.md

This repository stores Home Assistant operations docs and YAML templates for battery economics dashboards.

## Project Map

- Main stabilization docs:
  - [7-day-home-assistant-stabilization-checklist.md](7-day-home-assistant-stabilization-checklist.md)
  - [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)
  - [home-assistant-stabilization-daily-log-template.md](home-assistant-stabilization-daily-log-template.md)
- Battery package and dashboard templates:
  - [templates/bluetti_battery_economics.yaml](templates/bluetti_battery_economics.yaml)
  - [templates/bluetti_battery_dashboard.yaml](templates/bluetti_battery_dashboard.yaml)
  - [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md)
- BLE to MQTT prototype script:
  - [anker_ble.py](anker_ble.py)
- ESPHome config:
  - [anker.yaml](anker.yaml)

## How To Work In This Repo

- Treat this as a config/documentation repo; there is no build system, package manager, or automated test suite in-tree.
- Keep edits narrowly scoped. Do not rename Home Assistant entities unless the user asks for a coordinated migration.
- When changing template sensors, preserve consistency across:
  - sensor names and unique IDs
  - dashboard entity references
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
- **Buzzbrick**: `buzzbrick_*` (battery economics templates, templates/bluetti_battery_economics.yaml)
- **Anker**: `anker_*` (BLE/MQTT integration, anker_ble.py, anker.yaml)
- **Market Price**: `current_electricity_market_price` (shared across battery economics)

When adding new device templates, follow this pattern: use a short device identifier with snake_case sensor names.

## Validation Expectations

- For YAML edits, verify structure and indentation carefully (2-space indentation is used in current YAML files).
- For Home Assistant template changes, ensure each referenced entity exists or is clearly documented as required input.
- If you modify battery economics entities, verify linked dashboard cards still reference valid entity IDs.

## Security And Secrets

- Do not expose or rotate credentials unless explicitly requested.
- Treat values in [anker.yaml](anker.yaml) as sensitive configuration.

## Stabilization Process

The repository includes a 7-day structured stabilization process for Home Assistant instances:
- **Daily workflow**: [7-day-home-assistant-stabilization-checklist.md](7-day-home-assistant-stabilization-checklist.md)
- **Daily logging template**: [home-assistant-stabilization-daily-log-template.md](home-assistant-stabilization-daily-log-template.md)
- **MCP prompt pack**: [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)

Use the prompts with Home Assistant MCP server for entity discovery, availability analysis, and remediation planning.

## Battery Economics Workflow

For Buzzbrick battery integration:
1. Map required entities in [templates/bluetti_battery_economics.yaml](templates/bluetti_battery_economics.yaml)
2. Include package in Home Assistant and reload templates
3. Add dashboard card from [templates/bluetti_battery_dashboard.yaml](templates/bluetti_battery_dashboard.yaml)
4. Verify expected sensor entities appear (see setup guide for full list)
5. Monitor charging cost vs. discharge savings accuracy (see accuracy warning in setup guide)

## Related Docs

- Operational prompt pack: [home-assistant-stabilization-mcp-prompts.md](home-assistant-stabilization-mcp-prompts.md)
- Battery setup walkthrough: [templates/bluetti_battery_setup.md](templates/bluetti_battery_setup.md)