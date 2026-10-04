# Bluetti telemetry self-heal — cards #212, #214, #246, #259, #306

Make the Bluetti / buzzbrick **cloud** integration self-recover so a transient
DNS/network blip can't silently freeze the battery telemetry for ~44h again.

**Package 1.1.0 (#306, 2026-10-04)** is the current behaviour, and
[§2d](#2d-package-110--what-the-2026-09-12-incident-showed-306) is the place to
start: the detection matrix, the reload and notification timeline, the
`sensor.bluetti_report_ages` sensor, deploy and post-deploy checks. Where an older
section below disagrees with §2d (the 5-minute threshold, the cap of 4 reloads,
the once-per-episode notification), §2d is right — those sections are marked.

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

- `sensor.office_buzzbrick_battery_level` — SoC (%)
- `sensor.office_buzzbrick_ap3002532000565690_grid_input_power` — grid charging power (W)
- `sensor.office_buzzbrick_ap3002532000565690_alternating_current_out_power` — AC out (W)
- `sensor.office_buzzbrick_ap3002532000565690_photovoltaics_input_power` — PV in (W)

**DNS itself was healthy** (coredns-lab `.180` forwards and resolves
`gw.bluettipower.com` fine) — this is **not** a DNS fix. The integration cached a
dead aiohttp connector and never retried until the owner manually reloaded it.
The whole-home HEM meter and `select.apex300_working_mode` are on other paths and
stayed fine.

## 1a. The second incident — fresh all-zeros (#214)

On **2026-07-26** the same cloud integration failed a *different* way. It kept
polling normally — the coordinator re-reported every ~13 s, so `last_reported`
advanced continuously — but every reported value was **exactly 0 at once**:

- `sensor.office_buzzbrick_battery_level` (SoC) = 0
- `sensor.office_buzzbrick_ap3002532000565690_grid_input_power` = 0
- `sensor.office_buzzbrick_ap3002532000565690_alternating_current_out_power` = 0
- `sensor.office_buzzbrick_ap3002532000565690_photovoltaics_input_power` = 0

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

As of package **1.1.0**:

| Piece | Entity | Job |
|---|---|---|
| Detector (stale) | `binary_sensor.bluetti_telemetry_stale` | `on` when no battery entity has **reported** for longer than the threshold, or none is available |
| Detector (all-zeros, #214) | `binary_sensor.bluetti_telemetry_all_zero` | `on` when SoC + grid-in + AC-out are all present and all ~0 |
| Detector (SoC-zero, #306) | `binary_sensor.bluetti_telemetry_soc_zero` | `on` when SoC reads exactly 0 — notification only, see §2d |
| Detector (partial freeze, #306) | `binary_sensor.bluetti_telemetry_partial_freeze` | `on` when one of SoC / grid-in / AC-out stopped reporting while another entity still reports — **observe-first**, see §2d |
| Enforce switch (#306) | `input_boolean.bluetti_partial_freeze_enforce` (default **off**) | `on` = a partial freeze counts as stale |
| Threshold | `input_number.bluetti_stale_threshold_minutes` (floor and default **10 min**) | tune stale detection without editing templates |
| LAR liveness (#259) | `binary_sensor.bluetti_integration_alive` | `on` ⇔ not stale and not all-zero; its `heartbeat` attribute is load-bearing (§2c) |
| True report ages (#306) | `sensor.bluetti_report_ages` | per-entity `last_reported` / `last_updated` age in seconds, readable over REST |
| Episode (#306) | `binary_sensor.bluetti_selfheal_episode` + `input_datetime.bluetti_selfheal_episode_start` | `on` = not alive, or SoC-zero, for 2 min; `off` = good again for 12 min |
| Auto-recover | automation `bluetti_selfheal_reload_on_stale` | reloads the Bluetti config entry while stale or all-zero — never stops |
| Keep REST fresh (#259) | automation `bluetti_force_refresh_values` | reloads the entry when no value changed for 10 min |
| Reload budget | `input_datetime.bluetti_selfheal_last_reload` (stamped by **both** reload automations) + `counter.bluetti_selfheal_reload_count` (informational) | at most one reload per 15 min from all automations together |
| Owner escalation (#246, #306) | automation `bluetti_selfheal_notify_stuck` + `input_datetime.bluetti_selfheal_last_notify` | persistent notification **and phone push** 30 min into an episode, then every 2 h, with the duration |
| Recovery reset | automation `bluetti_selfheal_reset_on_recovery` | when the episode ends: resets the counter, clears the notifications, sends "recovered" if the owner had been told |

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
- Threshold **10 min** (floor and default since 1.1.0). The original text here
  said "5 min, the poll cadence is seconds". Neither held on vesta: the helper
  has no `initial`, so it started at its `min` of **1 min**, and the archive of
  this sensor's `freshest_signal_age_seconds` shows the freshest entity reports
  once every **300 s** when nothing changes. A 1-minute threshold under a
  5-minute cadence made the detector flap all day (§2d). The helper's `min` is
  now 10 and the templates floor it at 10 as well. The reload automation also
  requires the stale state to persist (`for: 2min`), so the first reload lands
  ~12 min after a real freeze — vs the 44h manual-reload incident.

If your HA build predates `last_reported` (added 2024.8), fall back to
`last_updated` and raise the threshold well above the longest expected idle
steady-value stretch — but every current build has `last_reported`.

## 2a. Fresh all-zeros detector (#214)

`binary_sensor.bluetti_telemetry_all_zero` catches the §1a mode that the
freshness detector is blind to. It is **value-based**, not time-based:

- It is `on` only when **all three** of SoC
  (`sensor.office_buzzbrick_battery_level`), grid-in
  (`sensor.office_buzzbrick_ap3002532000565690_grid_input_power`) and AC-out
  (`sensor.office_buzzbrick_ap3002532000565690_alternating_current_out_power`) are
  **present** (not `unknown`/`unavailable`) **and** all within a small epsilon
  of 0. If any one is missing, it is `off` (we cannot assert all-zeros).
- **Solar (PV) is deliberately EXCLUDED** from the conjunction.
  `sensor.office_buzzbrick_ap3002532000565690_photovoltaics_input_power` is
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

> **1.1.0:** the wiring below still holds for the triggers and the `or`
> condition. The retry cap of 4 and the "both detectors off" reset it mentions
> are gone — see "Loop guard" further down and §2d.

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
  entity_id: sensor.office_buzzbrick_battery_level
```

HA resolves that entity → its owning config entry → reloads it. **This needs no
host-side `config_entry_id`**, which is why the package is portable and can ship
from this repo unfilled. (Fallback by explicit id in §5.)

### Loop guard (so a real outage doesn't hammer reloads) — 1.1.0

- **One budget for every reload.** Both reload automations stamp
  `input_datetime.bluetti_selfheal_last_reload`, and the episode automation
  honours the stamp whoever wrote it: **at most one reload of the Bluetti config
  entry per 15 minutes, from all automations together.** (Until 1.1.0 the two
  fired independently, often in the same second.)
- **Fast phase:** in the first hour of an episode the cooldown is **15 min** —
  about 4 attempts.
- **Slow phase:** after the first hour the cooldown is **60 min**, and it
  **never stops** while the freeze lasts. The old cap of 4 went quiet for good:
  on 2026-09-13 it was reached at 00:25 UTC and the automation did nothing for
  the remaining 20 h.
- **Reset:** when the episode ends (`binary_sensor.bluetti_selfheal_episode`
  goes off: good again for 12 min) the counter resets and the notifications
  clear. 12 min, not 2: a reload re-creates the entities, so the stale detector
  is off for one threshold after every reload whether it helped or not;
  "recovered" has to outlast that.

A transient blip self-heals on attempt 1; an outage that reloads cannot fix is
reloaded at a bounded rate for as long as it lasts, and the owner is told (§2b).

## 2b. Owner escalation (#246, reworked in 1.1.0 by #306)

> **1.1.0:** the trigger and the repeat described in the bullets below are the
> 1.0.0 design and no longer apply. The automation now goes by the **duration of
> the episode**: a persistent notification **and a phone push**
> (`notify.mobile_app_grey_red_beard`, normal priority) 30–35 min into an
> episode, again every 2 h for as long as it lasts, each with the duration in
> the title ("Bluetti telemetry DOWN for 2.5 h"), and a "recovered after …" push
> at the end. Why: §2d.

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

Persistent notifications fire on each reload by the episode automation
(`bluetti_selfheal`) and on the owner escalation (`bluetti_telemetry_stuck`,
§2b) — both always-available, no host config. Since 1.1.0 the escalation and the
recovery also push to the phone through `notify.mobile_app_grey_red_beard` (the
device `ceres_robigus` 1.5.0 already uses), with `continue_on_error` so a
missing service cannot break the automation. The per-reload notification stays
persistent-only.

## 2c. LAR liveness signal + force-refresh (#259, 2026-08-31)

Two additions that close the **lar idle-deadlock**: the lar (jupiter-cell) reads
HA over REST `/api/states`, and HA only REWRITES a state object (bumping the
REST-visible `last_updated`, and — because the REST payload is served from a
cached dict — the REST-visible `last_reported` too) when the **value changes**.
An idle battery holds constant values for hours, so over REST the whole feed
looks frozen; the lar's #211 staleness guard (900 s) then suppressed valid
charge plans into a passthrough hold, and because holding keeps the values
constant, the hold never cleared (deadlock; incidents 2026-08-30/31).

**`binary_sensor.bluetti_integration_alive`** — the HA-side liveness verdict the
lar consumes (jupiter ≥ 0.18.4, `ha.battery_liveness_entity`): `on` ⇔ NOT stale
(§2) AND NOT all-zero (§2a); `off` on any freeze or when a detector is itself
unknown/unavailable (strict positive confirmation — the lar keeps its hold on
any doubt). Because the §2 stale detector computes `last_reported` age in a
**template** (the template engine sees the true ~13 s heartbeat REST hides),
this sensor genuinely discriminates idle-but-live from dead. Its `heartbeat`
attribute is `now()`-driven and changes every minute **on purpose**: the lar's
`battery_liveness_max_age_seconds` gate (300 s) reads THIS entity's REST
`last_updated`, which would itself freeze while the sensor sits constant `on` —
the churning attribute forces a fresh state write ~every 60 s so the gate
passes while HA's template engine is healthy, and refuses (hold stands) if the
engine wedges. Do not remove it.

**`bluetti_force_refresh_values`** (automation) — the blunt instrument (owner,
2026-08-31): every 5 min, if the freshest battery entity's REST value has sat
unchanged **> 10 min** (well under the lar's 900 s guard), reload the Bluetti
config entry. A reload recreates the entities ⇒ fresh state writes ⇒ fresh REST
timestamps — so the lar guard can never trip on idle, dashboards stay current,
and a genuinely wedged poller gets kicked as a bonus. Post-reload the ages
reset, which is the cooldown (~1 reload / 10 idle minutes max). All-unavailable
(hard-down) is deliberately excluded — that stays §2's capped episode logic.

Defense-in-depth order on the lar side (gitops `jupiter-tervuren/values.yaml`):
force-refresh keeps REST fresh → liveness override clears a false stale →
`battery_stale_max_hold_seconds` (interim blind timer, revert to 0 once the
above two are proven) → #211 hold as the final safety.

**1.1.0 (#306):** both pieces are kept. The force-refresh condition is unchanged;
it now stamps `input_datetime.bluetti_selfheal_last_reload` after its reload so
the episode automation does not reload on top of it. The alive sensor's template
is unchanged, but it inherits the corrected stale threshold: until 1.1.0 it was
`off` about two thirds of the time on a working integration (§2d).

## 2d. Package 1.1.0 — what the 2026-09-12 incident showed (#306)

Everything in this section is read from the InfluxDB archive of Home Assistant
(bucket `homeassistant`, through Grafana, read-only) — the package's own
sensors, counter and automations are in it. Times are **UTC**.

### The incident, as Home Assistant recorded it

| Time (UTC) | What the integration served | What the package did |
|---|---|---|
| 09-12 from ≤ 18:00 | values change **only at a reload** (two writes per entity per reload) | reloads ~8 an hour: force-refresh every 15 min, the episode automation on a flapping stale detector |
| 09-12 ~22:50 | **SoC 0**, grid-in 654 W, AC-out 653 W, the same at every reload | nothing: not all-zero (two of three non-zero), not stale. No detector saw it for 4 h 20 min |
| 09-13 00:25:01 | same | the reload counter reaches its cap of 4 (it had stopped being reset); the episode automation stops reloading |
| 09-13 00:30:01 | same | `bluetti_selfheal_notify_stuck` fires — **once**, a persistent notification. It was the flapping *stale* detector that satisfied its condition; the all-zero detector was off |
| 09-13 ~03:10 | **SoC 0, grid-in 0, AC-out 0** | `bluetti_telemetry_all_zero` on (off for ~1.5 s at each reload); `bluetti_integration_alive` off |
| 09-13 03:10 → 21:00 | all zeros | force-refresh reloads every 15 min (86 in the whole incident); each one re-creates the entities with a cached 51 % / 2008 W / 607 W for ~130 ms and then gets zeros again. Nothing else: no reload from the episode automation, no second notification |
| 09-13 21:01 | — | the archive goes dark until 09-15 ~12:30 (no HA entity wrote anything, including the minutely alive heartbeat); the end of the incident is not in it |

So: the notification fired, once, 1 h 40 min in, where nobody looked, and never
again. 86 reloads did not help, because a reload was not the cure — every fresh
fetch returned the same zeros. (Card #306 assumed the zeros were re-stamped
every ~30 s and so never tripped the force-refresh. The record says otherwise:
the zeros were constant values and the force-refresh fired every 15 min
throughout.)

### What was wrong in 1.0.0 (four separate things)

1. **The stale threshold was 1 minute, the report cadence is 300 s.**
   `input_number.bluetti_stale_threshold_minutes` has no `initial`, so it started
   at its `min` (1), not at the documented 5. `freshest_signal_age_seconds`
   climbs 1 → 61 → 121 → 181 → 241 and resets, around the clock. Result on
   2026-10-03: stale `on` 62–71 % of the time, `bluetti_integration_alive` `on`
   only 29–38 % of the time, and the episode automation reloading on a false
   freeze ~90 times a day. The #246 notification fired 13 more times between
   09-18 and 10-04 for the same reason.
2. **SoC 0 with power flowing was invisible** (the first 4 h 20 min).
3. **The escalation fired once and its backstop could not fire**: it needed a
   detector continuously `on` for 30 min, and every reload takes the entities
   away for a second.
4. **The cap of 4 never reset**: the reset needed the stale detector `off` for
   2 min, which a flapping detector rarely gives.

### Detection matrix (1.1.0)

| Mode | Looks like | Signal that catches it | Reload | Owner told |
|---|---|---|---|---|
| Stale (#212) | values present, no entity reports | `bluetti_telemetry_stale` (MIN `last_reported` age > 10 min) | yes | yes, if it lasts through the reloads |
| Hard down | every entity unavailable | `bluetti_telemetry_stale` (no ages at all) | yes | yes |
| All-zero (#214) | SoC, grid-in, AC-out all 0 | `bluetti_telemetry_all_zero` | yes | yes |
| SoC-zero (#306) | SoC 0, power non-zero | `bluetti_telemetry_soc_zero` | no (did not help on 09-12; the force-refresh still runs) | yes |
| Partial freeze (#306) | one of SoC / grid-in / AC-out silent, another entity reporting | `bluetti_telemetry_partial_freeze` (MAX `last_reported` age over those three > 10 min) | only with `bluetti_partial_freeze_enforce` on | only with enforce on |
| Reports, but values only change at a reload | `last_reported` advances every 300 s, `last_updated` only at reloads | **nothing** — read `min_updated_s` on `sensor.bluetti_report_ages` | force-refresh every 15 min (which is the only thing delivering data) | no |

The last row is not hypothetical: it is the state of the integration **since
about 2026-09-18** and on 2026-10-04. On 2026-10-03 between 13:00 and 13:40,
during a charge, SoC went 67 → 70 → 72 and each of those values arrived at a
reload (13:00, 13:05, 13:20, 13:35) — nothing in between. A healthy day
(2026-09-17) has ~1900 AC-out writes; these days have ~300. The lar is being fed
one sample per reload. This package cannot tell that state from a battery that
is idle, and reloading does not cure it; it is a separate problem (owner /
upstream integration), listed in the PR as the first follow-up.

### Partial freeze — why it only observes

The stale detector takes the MIN age, so one live entity masks three frozen
ones. Flipping MIN to MAX `last_updated` would be wrong: "value unchanged" is
true of PV all night and of grid-in for a whole steady charge, and it would
reload around the clock. The right signal is the MAX **`last_reported`** age
over the entities that are *expected to keep reporting*.

Which entities those are is the open point. PV is out (it reads 0 in every
sample of the archive; if the integration only writes on change it never writes
at all). AC-out is in (it changes ~every 45 s on a healthy day). SoC and grid-in
are in because they are what the lar steers on — but whether the integration
re-reports an unchanged SoC or grid-in cannot be read from the archive: InfluxDB
only receives value changes, and the one archived `last_reported` number is the
MIN over all four. So the detector computes its verdict and does nothing with it
until `input_boolean.bluetti_partial_freeze_enforce` is turned on.

**To decide (owner, after a day and a night on 1.1.0):** look at
`sensor.bluetti_report_ages` history. If `soc_s`, `grid_input_s` and `ac_out_s`
all stay under 600 while things are fine, turn the switch on. If one of them
climbs past 600 with nothing wrong (the partial-freeze sensor will be `on`),
that entity is not "expected to report": take it out of the `expected` list in
the package instead.

### `sensor.bluetti_report_ages` — how to read it

REST shows a cache-frozen `last_reported` and only moves `last_updated` when a
value changes, so from outside HA "constant" and "frozen" are the same. This
sensor publishes what the template engine sees, once a minute:

| Attribute | Meaning |
|---|---|
| `soc_s`, `grid_input_s`, `ac_out_s`, `pv_input_s` | seconds since that entity last **reported** (wrote its state, changed or not); `null` = unavailable |
| `min_s`, `max_s` | freshest / oldest report over the available entities; the state of the sensor is `max_s` |
| `expected_max_s` | oldest report over SoC, grid-in, AC-out — what the partial-freeze detector compares to the threshold |
| `soc_updated_s`, `grid_input_updated_s`, `ac_out_updated_s`, `pv_input_updated_s` | seconds since that entity's **value last changed** (what REST shows) |
| `min_updated_s` | freshest value change — what the force-refresh compares to 600 s |
| `available` | how many of the four entities are available (0 = hard down) |
| `as_of` | the minute the ages were computed |

- **Is this sensor itself fresh?** `as_of` changes every minute, so its REST
  `last_updated` moves while HA's template engine works. A reader (the lar, in a
  follow-up) checks that it is under ~2 min old and then trusts the ages.
- **Healthy:** `min_s` under 300, `min_updated_s` under a minute or two.
- **Reports but no data** (the last row of the matrix): `min_s` under 300 while
  `min_updated_s` saw-tooths up to ~900 and drops only at a reload.
- **Frozen:** `min_s` over 600.
- **One entity frozen:** its `*_s` over 600 while `min_s` is small.
- **Cost:** it is trigger-based — exactly one state write a minute (1440 a day),
  never one per Bluetti state change — and has no `state_class`, so no
  long-term statistics. It does land in the recorder and in InfluxDB like the
  stale and alive sensors already do every minute. To keep it out of the
  recorder, add it to `recorder: exclude: entities:` in vesta's
  `configuration.yaml` (a package cannot carry a second `recorder:` block); keep
  it in InfluxDB, that history is the point.

### Reload and notification timeline (1.1.0)

For an episode that starts at T (the first minute a detector is on):

| When | What |
|---|---|
| T + 2 min | episode `on`; first reload, unless something reloaded in the last 15 min |
| first hour | a reload whenever 15 min have passed since the last one (any automation) |
| T + 32…37 min | first notification: persistent + phone, "DOWN for 3x min" |
| after 1 h | the episode automation retries hourly; the force-refresh keeps its own 15-min rhythm while values are constant |
| every 2 h | the notification repeats with the new duration (the phone push replaces the previous one) |
| recovery + 12 min | episode `off`: counter reset, notifications dismissed, "recovered after …" push |

### Reload rate

| State of the integration | 1.0.0, measured | 1.1.0 |
|---|---|---|
| healthy, values changing (2026-09-17) | 4 a day (false stale) | ~0 |
| values constant: idle, or the "only at a reload" state (2026-10-02/03) | **~178 a day** (88 force-refresh + ~90 false stale) | **≤ 96 a day** (force-refresh only, one per 15 min) |
| outage (stale / all-zero) | 8 in the first hour, then 4 an hour | 4 an hour |

In the "only at a reload" state the reloads are also the lar's samples. Their
longest gap stays 15 min; the extra sample ~5 min after each force-refresh
reload, which the false-stale reload happened to give, goes away.

## 3. Apply on vesta (owner step — live-prod, not done by the agent)

### Deploying 1.1.0 (#306)

One file: `packages/bluetti_selfheal.yaml`. Nothing else on vesta changes.

1. From a checkout of `main` with the PR merged:
   `scripts/deploy.sh --check bluetti_selfheal` (expect git `1.1.0`, vesta
   `1.0.0`), then `scripts/deploy.sh bluetti_selfheal`. With `HA_TOKEN` exported
   it runs the config check and `homeassistant.reload_all`; without it, it only
   copies the file — then Developer Tools → YAML → **Check configuration**, and
   **All YAML configuration** reload (or restart Home Assistant).
2. A reload is enough: every domain the package touches reloads (template,
   automation, input_number, input_boolean, input_datetime, counter). If one of
   the new entities is missing afterwards, restart Home Assistant.
3. Check, in Developer Tools → States:
   - `input_number.bluetti_stale_threshold_minutes` = **10** (it was 1).
   - `binary_sensor.bluetti_telemetry_stale` = `off` and **stays** off over
     10 minutes (it used to flip every few minutes); `threshold_seconds` = 600.
   - `binary_sensor.bluetti_integration_alive` = `on`, `heartbeat` moving every
     minute.
   - `sensor.bluetti_report_ages`: a number, `as_of` moving every minute, the
     four `*_s` and four `*_updated_s` attributes filled.
   - `binary_sensor.bluetti_telemetry_soc_zero` = `off`,
     `binary_sensor.bluetti_telemetry_partial_freeze` = on or off (it only
     observes), `input_boolean.bluetti_partial_freeze_enforce` = `off`.
   - `binary_sensor.bluetti_selfheal_episode` = `unknown` for the first 12 min,
     then `off`; when it settles, `counter.bluetti_selfheal_reload_count` goes
     to 0 and any old "STUCK" notification disappears.
4. Check the phone path once: Developer Tools → Actions →
   `notify.mobile_app_grey_red_beard` with a test message. If that service does
   not exist the automation still runs (`continue_on_error`), but nothing reaches
   the phone.
5. Paste in Developer Tools → Template to see the true ages next to the
   detectors:
   ```jinja
   {% set r = 'sensor.bluetti_report_ages' %}
   reported  soc={{ state_attr(r,'soc_s') }} grid={{ state_attr(r,'grid_input_s') }} ac={{ state_attr(r,'ac_out_s') }} pv={{ state_attr(r,'pv_input_s') }}
   updated   soc={{ state_attr(r,'soc_updated_s') }} grid={{ state_attr(r,'grid_input_updated_s') }} ac={{ state_attr(r,'ac_out_updated_s') }} pv={{ state_attr(r,'pv_input_updated_s') }}
   stale={{ states('binary_sensor.bluetti_telemetry_stale') }} partial={{ states('binary_sensor.bluetti_telemetry_partial_freeze') }} zero={{ states('binary_sensor.bluetti_telemetry_all_zero') }} soc0={{ states('binary_sensor.bluetti_telemetry_soc_zero') }} alive={{ states('binary_sensor.bluetti_integration_alive') }} episode={{ states('binary_sensor.bluetti_selfheal_episode') }}
   last reload {{ ((now().timestamp() - state_attr('input_datetime.bluetti_selfheal_last_reload','timestamp')) / 60) | round(0) }} min ago
   ```
6. Over the next day: Settings → Automations → *Bluetti self-heal: reload
   integration when telemetry frozen* should show **no** runs while things work
   (it ran ~90 times a day), and *Bluetti force-refresh* at most one run per
   15 min.
7. After a day and a night: decide on the partial-freeze switch (§2d).

To go back: `git revert` the 1.1.0 commit on `main` and run
`scripts/deploy.sh bluetti_selfheal` again (the script deploys committed files
only). The three new helpers and four new sensors disappear; the threshold
helper keeps the value 10.

### First install (#212, historical)

1. Copy [`packages/bluetti_selfheal.yaml`](packages/bluetti_selfheal.yaml) to
   `vesta:/config/packages/bluetti_selfheal.yaml` (Samba share or the File-editor
   add-on).
2. Ensure `configuration.yaml` enables packages:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. **Verify the four entity IDs** against the live host
   (Developer Tools → States, filter `office_buzzbrick`). They are copied from
   the incident report and the existing setup docs, but confirm the exact slugs
   — a wrong slug silently drops that signal from the detector.
4. **Developer Tools → YAML → Check Configuration**, then **Restart** (or reload
   Template + Automations + the helper domains).
5. Sanity-check in Developer Tools → States:
   - `binary_sensor.bluetti_telemetry_stale` = `off`, and its
     `freshest_signal_age_seconds` attribute is under ~300 (the integration
     reports at least every 300 s).
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

To prove the loop end-to-end without waiting for a real blip, pull the
integration's connectivity (or disable the config entry briefly), watch
`binary_sensor.bluetti_telemetry_stale` go `on` and
`binary_sensor.bluetti_selfheal_episode` follow 2 min later, and confirm the
automation reloads and the counter increments. Leave it down for 35 min to see
the notification and the phone push; restore it and the "recovered" push comes
12 min after the telemetry is back.

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
- **Open owner decisions from #306** (§2d): the partial-freeze switch (after a
  day of `sensor.bluetti_report_ages`); whether the phone push should be
  high-priority (it is normal priority: lost optimisation, not a safety
  problem); and the integration's "values only change at a reload" state, which
  this package can neither detect nor cure.
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
the IDs and found them unchanged by that crash.

> **UPDATE 2026-08-27 (#256): the entity IDs DID change — but from a later,
> unrelated cause.** The BuzzBrick/Apex device was moved into the HA **"Office"**
> area, which regenerated its sensor object IDs with an `office_` prefix. This is
> a device-area rename, not the 08-19 crash. The old IDs now 404 "Entity not
> found". All four references in this package's detectors were repointed to the
> new names (this card), the lar config was repointed and verified live in gitops
> #254, and the table below now lists the **current** (post-rename) IDs. The
> 08-19 read-health evidence further down remains valid for *that* event; it just
> predates this rename.

**Configured Bluetti / battery entity IDs (current — post 2026-08-27 `office_`
rename; the ones this package and the lar now use):**

| Role | Entity ID |
|---|---|
| SoC | `sensor.office_buzzbrick_battery_level` |
| grid-in | `sensor.office_buzzbrick_ap3002532000565690_grid_input_power` |
| AC-out (house load) | `sensor.office_buzzbrick_ap3002532000565690_alternating_current_out_power` |
| PV-in (solar) | `sensor.office_buzzbrick_ap3002532000565690_photovoltaics_input_power` |
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
`office_buzzbrick` and confirm the four Bluetti IDs above still exist; then
confirm `select.apex300_working_mode`,
`sensor.utility_room_home_energy_meter_electric_consumption_w`,
`sensor.fluvius_meter_1sag1100121989_peak_power` and `sensor.office_a_c_power`.
If **any** differs, update it in **all three** places, consistently:

1. this package (`packages/bluetti_selfheal.yaml`) — the stale + all-zero
   detectors;
2. the lar config — gitops `landingzones/jupiter-tervuren/values.yaml`
   `siteConfig.entities` (**separate gitops PR**, not this repo);
3. the Grafana dashboards (tracked separately under #245).
