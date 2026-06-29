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
- **or CLI** (from the cluster):
  ```sh
  kubectl -n influxdb exec deploy/influxdb-influxdb2 -- \
    influx auth create --org zeus --description "home-assistant" \
    --write-bucket $(influx bucket list --org zeus --name homeassistant --hide-headers | awk '{print $1}')
  ```
Put the token in HA `secrets.yaml` (never commit it):
```yaml
# secrets.yaml
influxdb_token: "<paste-the-homeassistant-scoped-token>"
```

### `configuration.yaml` block

```yaml
influxdb:
  api_version: 2
  ssl: true
  verify_ssl: false            # internal lab-CA; set true after trusting the CA on vesta
  host: influxdb.lab.local
  port: 443
  token: !secret influxdb_token
  organization: zeus
  bucket: homeassistant
  max_retries: 3               # survive brief gateway/restart blips
  precision: s
  # Keep the DB lean & useful — record measurements, skip diagnostic noise.
  include:
    domains:
      - sensor
      - binary_sensor
      - climate
      - sun
  exclude:
    entity_globs:
      - sensor.*_rssi
      - sensor.*_linkquality
      - sensor.*_uptime
      - sensor.*_last_seen
```

Apply: **Developer Tools → YAML → Check Configuration**, then **Restart**. Verify
points land:
```sh
# any HA series in the homeassistant bucket in the last 10m?
curl -sk -H "Authorization: Token <token>" \
  "https://influxdb.lab.local/api/v2/query?org=zeus" \
  -H 'Content-Type: application/vnd.flux' \
  --data 'from(bucket:"homeassistant") |> range(start:-10m) |> limit(n:5)'
```

---

## 2. Recorder stopped 2026-06-22 — diagnosis & fix

The recorder is independent of the InfluxDB integration; HA needs it for the UI
History/Logbook/Statistics. It silently stops on errors. Diagnose on the host
(SSH/Terminal add-on or **Settings → System → Logs**):

### Check, in order
1. **Logs** around 06-22: search `recorder`. Tell-tale lines:
   - `sqlite3.OperationalError: database or disk is full` → **disk full**
   - `database disk image is malformed` / `disk I/O error` → **DB corruption**
   - `The system could not validate that the database ... migrated` → **migration failure**
2. **Disk**: `df -h` — recorder dies when `/config` (or the DB partition) fills. The
   SQLite DB is `/config/home-assistant_v2.db`; check its size with `du -h`.
3. **Statistics issues**: Developer Tools → Statistics (look for "fix issue").

### Fixes
- **Disk full (most common):** free space, then bound future growth (below) and
  restart. The unbounded DB is usually the cause.
- **DB corrupted:** stop HA → rename `home-assistant_v2.db` (and `-wal`/`-shm`) →
  start HA (it recreates a fresh DB). Local history before now is lost, **but
  InfluxDB holds it going forward** once item 1 is live. Prefer restoring from a
  backup if recent.
- **Bound growth so it doesn't recur** — once InfluxDB owns long-term history, the
  recorder only needs a short window for the UI:
  ```yaml
  recorder:
    purge_keep_days: 10
    commit_interval: 5
    auto_purge: true
    exclude:
      entity_globs:
        - sensor.*_rssi
        - sensor.*_linkquality
        - sensor.*_uptime
  ```
- **Catch it next time:** add a `system_monitor` disk-use sensor + an automation
  that notifies when `/config` disk use > 85%.

### Why both items together
A disk-full recorder failure is the likely root cause; moving long-term history to
InfluxDB (item 1) **and** trimming `purge_keep_days` (item 2) keeps the SQLite DB
small so this doesn't repeat.
