# Bluetti telemetry self-heal — cards #212, #214, #246

Make the Bluetti / buzzbrick **cloud** integration self-recover so a transient
DNS/network blip can't silently freeze the battery telemetry for ~44h again.

**#214 extends this** with a second freeze-mode detector for **fresh all-zeros**
(incident 2026-07-26) that the original `last_reported`-freshness logic cannot
see — it reuses the same reload automation, cooldown and retry cap. See
[§1a](#1a-the-second-incident-fresh-all-zeros--214) and
[§2a](#2a-fresh-all-zeros-detector--214).

**#246 extends this** with an owner-facing escalation: when the auto-heal has
**spent its whole reload budget** (counter cap 4) and telemetry is **still**
frozen, a persistent notification tells the owner to **power-cycle the battery**
by hand — because reloading the integration can't fix a battery/firmware hang
(e.g. the 2026-08-19 firmware crash) or a real Bluetti-cloud outage. It reuses
#212/#214's detectors + counter (no new detector). See
[§2b](#2b-owner-escalation--when-auto-heal-gives-up-246). #246 also
**re-verified the Bluetti entity IDs** after the 08-19 crash — see
[§8](#8-entity-id-re-verification-246).

The HA instance runs on **vesta.local (192.168.50.18)**, not in k8s. This repo is
**docs/runbooks/packages only and does NOT sync to vesta** — merging deploys
nothing. The deliverable is the drop-in package plus the owner apply steps below.

Package: [`packages/bluetti_selfheal.yaml`](packages/bluetti_selfheal.yaml)

---

## 1. The incident (root cause)

On **2026-07-24 ~19:00** a transient DNS/network blip (the Bluetti is a *cloud*
integration polling `gw.bluettipower.com`; consistent with the known
wireless-backhaul fragility) wedged the integration's poller. Its battery
sensors **froze for ~44h** — **stale-but-present**, they kept their last numeric
value and **never went `unavailable`**:

- `sensor.ap3002532000565690_battery_level` — SoC (%)
- `sensor.buzzbrick_ap3002532000565690_grid_input_power` — grid charging power (W)
- `sensor.buzzbrick_ap3002532000565690_alternating_current_out_power` — AC out (W)
- `sensor.buzzbrick_ap3002532000565690_photovoltaics_input_power` — PV in (W)

**DNS itself was healthy** (coredns-lab `.180` forwards and resolves
`gw.bluettipower.com` fine) — this is **not** a DNS fix. The integration cached a
dead aiohttp connector and never retried until the owner manually reloaded it.
The whole-home HEM meter and `select.apex300_working_mode` are on other paths and
stayed fine.

## 1a. The second incident — fresh all-zeros (#214)

On **2026-07-26** the same cloud integration failed a *different* way. It kept
polling normally — the coordinator re-reported every ~13 s, so `last_reported`
advanced continuously — but every reported value was **exactly 0 at once**:

- `sensor.ap3002532000565690_battery_level` (SoC) = 0
- `sensor.buzzbrick_ap3002532000565690_grid_input_power` = 0
- `sensor.buzzbrick_ap3002532000565690_alternating_current_out_power` = 0
- `sensor.buzzbrick_ap3002532000565690_photovoltaics_input_power` = 0

This is **fresh-but-wrong**, the mirror of the §1 stale-but-present freeze:

- The §1 detector keys off **`last_reported` freshness**. Here `last_reported`
  keeps advancing (the poll succeeds, it just returns zeros), so
  `binary_sensor.bluetti_telemetry_stale` stays **`off`** — the original
  self-heal **never fires**.
- A simultaneous SoC = 0, grid-in = 0, **and** AC-out = 0 is physically
  implausible for a live, charged battery in a house that always draws some
  load. It is a distinct signature we can detect on **value**, not freshness.

Why it matters even though it fail-safed this time: on 2026-07-26 the fake SoC
was 0 (≤ floor → the controller did not discharge). The dangerous mirror is a
fresh-spurious **high** SoC, which the lar-side guard in the parent card #214
handles. This HA companion covers the **all-zeros** case and reloads the wedged
integration, which is the only thing that clears it.

## 2. What the package does

| Piece | Entity | Job |
|---|---|---|
| Detector (stale) | `binary_sensor.bluetti_telemetry_stale` | `on` when the battery telemetry stops polling (frozen) |
| Detector (all-zeros, #214) | `binary_sensor.bluetti_telemetry_all_zero` | `on` when SoC + grid-in + AC-out are all present and all ~0 |
| Threshold | `input_number.bluetti_stale_threshold_minutes` (default **5 min**) | tune stale detection without editing templates |
| Auto-recover | automation `bluetti_selfheal_reload_on_stale` | reloads the Bluetti config entry (fired by **either** detector) |
| Loop guard | `input_datetime.bluetti_selfheal_last_reload` + `counter.bluetti_selfheal_reload_count` | 15-min cooldown, max 4 reloads/episode, then escalate — **shared** by both modes |
| Owner escalation (#246) | automation `bluetti_selfheal_notify_stuck` | fires a "power-cycle the battery" persistent notification when the reload budget is spent (counter cap 4) **and** telemetry is still frozen |
| Recovery reset | automation `bluetti_selfheal_reset_on_recovery` | clears the guard + notifications once **both** detectors are off |

### Freshness signal — why `last_reported`, not `last_updated`

The freeze was **stale-but-present**, so an `unavailable` check would miss it
entirely. We must detect that the integration **stopped polling**:

- The detector keys off **`last_reported`**, which advances on *every* successful
  coordinator poll even when the value is unchanged — unlike `last_updated` /
  `last_changed`, which only move when the value changes. SoC and even the power
  sensors can hold a steady value for long idle stretches while perfectly
  healthy, so keying on `last_updated` would false-positive every idle night.
  `last_reported` == "did we get a fresh poll", which is exactly the freeze.
- It takes the **minimum age across all four battery entities** (the *freshest*).
  They share one coordinator and froze at the same timestamp in the incident, so
  if even the freshest hasn't reported in > threshold, the whole integration is
  wedged. Requiring the freshest to be stale means a single-entity quirk can't
  trip a false freeze — they must **all be stale together**.
- Threshold **5 min** (default): the Bluetti cloud poll cadence is seconds, so
  5 min of no fresh poll is dozens of missed polls. The reload automation also
  requires the stale state to persist (`for: 2min`), so a blip that self-heals
  within a poll or two never triggers a reload. First reload lands ~7 min after a
  real freeze — vs the 44h manual-reload incident.

If your HA build predates `last_reported` (added 2024.8), fall back to
`last_updated` and raise the threshold well above the longest expected idle
steady-value stretch — but every current build has `last_reported`.

## 2a. Fresh all-zeros detector (#214)

`binary_sensor.bluetti_telemetry_all_zero` catches the §1a mode that the
freshness detector is blind to. It is **value-based**, not time-based:

- It is `on` only when **all three** of SoC
  (`sensor.ap3002532000565690_battery_level`), grid-in
  (`sensor.buzzbrick_ap3002532000565690_grid_input_power`) and AC-out
  (`sensor.buzzbrick_ap3002532000565690_alternating_current_out_power`) are
  **present** (not `unknown`/`unavailable`) **and** all within a small epsilon
  of 0. If any one is missing, it is `off` (we cannot assert all-zeros).
- **Solar (PV) is deliberately EXCLUDED** from the conjunction.
  `sensor.buzzbrick_ap3002532000565690_photovoltaics_input_power` is
  legitimately 0 every night, so requiring it == 0 would not discriminate a
  fault from a normal dusk — it would only add false negatives, never a true
  positive. PV is still exposed as the `photovoltaics_input_power_w_excluded`
  attribute for context/debugging, but it is not part of the trigger logic. The
  three conjuncts are also exposed as `soc_percent`, `grid_input_power_w` and
  `ac_output_power_w` attributes.
- Being value-based, it re-evaluates whenever those entities change state; it
  needs no `now()` tick. (The stale detector uses `now()` because staleness is
  time-based.)

**Why `last_reported`-freshness misses it:** in this mode the poll keeps
succeeding — `last_reported` advances every ~13 s — so the freshest-signal age
stays tiny and `binary_sensor.bluetti_telemetry_stale` never goes `on`. The
integration is "fresh" by every timing measure; it is only the *values* that are
wrong. Detecting it therefore requires inspecting the values, which is exactly
what this sensor does.

**Wiring (same guard, not a second one):** the all-zeros sensor is added as an
**additional trigger** on `bluetti_selfheal_reload_on_stale`, with the same
`for: "00:02:00"` debounce as the stale trigger. The reload condition became an
`or` of the two detectors, and the action, cooldown
(`input_datetime.bluetti_selfheal_last_reload`) and retry cap
(`counter.bluetti_selfheal_reload_count`, max 4/episode) are **reused unchanged**
— so a persistently-all-zeros cloud can no more hammer reloads than a
persistently-stale one. The recovery/reset automation now triggers on *either*
detector clearing but only resets the guard once **both** are `off`, so a reload
that fixes one mode while the other is still active does not hand the still-broken
mode a fresh, uncapped retry budget.

### Reload mechanism

The automation calls **`homeassistant.reload_config_entry`** targeted **by
entity**:

```yaml
service: homeassistant.reload_config_entry
target:
  entity_id: sensor.ap3002532000565690_battery_level
```

HA resolves that entity → its owning config entry → reloads it. **This needs no
host-side `config_entry_id`**, which is why the package is portable and can ship
from this repo unfilled. (Fallback by explicit id in §5.)

### Loop guard (so a real outage doesn't hammer reloads)

- **Cooldown:** no reload within **15 min** of the last attempt (epoch-timestamp
  compare, tz-safe).
- **Retry cap:** at most **4** reloads per freeze episode. Attempts land at
  roughly +7, +22, +37, +52 min; after the 4th, reloads pause and the owner
  escalation (§2b) fires the "power-cycle the battery" notification.
- **Reset:** when telemetry is fresh again for 2 min, the counter resets and the
  notifications clear, so the next episode starts from zero.

A transient blip self-heals on attempt 1; a genuine multi-hour Bluetti-cloud
outage escalates once and then stays quiet.

## 2b. Owner escalation — when auto-heal gives up (#246)

The self-heal only ever reloads the **HA integration**. That clears a wedged
poller, but it can do nothing about a **battery-side hang** (the 2026-08-19
Bluetti firmware crash), a locked-up unit, or a real Bluetti-cloud outage — for
those the only fix is a **human power-cycle of the battery**. So once the
auto-heal has spent its budget and telemetry is still frozen, a human needs a
heads-up.

Automation `bluetti_selfheal_notify_stuck`:

- **Condition — "reloads exhausted AND still frozen":**
  `counter.bluetti_selfheal_reload_count` at the cap (**≥ 4** — the reload action
  only increments while below 4, so it parks at 4) **and** either
  `binary_sensor.bluetti_telemetry_stale` **or**
  `binary_sensor.bluetti_telemetry_all_zero` still `on`. This is the "auto-heal
  gave up" signal — deliberately **not** noise on every lumpy poll gap: a
  transient blip self-heals on reload attempt 1 and never reaches the cap.
- **Triggers (both edge once per episode → no spam):**
  - *primary* — the counter has been parked at the cap for **5 min**
    (`numeric_state above: 3, for: 00:05:00`), i.e. the 4th reload landed and did
    not clear the freeze. The counter resets to 0 on recovery, so this can only
    edge once per episode.
  - *backstop* — either detector has been continuously `on` for **30 min**
    (still gated by the exhausted-budget condition, so it can't fire early).
- **Action:** `persistent_notification.create` (id `bluetti_telemetry_stuck`,
  title *"Bluetti telemetry STUCK — power-cycle the battery"*). Always available,
  no host config; shows in the HA UI and the companion app. The message reports
  how many reloads were tried, which freeze mode is active, the freshest signal
  age in minutes, and the action: **power-cycle the Bluetti battery**, then check
  the integration and the wireless backhaul.
- **Optional phone push:** a `notify.mobile_app_<device>` block is included
  **commented out** with a placeholder — the exact service name is host-side and
  could not be confirmed from this repo (see §8). Uncomment it on vesta and set
  your device's service (Developer Tools → Actions → type `notify.mobile_app_`
  and read the autocomplete). Because the automation edges once per episode, the
  push is one-shot — no repeat spam.
- **Dismiss:** the recovery automation (§Loop guard "Reset") dismisses
  `bluetti_telemetry_stuck` when both detectors clear, so it's one card per
  episode.

**Supersedes the old inline escalate.** #212's reload automation used to create a
generic `bluetti_selfheal_escalate` notification in its over-budget branch; that
re-fired on every ~15-min recheck tick and couldn't carry a clean one-shot push.
#246 removes it — the reload automation now simply no-ops when over budget — and
moves escalation into this dedicated automation. The recovery reset still
dismisses the legacy `bluetti_selfheal_escalate` id as a harmless no-op so any
card left on vesta from before the re-apply gets cleared.

### Notifications

Persistent notifications fire on each reload (`bluetti_selfheal`) and on the
owner escalation (`bluetti_telemetry_stuck`, §2b) — both always-available, no
host config. An optional `notify.mobile_app_<device>` push is included
**commented out** on both — uncomment and set your device's notify service on
vesta.

## 3. Apply on vesta (owner step — live-prod, not done by the agent)

1. Copy [`packages/bluetti_selfheal.yaml`](packages/bluetti_selfheal.yaml) to
   `vesta:/config/packages/bluetti_selfheal.yaml` (Samba share or the File-editor
   add-on).
2. Ensure `configuration.yaml` enables packages:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. **Verify the four entity IDs** against the live host
   (Developer Tools → States, filter `ap3002532000565690`). They are copied from
   the incident report and the existing setup docs, but confirm the exact slugs
   — a wrong slug silently drops that signal from the detector.
4. **Developer Tools → YAML → Check Configuration**, then **Restart** (or reload
   Template + Automations + the helper domains).
5. Sanity-check in Developer Tools → States:
   - `binary_sensor.bluetti_telemetry_stale` = `off`, and its
     `freshest_signal_age_seconds` attribute is small (a few seconds).
   - `binary_sensor.bluetti_telemetry_all_zero` = `off` (unless the battery is
     genuinely at 0 with no grid-in and no AC-out — check its `soc_percent`,
     `grid_input_power_w`, `ac_output_power_w` attributes show the real values).
   - Optionally test the recovery path: Developer Tools → Actions, run
     `homeassistant.reload_config_entry` on the same entity and confirm the
     sensors come back fresh.

> **#214 is OBSERVE-FIRST on the lar side, but the HA reload is active.** The
> parent card #214 ships the lar-side implausibility *guard* metric-only first;
> this HA companion, like the rest of the self-heal package, is a live reload —
> reloading a wedged cloud integration only ever *restores* telemetry, so it is
> safe to run from day one. Watch `binary_sensor.bluetti_telemetry_all_zero`
> across at least one overnight to confirm zero false positives before relying
> on it.

## 4. Verify auto-recovery once (optional, owner)

To prove the loop end-to-end without waiting for a real blip, temporarily raise
`input_number.bluetti_stale_threshold_minutes` and pull the integration's
connectivity (or stop it briefly), watch `binary_sensor.bluetti_telemetry_stale`
go `on`, and confirm the automation reloads and the counter increments. Restore
the threshold to 5 afterward.

## 5. Fallback: target by explicit `config_entry_id` (host-side value)

Targeting by entity (§2) avoids needing the id. If you prefer the explicit form
(or entity targeting is unavailable on an older HA), find the id **on the host**
and swap the reload action to use it:

- **UI:** Settings → Devices & Services → **Bluetti** → ⋮ → the `entry_id` is the
  long hex in the URL `…/config/integrations/integration/bluetti#config_entry/<ID>`,
  or use the entity's *Settings* cog → the entry it belongs to.
- **File:** `/config/.storage/core.config_entries` → find the Bluetti entry →
  its `"entry_id"`.

```yaml
service: homeassistant.reload_config_entry
data:
  entry_id: "<paste-the-bluetti-config_entry_id>"
```

> **This `config_entry_id` is a host-side value and cannot be determined from
> this repo — it must be filled in on vesta if you take the fallback path.** The
> shipped package uses entity targeting precisely so this is not required.

## 6. Interlock with card #211 (lar-side, complementary — do not double-fix)

#211 adds a lar-side Prometheus metric `jupiter_lar_battery_telemetry_stale`
plus an alert. The two are **complementary and must not both try to "fix" the
same thing**:

- **#212 (this, primary auto-recover):** reloads the *HA integration* — the root
  cause of the freeze. It is the only thing that clears a wedged poller.
- **#211 (controller failsafe):** detects staleness on the lar/controller side
  and makes the **controller** safe (e.g. holds/interlocks the battery) while the
  telemetry it depends on is stale. It does **not** reload the integration.

So: #212 restores the data; #211 keeps the controller safe until the data is
back. Neither reaches into the other's domain.

**Optional secondary trigger (disabled by default):** the automation includes a
commented `webhook` trigger (`bluetti_telemetry_stale_from_lar`). If you want
#211's Alertmanager to also poke HA (shortening time-to-reload when the lar-side
metric fires first), enable that webhook and point an Alertmanager receiver at
`https://<ha-host>/api/webhook/bluetti_telemetry_stale_from_lar`. The HA-native
detector stands alone; the webhook is purely additive.

## 7. Notes / owner decisions

- **Not git-deployable:** this repo does not sync to vesta; the live apply (§3)
  is an owner-gated step, described here, not performed by the agent.
- **Entity IDs** must be confirmed on the live host (§3.3).
- **`config_entry_id`** could not be determined from the repo — it is host-side.
  The package avoids needing it by targeting the entry via `entity_id`; the
  explicit-id path (§5) is a documented fallback only.
- **Naming:** `buzzbrick_*` here refers only to the existing physical Bluetti
  device sensors — this package references them, it does not reintroduce any
  retired `buzzbrick_*` economics entities.

## 8. Entity-ID re-verification (#246)

The **2026-08-19 Bluetti firmware crash + integration reload** raised the worry
that HA could have re-created the Bluetti entities under **new IDs**, which would
silently break both these detectors and the jupiter-lar reads. #246 re-checked
the IDs.

**Configured Bluetti / battery entity IDs (unchanged — still the ones this
package and the lar use):**

| Role | Entity ID |
|---|---|
| SoC | `sensor.ap3002532000565690_battery_level` |
| grid-in | `sensor.buzzbrick_ap3002532000565690_grid_input_power` |
| AC-out (house load) | `sensor.buzzbrick_ap3002532000565690_alternating_current_out_power` |
| PV-in (solar) | `sensor.buzzbrick_ap3002532000565690_photovoltaics_input_power` |
| working-mode control | `select.apex300_working_mode` |
| whole-home import | `sensor.utility_room_home_energy_meter_electric_consumption_w` |
| capacity peak (Fluvius) | `sensor.fluvius_meter_1sag1100121989_peak_power` |
| office A/C power | `sensor.office_a_c_power` |

**Evidence they did NOT change:**

- **lar read-health (Prometheus, 2026-08-26):** the lar's SoC read works
  (SoC recovered to ~51 %) and 24 h HA read-error rates are **low** (SoC ~0.6 %,
  grid low). A *changed* entity ID would fail ~**100 %** of reads, not ~0.6 % —
  so the IDs the lar is configured with still resolve. The self-heal detectors
  read the **same** IDs, so they resolve too.
- Home Assistant's entity **registry keys entities by a stable unique_id**, and a
  firmware crash + integration *reload* (not a delete/re-add of the config entry)
  re-uses the existing registry entries — it does not mint new object IDs.

**What could NOT be confirmed here, and why (flagged for owner spot-check):**
the sanctioned HA access for this agent is **Assist/MCP only**, and none of the
Bluetti/energy/Fluvius/working-mode entities are **exposed to Assist** (only a
couple of Office climate entities are). Per-entity live confirmation via the
sanctioned tools was therefore **not possible**, and dumping `/api/states` or
extracting the HA token is **out of policy** (a prior attempt tripped the
security classifier). So this verification rests on the **indirect** read-health
evidence above, which is strong but not a per-entity string match.

**Owner spot-check (2 min, do once):** Developer Tools → States, filter
`ap3002532000565690` and confirm the four Bluetti IDs above still exist; then
confirm `select.apex300_working_mode`,
`sensor.utility_room_home_energy_meter_electric_consumption_w`,
`sensor.fluvius_meter_1sag1100121989_peak_power` and `sensor.office_a_c_power`.
If **any** differs, update it in **all three** places, consistently:

1. this package (`packages/bluetti_selfheal.yaml`) — the stale + all-zero
   detectors;
2. the lar config — gitops `landingzones/jupiter-tervuren/values.yaml`
   `siteConfig.entities` (**separate gitops PR**, not this repo);
3. the Grafana dashboards (tracked separately under #245).
