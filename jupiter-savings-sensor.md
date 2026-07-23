# Jupiter-sourced battery savings sensor (replacing zeus) — card #166

Moves Home Assistant's daily battery-savings entity **off zeus and onto
jupiter**, the authoritative independent savings source, ahead of the zeus
decommission (**#169, ~2026-08-06**). After that date the zeus service stops
and its sensor goes stale; this replacement keeps the HA-side savings figure
live.

The HA instance runs on **vesta.local (192.168.50.18)**, not in k8s.

Companion file: [`templates/jupiter_savings_sensor.yaml`](templates/jupiter_savings_sensor.yaml)
(the drop-in package).

---

## 1. What the old entity actually is (finding)

`sensor.zeus_battery_savings_today` is **not git-managed anywhere** — not in
this repo, not as a template/helper on the host. It is **published to HA by the
zeus service via MQTT discovery** (base topic `zeus`; see the zeus landing-zone
README "MQTT / Home Assistant"). The cluster-side zeus pod publishes discovery
configs to `mqtt.lab.local`, which the **cluster→vesta MQTT bridge**
(`bridge-jupiter.conf`, see gitops `docs/jupiter-bridge-vesta.md`) forwards to
vesta's Mosquitto, where HA's MQTT integration materialises the entity.

Consequence: there is **no HA config file to edit** to change its source, and
the entity **disappears on its own when zeus is decommissioned** — nothing in
HA "deletes" it. So this card *adds* a parallel jupiter-fed entity rather than
rewiring the old one.

## 2. Source chosen: InfluxDB `jupiter_daily_savings` — and why

Jupiter's savings number is published two ways (both from the central
reporting-service, `source=independent`):

| Source | Metric | Reachable from vesta? |
|---|---|---|
| Prometheus | `jupiter_savings_today_eur{site_id="tervuren"}` | **No** — Prometheus has no ingress (`observability.yaml`: `ingress.enabled: false`); it is cluster-internal only. |
| reporting-service `/metrics` | same gauge | **No** — ClusterIP + ingress-only NetworkPolicy; no LB/host. |
| **InfluxDB** | **`jupiter_daily_savings`** (measurement, `zeus` bucket, `site_id="tervuren"`) | **Yes** — HA already reaches `https://influxdb.lab.local` (proven in `influxdb-and-recorder.md`, verify_ssl off). |

**InfluxDB is the only jupiter source HA can actually reach**, and it is also
the most robust: the value is already written durably by the reporting-service
on its ~60s in-process timer, and it survives zeus's decommission (jupiter keeps
writing it). That is the pick.

The two jupiter numbers agree by construction (same realized computation);
today both read **≈ €0.75**. The InfluxDB series is the running intraday value,
so `last()` tracks the same "savings so far today" that
`zeus_battery_savings_today` showed.

### Ideal long-term alternative (out of scope, needs a jupiter change)

