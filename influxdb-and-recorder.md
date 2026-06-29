# Home Assistant → InfluxDB + recorder remediation

Two related operational items for the HA instance on **vesta.local (192.168.50.18)**:

1. **Wire HA → InfluxDB** so HA dual-writes sensor history to the durable store
   (the `homeassistant` bucket). This is phase 3 of zeus
   [ADR-0009](https://github.com/jellebens/zeus) and lets the forecaster eventually
   drop its self-grown `load_history.csv`.
2. **Fix the recorder**, which stopped writing on **2026-06-22** (HA history has no
   samples after that date).

> These changes are applied **on the HA host** (`/config/configuration.yaml`,
> `secrets.yaml`), not in a cluster repo. This doc is the runbook.

---

## 1. HA → InfluxDB integration

### Endpoint (already in place, verified 2026-06-29)

- URL: **`https://influxdb.lab.local`** → gateway VIP `192.168.50.200`
  (`platform`/`.config/lab/gateway.yaml`, listener `influxdb-https` :443, TLS
  terminate → backend `influxdb-influxdb2:80`).
- `/health` → `ready for queries and writes`, InfluxDB **v2.7.4**.
- **org `zeus`**, **bucket `homeassistant`** (created by `platform/influxdb-config`).
- The cert is issued by the internal **lab-ca-issuer**, so a LAN host doesn't trust
  it by default (`curl` → `ssl_verify=20`). Use `verify_ssl: false`, **or** install
  the lab CA on vesta and set `verify_ssl: true`.

### Token (do NOT reuse the admin token)

Create a dedicated token scoped to **write** the `homeassistant` bucket:

- **InfluxDB UI:** open `https://influxdb.lab.local` → log in (admin creds from the
  `influxdb-auth` secret) → **Load Data → API Tokens → Generate → Custom API
  token** → Write access to bucket `homeassistant` → copy the token once.
- **or CLI** (from the cluster — InfluxDB runs as a StatefulSet, pod
  `influxdb-influxdb2-0`; the `homeassistant` bucket id is `5b0f1ad2efcb99f5`):
  ```sh
  ADMIN=$(kubectl -n influxdb get secret influxdb-auth -o jsonpath='{.data.admin-token}' | base64 -d)
  kubectl -n influxdb exec influxdb-influxdb2-0 -- \
    influx auth create --org zeus --write-bucket 5b0f1ad2efcb99f5 \
    --description "home-assistant" --token "$ADMIN" --json
  ```
  (creates a **write-only** token scoped to the `homeassistant` bucket)
Put the token in HA `secrets.yaml` (never commit it):
```yaml
# secrets.yaml
influxdb_token: "<paste-the-homeassistant-scoped-token>"
```

### Set it up via the **UI config flow** — NOT YAML

This HA version **deprecates the YAML `influxdb:` connection block** — it tries to
import it into a config entry and, in our case, the import failed with *"could not
connect"* because the import path does **not honor `verify_ssl: false`** against the
internal lab-CA (even though `curl -sk https://influxdb.lab.local/health` succeeds
from vesta). Don't fight the YAML; use the UI flow, which has a working SSL toggle:

1. **Settings → Devices & Services → + Add Integration → "InfluxDB"**, then enter:
   - Version **2**, Host `influxdb.lab.local`, Port **443**
   - SSL **on**, **Verify SSL certificate OFF**  ← the key bit (internal CA)
   - Token = the `home-assistant` token, Organization `zeus`, Bucket `homeassistant`
2. It tests the connection live and creates the config entry.

> `verify_ssl` true is only possible after the lab CA is trusted on vesta; off is
> fine on the LAN.

**Verified working 2026-06-29:** ~668 points / 15 min, 32 active entities/h,
including `buzzbrick_*` (Bluetti grid/AC/charge/discharge) and
`utility_room_home_energy_meter_*` (Aeotec W/kWh/V/A). Check from the cluster:
```sh
ADMIN=$(kubectl -n influxdb get secret influxdb-auth -o jsonpath='{.data.admin-token}' | base64 -d)
kubectl -n influxdb exec -i influxdb-influxdb2-0 -- influx query --org zeus --token "$ADMIN" --raw \
  'from(bucket:"homeassistant") |> range(start:-15m) |> count() |> group() |> sum()'
```

### Filtering what HA records — do NOT use a YAML `influxdb:` block

⚠️ **A connection-less `influxdb:` YAML block BREAKS the integration** on this HA
version. Adding one (even with only `include`/`exclude`) re-triggers the deprecated
YAML→config-entry import, which fails ("could not connect", since it has no
connection keys) and **disables InfluxDB writing entirely**. Observed 2026-06-29:
adding the filter block stopped all writes to the `homeassistant` bucket at 18:23
(HA itself stayed up). Fix: delete the `influxdb:` block, restart.

To filter, instead: use the integration's own options (**Settings → Devices &
Services → InfluxDB → Configure**) if it offers include/exclude, or just leave it
unfiltered — recording everything to InfluxDB is harmless. The diagnostic noise
(`*_rssi`, `average_electricity_price`) only matters for the **recorder** DB size,
which the `recorder:` block in §2c already handles.

