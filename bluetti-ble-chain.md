# Bluetti Apex 300 over Bluetooth — the BLE-aware end-to-end chain (card #360)

**Status (2026-11-08): repo-only.** Two packages are changed/added here and nothing on
vesta is touched by this document; the owner deploys with `scripts/deploy.sh` (§4).
The switch to Bluetooth Control itself, the integration's behaviour in that mode and
the as-built record of 2026-11-07 are in **`bluetti-ble.md`** (card #358, its §11–11.2
are the evidence this card acts on); the self-heal package's design is in
[bluetti-selfheal.md](bluetti-selfheal.md). This file is the "§12" those two point at:
the chain in words, where each package hooks in, deploy and rollback.

Cards: #360 (this), #358 (the switch), #355 (the daily 15:00Z cloud cutoff), #357 (lar
hold policy), #217 (telemetry off the cloud), #309 (Modbus). gitops:
`landingzones/jupiter-tervuren/values.yaml` (`siteConfig.entities`,
`battery_report_ages_entity`, `ha.battery_liveness_entity`).

---

## 1. The chain, in words

```
jupiter-lar (k8s, LIVE controller; plans every 15 min, spike path faster)
   │  writes DISCHARGING / PASSTHROUGH / CHARGING
   ▼
select.apex300_working_mode                 UI template-select helper, backed by
                                            input_text.apex300_mode_internal
   │  state change  — and a time_pattern every 5 min —
   ▼
automation "Update Apex 300 Working mode"   UI-managed, vesta /config/automations.yaml,
                                            id 1771413777556. NOT in this repo.
                                            CHARGING → "Backup", DISCHARGING → "Custom",
                                            PASSTHROUGH → "Time of Use"
   │  select.select_option
   ▼
select.office_buzzbrick_ap3002532000565690_working_mode     the Bluetti integration's
                                            select (bluetti-official v1.0.5, Bluetooth
                                            Control since 2026-11-07 22:12Z)
   │  BLE write  SetCtrlWorkMode                            ◄── only while the BLE
   ▼                                                            link is up
the Apex 300
   │  next BLE poll (10 s): SOC, GridAllTotalPower, ACLoadAllTotalPower,
   │  PVAllTotalPower, SetCtrlWorkMode …  → the five entities the lar / this repo read
   ▼
readback: the Bluetti select shows the unit's mode; the lar measures the actual
mode from grid-in − AC-out (jupiter_lar_actual_mode) and reads
sensor.bluetti_report_ages / binary_sensor.bluetti_integration_alive for freshness.
```

What BLE changed in that picture (bluetti-ble.md §11.1–11.2, 2026-11-07 UTC):