The *cleanest* parity with how zeus does it would be for the reporting-service
to publish an **MQTT discovery** savings sensor (bridged to vesta like zeus's),
so HA materialises it with zero host config. That is a jupiter-side change (the
`reporting` EMQX user is currently subscribe-only) and is **not a hestia/HA
task** — noted here for the record.

## 3. Token / secret (owner step — live-prod)

The existing HA `homeassistant` InfluxDB token is **write-only to the
`homeassistant` bucket** and cannot read `zeus`. Mint a read-scoped token and
put it in HA `secrets.yaml`:

```sh
# From the cluster (zeus bucket id is discoverable; org is `zeus`):
ADMIN=$(kubectl -n influxdb get secret influxdb-auth -o jsonpath='{.data.admin-token}' | base64 -d)
ZEUS_BUCKET=$(kubectl -n influxdb exec influxdb-influxdb2-0 -- \
  influx bucket list --org zeus --token "$ADMIN" --json | jq -r '.[]|select(.name=="zeus")|.id')
kubectl -n influxdb exec influxdb-influxdb2-0 -- \
  influx auth create --org zeus --read-bucket "$ZEUS_BUCKET" \
  --description "home-assistant-read-zeus" --token "$ADMIN" --json
```

```yaml
# vesta:/config/secrets.yaml   (never commit this)
influxdb_zeus_read_token: "<paste-the-read-only-zeus-token>"
```

## 4. Deploy path to vesta (there is NO auto-deploy)

This repo is **docs/runbooks only** and does **not** sync to the vesta host.
Merging to `main` does **not** deploy anything (unlike the k8s Argo flow).
HA config changes are applied **by hand on vesta** — the same pattern as
`influxdb-and-recorder.md` and `fluvius.md`. To apply this card:

1. Add the read token to `secrets.yaml` (§3).
2. Copy [`templates/jupiter_savings_sensor.yaml`](templates/jupiter_savings_sensor.yaml)
   to `vesta:/config/packages/jupiter_savings_sensor.yaml` (via the Samba share
   or the File-editor add-on), and make sure `configuration.yaml` has:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
   (or paste the `sensor:` + `template:` blocks into `configuration.yaml`).
3. **Developer Tools → YAML → Check Configuration**, then **Restart**.
4. Confirm InfluxDB history still writes after the restart (the recorder-doc
   landmine is the *top-level* `influxdb:` key, which this does not add — but
   verify anyway).

This is a **live-prod mutation and an owner-gated step**; it is described here,
not performed by the agent.

## 5. Validation (must match jupiter ≈ €0.75 today)

- From the cluster, read the same point the sensor reads:
  ```sh
  ADMIN=$(kubectl -n influxdb get secret influxdb-auth -o jsonpath='{.data.admin-token}' | base64 -d)
  kubectl -n influxdb exec -i influxdb-influxdb2-0 -- influx query --org zeus --token "$ADMIN" --raw '
    from(bucket:"zeus") |> range(start:-26h)
      |> filter(fn:(r)=>r._measurement=="jupiter_daily_savings" and r.site_id=="tervuren")
      |> last()'
  ```
  Also confirm the field name (expected `value`) — if it differs, fix the
  `_field` filter in the package's Flux query.
- In HA: **Developer Tools → States →** `sensor.jupiter_battery_savings_today`
  should read the same number (± a rounding step) as
  `sensor.zeus_battery_savings_today`, and both should track
  `jupiter_savings_today_eur` (€0.75 today).
- Let the two run **in parallel for a soak window** and diff daily; they read
  the same realized behavior and should agree.

## 6. Consumers of `zeus_battery_savings_today` + removal plan

Known consumers (none are inside this repo):

- **Grafana** `home-energy-ha.json` — two panels ("Battery savings today (zeus —
  source of truth)") read `entity_id="zeus_battery_savings_today"`, `_field="value"`
  from the `homeassistant` bucket (HA's own recorder path). Once the new sensor
  runs, HA's recorder also writes `sensor.jupiter_battery_savings_today` to that
  bucket, so these panels can be repointed. (Dashboard migration is **#165**.)
- **Kiosk** savings tile (HA dashboard) — migrates under **#165**.
- **HA automations** — none known, but enumerate on the live host (Settings →
  Automations, search `zeus_battery_savings`) before retiring the old entity.

**Removal plan (do NOT delete in this change):**

1. **Now (this card):** add `sensor.jupiter_battery_savings_today` in parallel;
   old entity untouched.
2. **Soak:** verify the two agree over a window.
3. **#165:** repoint the kiosk tile and the two Grafana panels to the new sensor.
4. **#169 (~08-06):** zeus is decommissioned → `sensor.zeus_battery_savings_today`
   goes unavailable on its own (it is MQTT-discovery-owned by zeus; there is
   nothing to delete on the HA side).

## 7. Deviations / flags for the owner

- **Branching:** the card's GitFlow instruction (branch off `develop`, PR into
  `develop`) does not fit this repo — `home-assitant` has **no `develop`/`master`
  branch; its trunk is `main`** and CI gates PRs into `main` (GitHub-flow, same
  as card #185). This work is branched off `main` and PR'd into `main`.
- **Not git-deployable:** the actual sensor cannot be "shipped" by this repo —
  it must be applied on the vesta host (§4). This PR delivers the ready-to-apply
  package + runbook; the live apply, the InfluxDB read token, and the field-name
  check are owner steps.
- **Field name** for `jupiter_daily_savings` (`_field`) is assumed `value` and
  should be confirmed once (§5).
