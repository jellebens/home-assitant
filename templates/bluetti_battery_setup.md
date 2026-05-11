# Buzzbrick Battery Economics Setup

## 1. Current entity mapping

The package is currently wired to these entities:

- `sensor.buzzbrick_ap3002532000565690_grid_input_power`
  Buzzbrick charging power from the grid in watts.
- `sensor.buzzbrick_ap3002532000565690_alternating_current_out_power`
  Buzzbrick AC output power in watts.
- `sensor.current_electricity_market_price`
  Current import market price in EUR per kWh.

If you later want to use a different tariff sensor, update the template references and `unit_of_measurement` fields together.

## 2. Include the package in Home Assistant

If you already use packages:

```yaml
homeassistant:
  packages: !include_dir_named templates
```

If you already use `templates/` for something else, just make sure `bluetti_battery_economics.yaml` is included by your existing setup.

## 3. Add the dashboard card

Open a dashboard in YAML mode and paste in the contents of `templates/bluetti_battery_dashboard.yaml`.

## 4. Expected entities after reload

After reloading templates, helpers, and sensors, you should see at least:

- `sensor.buzzbrick_charge_cost_rate`
- `sensor.buzzbrick_discharge_savings_rate`
- `sensor.buzzbrick_charge_cost_total`
- `sensor.buzzbrick_discharge_savings_total`
- `sensor.buzzbrick_charge_cost_today`
- `sensor.buzzbrick_discharge_savings_today`
- `sensor.buzzbrick_net_savings_today`
- `binary_sensor.buzzbrick_mode_charging`
- `binary_sensor.buzzbrick_mode_passthrough`
- `binary_sensor.buzzbrick_mode_discharging`

## 5. Accuracy warning

Charging cost is only correct when the charging power sensor represents grid charging only.
If the Buzzbrick can charge from solar and grid at the same time, do not use a combined input power sensor for charging cost.