| Fact | Consequence |
|---|---|
| The link drops every few minutes (on 22:13:05, off 22:15:31, on 22:18:08, off 22:20:24, on 22:27:54) and **every** Bluetti entity is `unavailable` while it is down | a `select.select_option` issued in a gap fails; a lar command in a gap was lost until the UI automation's next 5-min tick (gap closer: §2.1). The stale detector is on for the gap, the lar holds — the safe direction |
| `sensor.office_buzzbrick_ap3002532000565690_bluetooth_connected` (`sensor.` domain, `on`/`off`) **stays available** through a gap; only a config-entry reload makes it `unavailable`, and in cloud mode it does not exist | it is the one signal that tells a link gap from a reload — everything in this card keys off it (§2) |
| A link gap takes the four telemetry entities `unavailable → value`, which `bluetti_selfheal` 1.2.0 read as a reload: the push age the lar reads jumped to 581 s at 22:30Z with live values | fixed in `bluetti_selfheal` 1.3.0 (§2.2) |
| A reload in BLE mode re-runs setup, which needs the Bluetti cloud (product list, proto file, `.so` checksum); during the daily 15:00–15:06Z cutoff (#355) it **fails setup** and the entities stay missing until a later reload succeeds | the episode reload now waits a grace period for the link to come back by itself (§2.3); the reload is kept — it is the only lever that re-establishes BLE when the integration will not |
| `…grid_input_power` and `…alternating_current_out_power` alternate between the true value and 0 on consecutive polls (~18 s); SoC and the select do not | **a 0 from those two is "unknown", never "zero watts"**, for anything that reasons about them. Nothing in these two packages does; the all-zero detector is safe (needs SoC = 0 too and 2 min continuously on). The lar's spike responder is NOT safe against it (bluetti-ble.md §11.2) — a lar card, not HA |

## 2. Where each package hooks in

### 2.1 `packages/bluetti_ble.yaml` 1.0.0 — the gap closer (new)

| Piece | Entity / automation | Job |
|---|---|---|
| Link as a binary sensor | `binary_sensor.bluetti_ble_link` | `on` ⇔ the Bluetooth sensor reads `on`; `off` otherwise, never `unavailable`. Attribute `source` = `ble` (sensor readable), `reloading` (sensor `unavailable`: entry reload or failed setup), `absent` (cloud mode / no integration); `bluetooth_address`, `down_since` |
| Re-assert on link return | automation `bluetti_ble_reassert_working_mode` ("Bluetti BLE: re-assert working mode when the link returns") | trigger: the Bluetooth sensor `on` for 15 s (one 10 s poll + margin, so the Bluetti select has been re-read from the unit; no `from:`, so `unavailable → on` after a reload counts too). Condition: `select.apex300_working_mode` maps to an option (same mapping as the UI automation), the Bluetti select is readable, the option is among its `options`, and they differ. Action: one `select.select_option` + a logbook line on the Bluetti select. Worst case: the unit is told the mode it already has |
| Link down 10 min | automation `bluetti_ble_link_down_notice` | persistent notification `bluetti_ble_link_down` + logbook line when the sensor has read `off` for 10 min (self-reconnects took 2.5–7.5 min); dismissed when it reads `on` again. No reload, no control write, no phone push (the self-heal's DOWN episode pushes at 30 min if the entities stay unavailable) |

It does not duplicate or replace the UI automation: the mapping is copied from it and
**must be changed in both places or neither**. It decides no mode — `demanded` is
always what the lar last wrote. It is inert in cloud mode (the trigger entity does not
exist → the automations never fire; `bluetti_ble_link` reads `off`, `source: absent`).

### 2.2 `packages/bluetti_selfheal.yaml` 1.3.0 — reconnect ≠ reload

Only `sensor.bluetti_last_push_update` changes logic. It gains the Bluetooth sensor as a
fifth trigger, and its `last_reload_seen` attribute advances only when

- the Bluetooth sensor **itself** comes back from `unknown`/`unavailable` (a true reload,
  or an HA start), or
- one of the four telemetry entities comes back while the Bluetooth sensor is **not
  readable** — `unknown` = cloud mode or no integration (the 1.2.0 rule, unchanged, so a
  Cloud-Control rollback needs no package change), `unavailable` = the entry is
  mid-reload and the four were re-created a moment before the link sensor was.

A telemetry entity coming back while the Bluetooth sensor reads `on` or `off` is a BLE
reconnect: `last_reload_seen` stays, and the next real value change counts as a push.
The Bluetooth sensor's own on/off changes never count as a push (the push test is
restricted to the four). Net effect the lar sees: `push_s` on `sensor.bluetti_report_ages`
(→ `jupiter_lar_battery_report_ages_push_seconds`, freshness mode `enforce`) no longer
jumps at a reconnect; it still resets at every true reload exactly as in 1.2.0.

Also new, additive: attribute `ble_link` on `sensor.bluetti_report_ages` (the Bluetooth
sensor's state as the template engine sees it: `on`/`off`/`unavailable`/`unknown`) so a
REST reader can tell "link gap" from "frozen".

### 2.3 `packages/bluetti_selfheal.yaml` 1.3.0 — the reload keeps a grace period

Automation `bluetti_selfheal_reload_on_stale` gets **one more condition**: while the
Bluetooth sensor reads `off` for less than `input_number.bluetti_ble_reconnect_grace_minutes`
(floor and default **10 min**, max 60; the helper starts at its `min` like the others),
it does not reload. The periodic recheck (every 5 min at :30) brings it back, so after
the grace the reload happens exactly as before, cooldown permitting (15 min in the
first hour of an episode, 60 min after).

Why conservative in this direction: a reload 2 min into a gap would pre-empt a link the
integration re-establishes by itself, and in BLE mode a reload is a cloud round-trip —
during the 15:00Z cutoff it fails setup and turns a minutes-long gap into an outage that
lasts until the cloud is back. Why not longer or no reload at all: a reload is the only
lever that re-establishes BLE when the integration will not (and what fetches a fresh
BLE server key after the integration clears it, bluetti-ble.md §3.2). The condition
passes unchanged when the sensor is absent (cloud mode), reads `on` (a freeze with the
link up is a real freeze) or is itself `unavailable` (entry mid-reload or failed setup —
upstream #174's crash path is not retried by HA itself, so the hourly reload is what
recovers it once the cloud answers).

**Observe-first:** in the first days on BLE, compare the automation's trace times with
the Bluetooth sensor's history. If gaps regularly outlast 10 min and a reload then fixes
them, lower nothing (the floor is 10); if the integration always comes back on its own,
raise the helper to 15–20 min so fewer cloud round-trips happen in the cutoff.

### 2.4 Unchanged on purpose

- The detectors, thresholds, `bluetti_integration_alive` (the lar's liveness contract),
  the force-refresh automation (in BLE mode values change every poll, so it does not
  fire while the link is up; while it is down there are no ages, so it does not fire
  either), the episode / notification timeline.
- The UI automation "Update Apex 300 Working mode", `select.apex300_working_mode`,
  `input_text.apex300_mode_internal`. Its 5-min re-write also remains the backstop for
  the gap closer.
- The lar and its gitops values (placeholder triple, entity ids): bluetti-ble.md §11.
- No consumer of the flapping power readings was added; see the last row of §1 for
  what any future one must do.

## 3. Reading it live (Developer Tools → States / Template)

```jinja
link={{ states('sensor.office_buzzbrick_ap3002532000565690_bluetooth_connected') }}
  ble_link={{ states('binary_sensor.bluetti_ble_link') }} ({{ state_attr('binary_sensor.bluetti_ble_link','source') }}, down since {{ state_attr('binary_sensor.bluetti_ble_link','down_since') }})
demanded={{ states('select.apex300_working_mode') }}  bluetti select={{ states('select.office_buzzbrick_ap3002532000565690_working_mode') }}
push_s={{ state_attr('sensor.bluetti_report_ages','push_s') }}  last_reload_seen={{ state_attr('sensor.bluetti_last_push_update','last_reload_seen') | timestamp_custom('%H:%M:%S', true) }}
stale={{ states('binary_sensor.bluetti_telemetry_stale') }} alive={{ states('binary_sensor.bluetti_integration_alive') }} grace={{ states('input_number.bluetti_ble_reconnect_grace_minutes') }} min
```

Healthy on BLE: `link=on` most of the time; across a gap `push_s` keeps counting from
the last real change (no jump to 500+ at the reconnect); `last_reload_seen` moves only
at a reload or an HA restart; the Bluetti select equals the mapped `demanded` within
~15 s of every `link=on`. Logbook, entity `select.office_buzzbrick_…_working_mode`: a
"Bluetti BLE: link back — re-asserted …" line only when the two had drifted apart.

If the link has been `off` 10 min: the `bluetti_ble_link_down` card. Check first
whether the phone app holds a Bluetooth session with the unit (one central at a time),
then `bluetoothctl info 30:ED:A0:AC:1B:52` over the SSH add-on (read-only), then
bluetti-ble.md §7 (unit-side vs cloud-side) and §9 (a dedicated radio).

## 4. Deploy (owner step — live-prod, not done by the agent)

Two files; the lar and the UI automation are untouched. From a checkout of `main` with
the PR merged, in WSL:

```sh
cd /home/jelle/repos/home-assitant
scripts/deploy.sh --check bluetti_selfheal bluetti_ble   # expect git 1.3.0 / 1.0.0, vesta 1.2.0 / <absent>
scripts/deploy.sh bluetti_selfheal bluetti_ble           # copies both, config check + reload_all with HA_TOKEN exported
```

Without `HA_TOKEN` the script only copies; then Developer Tools → YAML → **Check
configuration**, and **restart Home Assistant** (Settings → System → Restart). A
`reload_all` is enough in principle (template, automation, input_number), but a new
package file is picked up most reliably by a restart — and a restart reloads the
Bluetti entry, which needs the cloud: **do it outside 15:00–23:00Z**, and expect the
usual 1–3 min entity gap with the lar holding PASSTHROUGH.

Afterwards (within 15 min):

- `input_number.bluetti_ble_reconnect_grace_minutes` = **10**.
- `binary_sensor.bluetti_ble_link` exists, follows the Bluetooth sensor, `source: ble`.
- `sensor.bluetti_report_ages` has `ble_link`; `sensor.bluetti_last_push_update` has
  `last_reload_seen` ≈ the restart time, and it does **not** move at the next link gap.
- Settings → Automations: "Bluetti BLE: re-assert working mode when the link returns"
  and "Bluetti BLE: notify when the link has been down for 10 min" are on. The first
  shows a run only when the selects had drifted; a trace with the condition false is the
  normal case.
- The self-heal reload automation: no run 2 min into a link gap any more; a run ≥ 10 min
  into one (if it lasts that long), as before.

## 5. Rollback

- **Remove the gap closer:** `git revert` the `bluetti_ble` commit (or delete
  `packages/bluetti_ble.yaml` on vesta: `sudo rm /config/packages/bluetti_ble.yaml` over
  the SSH add-on), then restart HA. The binary sensor and the two automations disappear;
  the chain is the 2026-11-07 one again (the UI automation's 5-min tick is the only
  retry).
- **Self-heal back to 1.2.0:** `git revert` the 1.3.0 commit and `scripts/deploy.sh
  bluetti_selfheal`. The grace helper disappears; `last_reload_seen` goes back to the
  "any come-back is a reload" rule (the push age jumps at reconnects again, as on
  2026-11-07 evening — degraded freshness, never unsafe).
- **Cloud-Control rollback of the integration** (bluetti-ble.md §6) needs **no** change
  to either package: the Bluetooth sensor disappears, `bluetti_ble.yaml` goes inert,
  1.3.0 behaves as 1.2.0.
