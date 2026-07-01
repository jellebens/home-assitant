# Buzzbrick Battery Economics — RETIRED

> **This package has been retired.** The `bluetti_battery_economics.yaml`
> template package (and its Bluetti HA dashboards) was removed in commit
> `7177749`. Its economics sensors —
> `sensor.buzzbrick_charge_cost_*`, `sensor.buzzbrick_discharge_savings_*`,
> `sensor.buzzbrick_net_savings_today`, and the `binary_sensor.buzzbrick_mode_*`
> helpers — were the pre-zeus economics model and **diverged from zeus**
> (opposite-sign daily savings observed same day). They no longer exist.
>
> **Source of truth for battery economics is now [zeus](../zeus/README.md)**
> and its Grafana dashboard (`zeus_battery_savings_today` et al.). Do not
> recreate the buzzbrick economics sensors, and do not point any dashboard at
> them.

## Physical Bluetti sensors (still live)

The raw Bluetti device sensors are provided by the Bluetti integration, not by
this repo. These remain the physical throughput source and are unaffected:

- `sensor.buzzbrick_ap3002532000565690_grid_input_power` — grid charging power (W)
- `sensor.buzzbrick_ap3002532000565690_alternating_current_out_power` — AC output power (W)

These feed InfluxDB (see [influxdb-and-recorder.md](../influxdb-and-recorder.md)).