---

## 2. Recorder — NOT stopped; three data-quality warnings (logs 25–28 Jun 2026)

The recorder is **running** — it logged warnings through **28 Jun 23:45**. The
"stopped 06-22" symptom was a misread: that was the InfluxDB *import* coverage, not
the HA recorder. Confirm by checking **Settings → History** for a long-lived entity
(e.g. battery SoC) — a continuous line past 06-22 means the recorder is fine.

Three real issues surfaced in the logs, in priority order:

### 2a. `sensor.average_electricity_price` — oversized attributes + suppressed stats
Two warnings, same sensor (the Nord Pool price sensor — its `raw_today` /
`raw_tomorrow` 15-min arrays are huge):
- *"State attributes … exceed maximum size of 16384 bytes … will not be stored"*
  (156×) — HA auto-drops the bulky attributes. Harmless to data; noisy + bloats writes.
- *"unit … (None) cannot be converted to previously compiled statistics (€/kWh) …
  long term statistics will be suppressed"* — its unit went `None` on 25 Jun, so
  price LTS stopped compiling.

Pick one:
- **Don't need recorded price history** (price is already in zeus / InfluxDB) →
  exclude it; kills both warnings:
  ```yaml
  recorder:
    exclude:
      entities:
        - sensor.average_electricity_price
  ```
- **Want price long-term statistics** → restore the unit to `€/kWh` (Settings →
  Devices & Services → Entities → `sensor.average_electricity_price` → ⚙ → Unit of
  measurement), then **Developer Tools → Statistics →** find the entity → **Fix
  issue**. The 16 KB attribute note is harmless (recorder can't drop *only*
  attributes per entity, so just ignore it).

### 2b. zwave_js energy meters negative on `total_increasing`
`sensor.home_energy_meter_gen5_electric_{consumption,production}_kwh_1` and
`sensor.utility_room_home_energy_meter_electric_{consumption,production}_kwh_1`
briefly report tiny negatives (−0.043, −0.013) → breaks `total_increasing` stats.
Known Aeotec HEM Gen5 / zwave_js quirk (signed deltas; the *production* register on a
consumption-only install dips below 0).
- zeus uses the **`_w` consumption** sensor, **not** these `_kwh_1` accumulators —
  simplest fix: **disable the unused `_kwh_1` entities** (especially *production*)
  via Settings → Entities → disable. Stops the warnings.
- If you keep them, the negatives are spurious (HA treats them as a counter reset);
  clear via Developer Tools → Statistics → Fix issue.

### 2c. Keep the DB lean (recommended regardless)
Once InfluxDB owns long-term history (item 1), the recorder only needs a short
window for the UI:
```yaml
recorder:
  purge_keep_days: 10
  commit_interval: 5
  auto_purge: true
  exclude:
    entities:
      - sensor.average_electricity_price
    entity_globs:
      - sensor.*_rssi
      - sensor.*_linkquality
      - sensor.*_uptime
```

### Generic fallback — if the recorder ever *truly* stops
Symptoms: History flat-lines for all entities. Check **Settings → System → Logs**
for `recorder`:
- `database or disk is full` → free disk; `df -h`, `du -h /config/home-assistant_v2.db`.
- `database disk image is malformed` / `disk I/O error` → stop HA, rename
  `home-assistant_v2.db` (+ `-wal`/`-shm`), start HA (recreates fresh; InfluxDB keeps
  long-term history). Prefer a backup restore if recent.
