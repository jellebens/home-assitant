# Bluetti Apex 300 over Bluetooth — feasibility and switch runbook (cards #358 → #217)

**Status (2026-11-07): feasibility DONE, verdict FEASIBLE on the hardware vesta already
has. The switch itself is OWNER-GATED and NOT done.** Nothing on vesta was changed for
this document; every read below was read-only (SSH add-on, `bluetoothctl`, `sudo jq`
on `.storage`, no token or key ever printed).

Why: card #355 ([gitops `docs/soaks/2026-11-07-bluetti-daily-cloud-cutoff.md`](https://github.com/jellebens/gitops/blob/master/docs/soaks/2026-11-07-bluetti-daily-cloud-cutoff.md))
showed the Bluetti **cloud** stops pushing the unit's data at **15:00–15:06Z every day**
(and again 18:07–19:30Z), 2–8 h a time. The lar (`jupiter-tervuren`, the LIVE battery
controller) then holds PASSTHROUGH on last-good SoC and loses the evening-peak
discharge. The installed integration already has a **Bluetooth control mode** that reads
the unit directly over BLE. This document answers "can vesta do that?" and lays out the
switch as a runbook — because the lar reads four Home Assistant entities every 15 s and
a switch that renames or drops them for minutes becomes a stale hold (card #259 history).

Related: [bluetti-selfheal.md](bluetti-selfheal.md) (the cloud-mode self-heal package,
the #319 hand patch), [patches/bluetti-1.0.5-ws-handler-both-shapes.patch](patches/bluetti-1.0.5-ws-handler-both-shapes.patch),
gitops `landingzones/jupiter-tervuren/values.yaml` (`siteConfig.entities`,
`ha.battery_placeholder_signatures`). Cards: #358 (this experiment), #217 (telemetry
off the cloud), #357 (lar hold policy), #309 (Modbus, blocked on firmware).

---

## 1. Verdict

| Question | Answer | Evidence (§2) |
|---|---|---|
| Does vesta have a Bluetooth adapter? | **Yes.** vesta is a Raspberry Pi 5 (HAOS, kernel `6.18.39-haos-raspi`, aarch64) with the onboard `hci0` (`bcm43438-bt`, controller `2C:CF:67:70:B2:C8`), powered on, and Home Assistant's **Bluetooth integration already owns it** (config entry "Raspberry Pi (Trading) Ltd bcm43438-bt"). | §2.1 |
| Can vesta see the Apex 300 over BLE? | **Yes, strongly.** A 30 s scan found `AP3002532000565690` at `30:ED:A0:AC:1B:52`, **RSSI −55 dBm**, service `0000ff00-…` (the Bluetti GATT service), manufacturer data `BLUETTF` (= encrypted-link capable, what the integration expects). The advertised name equals the cloud SN, which is exactly the integration's auto-match rule. | §2.2 |
| Is the Apex 300 a BLE-supported model in v1.0.5? | **Yes.** Model `AP300-AP300` → `OakVersatileV2Device` (`SUPPORTED_MODELS = {"EL300,AORA300","AP300,AP300V2","AP200"}`). | §2.3 |
| Is the BLE decoder library available for vesta? | **Yes.** The integration downloads `bluetti_ble_linux_aarch64_314_musl.so` (2.96 MB, 2026-09-11, checksum-listed) from `download.bluetti.app` at first BLE start; vesta's tag is `linux_aarch64_314_musl` (HA 2026.11.0, CPython 3.14, musl). The dependency libs (`libcpsrt.so`, mbedTLS 3.6.4) are already in `ble/lib/`. Upstream marks aarch64-musl on Python 3.14 "untested". | §2.4 |
| Do the lar's entity ids survive the switch? | **Not automatically — this is the risk.** v1.0.5 has **no reconfigure path for the control mode**: switching = **delete the config entry and add the integration again** choosing "Bluetooth Control". Deleting the entry removes the device and its entities from the registries; HA normally restores the old `entity_id`s from its deleted-entities memory when the same `unique_id`s come back (the `unique_id`s are identical in both modes), but that must be **verified and repaired by hand** in the same window (§5 step 6). `select.apex300_working_mode` is a template select and survives; the automation behind it targets the Bluetti select, which is one of the ids to verify. | §3, §5 |
| Does BLE mode still need the cloud? | **At setup/reload yes, at runtime no.** Every entry (re)load needs the OAuth token, fetches the BLE "server key" via `get_decrypt_info` when it is empty, re-downloads the device's proto file (`downloads/proto/<SN>.bin`, deleted at every unload) and checks the `.so` checksum against `download.bluetti.app`. Polling itself is local BLE only; the STOMP websocket is not even started. | §3.2 |
| Can cloud and BLE run side by side? | **Per device, no.** `control_mode` is a per-device field; with one device the switch replaces cloud mode. Two entries for the same SN are refused by the flow (`all_devices_exists`). | §3.1 |

**Recommendation:** do the switch (§5) in a daytime window **outside 15:00–23:00Z**, with
the lar watched, and keep the cloud-mode rollback (§6) at hand. Then run the 15:00Z test
(§7). No extra hardware is needed; §9 lists the fallbacks if BLE from the rack turns
out unstable.

---

## 2. Evidence (read 2026-11-07 ~19:40Z, during the day's cloud cutoff)

### 2.1 vesta's Bluetooth adapter

```
$ ls -la /sys/class/bluetooth
hci0 -> ../../devices/platform/soc@107c000000/107d50c000.serial/.../bluetooth/hci0
$ bluetoothctl list
Controller 2C:CF:67:70:B2:C8 vesta.local [default]
$ bluetoothctl show
Controller 2C:CF:67:70:B2:C8 (public)   Powered: yes   PowerState: on   Discoverable: no
$ uname -a
Linux ... 6.18.39-haos-raspi ... aarch64
```

HA config entries (`sudo jq` on `.storage/core.config_entries`, non-secret fields):

| domain | title | note |
|---|---|---|
| `bluetooth` | Raspberry Pi (Trading) Ltd bcm43438-bt (2C:CF:67:70:B2:C8) | source `integration_discovery` — HA's own scanner is on this adapter |
| `bluetti` | BLUETTI Power Integration | options `{"devices":["AP3002532000565690"]}` only — **no** `control_mode`, `device_mapping` or `ble_setting` = cloud mode |
| `bluetti_modbus` | — | the community Modbus integration (v3.4.0) was **installed 2026-11-07 19:54 local**, no config entry yet — #309, not this card |

### 2.2 The Apex 300 over the air

30 s read-only scan from the SSH add-on (`bluetoothctl --timeout 30 scan on`), then
`bluetoothctl info 30:ED:A0:AC:1B:52`:

```
Device 30:ED:A0:AC:1B:52 (public)
    Name: AP3002532000565690
    UUID: Unknown (0000ff00-0000-1000-8000-00805f9b34fb)
    ManufacturerData.Key: 0x4c42   Value: 42 4c 55 45 54 54 46  "BLUETTF"
    ManufacturerData.Key: 0x0f06   Value: f0 02 06 00 81 ... (rolling)
    RSSI: -55
    Paired: no  Connected: no
```

−55 dBm from the rack is a strong link (the integration will connect from the first
attempt; −80 and below is where BLE gets flaky). The scan also listed the washer,
dryer, the Samsung TV and the owner's PC — the usual household noise, nothing that
shares the Bluetti service UUID.

### 2.3 What the integration does in BLE mode (v1.0.5 source on vesta)

Files read: `__init__.py`, `oauth.py` (the config flow lives here, `config_flow.py` only
imports the client credential), `models.py` (`read_data_from_ble`, `update_from_bluetooth`,
`check_ble_server_key`, `asyc_start_down_proto`), `sensor.py`, `ble/coordinator.py`,
`ble/device_reader_v2.py`, `ble/ble_decoder.py`, `ble/lib/bluetti_lib_loader.py`,
`ble/utils/device_builder.py`, `ble/devices/**`, `const.py`, `manifest.json`.

- **Model support**: `build_device_v2` takes the last `-` part of the cloud model
  (`AP300-AP300` → `AP300`) and matches `OakVersatileV2Device.SUPPORTED_MODELS`. The flow's
  `is_device_support()` only checks that the platform tag can be built — it does not look
  at the model at all.
- **Polling**: `PollingCoordinator` (`DataUpdateCoordinator`, default interval **10 s**,
  persistent connection, timeout 120 s, 5 retries) → `BluettiDevice.read_data_from_ble()`
  → `DeviceReaderV2.read_data()`: a 10 s `BleakScanner.discover` (to see whether the
  `BLUETTF` flag is present → encrypted link), connect, `start_notify` on `ff01`, the
  encrypted handshake through the downloaded `.so` (`crypt_link` with the server key),
  then one read command per state the cloud snapshot knows (`SOC`, `GridAllTotalPower`,
  `ACLoadAllTotalPower`, `PVAllTotalPower`, `DCLoadAllTotalPower`, `SetCtrlWorkMode`,
  `ChgFullTime`, `DsgFullTime`, the switches) plus `sChargingStatus`. The same
  `fnCode`s as the cloud → the same `BluettiState` objects → the same entities.
- **Entities**: `unique_id = f"{sn}_{fnCode}"` in both modes (`AP3002532000565690_SOC`,
  `…_GridAllTotalPower`, `…_ACLoadAllTotalPower`, `…_SetCtrlWorkMode`, …). BLE mode adds
  one entity, `binary_sensor.<device> Bluetooth Connected` (`unique_id
  AP3002532000565690_bluetooth_connected`, attribute `bluetooth_address`), and may add
  states the cloud does not have (`sChargingStatus`, `remoteSet`…) as `ble_state`
  entries without entities.
- **Availability**: in BLE mode `device.online` = *BLE client connected*. While the link
  is down the entities read **`unavailable`** (cloud mode keeps serving the last value
  and the reload placeholder). For the lar that is the *safe* direction: an
  `unavailable` state is a failed read → freshness hold, not a wrong number.
- **Control**: `set_state_value` in BLE mode writes over BLE
  (`_async_send_write_command`, `SetCtrlWorkMode` mapped 1/2/4/5 ↔ `workmode_3/0/1/2`).
  **The lar's working-mode actuation goes this way too** (`select.apex300_working_mode`
  → automation "Update Apex 300 Working mode" → `select.office_buzzbrick_…_working_mode`
  every state change and every 5 min). After the switch, control writes leave the cloud
  as well — this is part of what the owner approves.
- **Cloud mode is switched off entirely** for a BLE device: `hasCloudControl` is false →
  no STOMP websocket; `web_socket_message_handler` ignores BLE devices; `_async_update`
  (the REST status poll) is never called for them. The #319 hand patch in `models.py`
  becomes dormant but stays in the file.

### 2.4 The BLE library

`download.bluetti.app/ha-libs/20260908/linux/SHA256SUMS` (fetched from WSL 2026-11-07):

```
ec3a93b3…c88f  bluetti_ble_linux_aarch64_314_musl.so   (HTTP 200, 2 963 989 bytes, last-modified 2026-09-11)
6a192ad6…2de  bluetti_ble_linux_aarch64_313_musl.so
```

vesta's `__pycache__` is `cpython-314`, HAOS is Alpine (musl), `platform.machine()` is
`aarch64` → the loader asks for exactly the first file. The checksum is re-verified
(a GET of `SHA256SUMS`) at **every** entry load; with the server unreachable it keeps
the local copy. `ble/lib/` on vesta today holds only the dependency libs
(`libcpsrt.so` 20 MB, `libmbedcrypto/tls/x509.so.3.6.4`) — the `.so` itself appears
on the first BLE start. Upstream v1.0.5 release notes: "Python 3.14+ (HAOS ≥ 2026.3)
… aarch64_musl untested".

---

## 3. What the switch really is

### 3.1 There is no "reconfigure to BLE" in v1.0.5

- **Reconfigure** (`async_step_reconfigure`) → `async_step_user` → the OAuth login →
  `async_oauth_create_entry` sees `entry_id` in the flow context and **only replaces the
  token and reloads**. The control-mode form is never shown.
- **Add integration again** → after OAuth, `async_step_select_devices` lists only SNs
  **not** already in any entry's `options.devices` → with the Apex already integrated
  it aborts with `all_devices_exists`.
- There is no options flow. Upstream issue
  [#156](https://github.com/bluetti-official/bluetti-home-assistant/issues/156) asks for
  exactly this per-device switch; the maintainer answered "we will implement it as soon
  as possible" (2026-09-16), nothing shipped as of v1.0.5 (still the latest release).

So the only UI path is: **Settings → Devices & services → BLUETTI → ⋮ → Delete**, then
**Add integration → BLUETTI** → OAuth → select the Apex and **"Bluetooth Control"** →
confirm mapping (`ble_polling_interval` 10 s, `ble_polling_timeout` 120 s,
`ble_max_retries` 5) → the lib download progress → entry created with
`options.device_mapping = {"30:ED:A0:AC:1B:52": "AP3002532000565690"}`.

### 3.2 What the cloud is still used for in BLE mode

| When | What | If the cloud is down at that moment |
|---|---|---|
| the add flow | OAuth login; `get_decrypt_info(sn)` → `encryptKey` (the BLE *server key*) + `protoBufFileUrl`; `download_ble_lib()` | the flow fails ("Get Ble Key Error") — do the switch while the cloud is up (daytime, not 15:00–23:00Z) |
| every entry load / reload | OAuth session; the server key is fetched again **only if empty**; the proto file `downloads/proto/<SN>.bin` is **re-downloaded every time** (unload deletes it); the `.so` checksum is re-checked | the proto download fails → `read_data_from_ble` logs "proto file not down ok" and returns `None` → entities `unavailable` until a later reload succeeds |
| key expiry | `check_ble_server_key`: when a poll returns `None` and the lib reports the key not OK, the stored key is **cleared** (at most once per 12 h) and the log says "Reset ble server key, Please reload to get new ble key" — **nothing reloads by itself** | the self-heal package's stale detectors fire on the frozen/unavailable values and reload the entry within 10–15 min, which fetches a fresh key (cloud needed then) |
| runtime polling | nothing | unaffected — this is the point |

Upstream [#174](https://github.com/bluetti-official/bluetti-home-assistant/issues/174)
("Bluetooth encryption error after a few days"): a `decrypt_info` that came back `None`
during a reload crashed `async_setup_entry`; the maintainer blamed European network
issues and stated BLE needs the internet "only for the initial startup" — the code above
says every reload. The same thread reports an **AP300 over BLE returning garbage values**
(`2461152648` alternating with 0 on DC output) — the lar's #214 plausibility guard
(`battery_implausible_enforce: false`, observe-first) is the net for that; watch
`jupiter_lar_battery_implausible_total` after the switch.

### 3.3 Entity ids: what to expect and what to check

- `BluettiSensor._attr_name = f"{device.name} {fnName}"` with `device.name = sn` — the
  registry's `original_name` today is "AP3002532000565690 Battery Level" etc., while the
  live ids carry the `office_buzzbrick_` prefix from the 2026-08-27 area move (card
  #254/#256). The device is `name_by_user` "BuzzBrick", area `office`.
- `async_remove_entry` (runs on *Delete*) explicitly removes the device and every
  entity of the entry from the registries. HA keeps removed entities in
  `deleted_entities` (and removed devices in `deleted_devices`) and **restores the old
  `entity_id`, name and area when the same `platform + unique_id` is registered again**
  — the registry on vesta currently has 0 deleted Bluetti entities, so the restore will
  come from this deletion. Treat it as *expected*, not *guaranteed*: step 6 of §5
  verifies the four ids and renames them back if needed, inside the same window.
- The **template select `select.apex300_working_mode`** (UI helper over
  `input_text.apex300_mode_internal`) and the automation "Update Apex 300 Working mode"
  are not Bluetti entities and survive untouched; the automation's target
  `select.office_buzzbrick_ap3002532000565690_working_mode` is the fifth id to verify.
  (`sensor.apex300_battery_soc`, referenced by two old price-range automations, does not
  exist today either — pre-existing, not part of this change.)
- The **self-heal package** targets the entry *by entity*
  (`homeassistant.reload_config_entry` → `sensor.office_buzzbrick_battery_level`) and
  reads the same four ids in its detectors — once the ids are right, it keeps working
  without a package change.

### 3.4 The placeholder triple changes

The reload placeholder the lar rejects (`ha.battery_placeholder_signatures`:
SoC 51 / grid 2008 / AC-out 607, card #320) is the `stateList` snapshot stored in the
config entry's `products[]` **at the moment the entry was created** (2026-08-26). A
re-created entry stores **whatever the cloud returns at the moment of the add** — a new
triple. In BLE mode it is served less (entities are `unavailable` until the first BLE
poll, and that first poll happens before the entities are added), but a reload that
connects late still publishes it. After the switch, read the new snapshot (§5 step 8)
and add it to the gitops list (keep the old triple too).

---

## 4. Prerequisites (all met on 2026-11-07, re-check on the day)

- [ ] HA Bluetooth integration present and the adapter powered: Settings → Devices &
      services → Bluetooth shows the Pi adapter; or over SSH `bluetoothctl show` →
      `Powered: yes`.
- [ ] The Apex visible with a usable RSSI from vesta: `bluetoothctl --timeout 30 scan on`
      lists `AP3002532000565690`; `bluetoothctl info 30:ED:A0:AC:1B:52` RSSI better than
      −75. (The phone app must **not** be connected to the unit over Bluetooth at that
      moment — one central at a time; the app will fall back to the cloud afterwards.)
- [ ] Bluetti cloud reachable (the flow needs it): the current cloud-mode entities are
      changing, `binary_sensor.bluetti_push_dead` is `off` — i.e. **not** between
      15:00Z and ~23:00Z.
- [ ] The OAuth token valid (it is, to 2026-12-08 — re-login happens in the flow anyway).
- [ ] The #319 hand patch still in place (`sudo sha256sum
      /config/custom_components/bluetti/models.py` = `d107921a…55b3`) — it survives the
      entry delete/re-add; it only dies with a HACS update. Needed again if you roll back.
- [ ] The lar healthy before you start: `jupiter_lar_battery_telemetry_stale == 0`,
      `jupiter_lar_battery_placeholder_rejected_total` flat, Grafana "jupiter" dashboard
      showing live SoC. Note the current SoC and mode.
- [ ] Nobody else touching HA; the HA log view open (Settings → System → Logs, filter
      `bluetti`) — the SSH add-on cannot show the HA log.
- [ ] 30 min of owner attention. Expected entity gap: **2–5 min** (delete → re-add →
      first BLE poll). The lar will hold PASSTHROUGH for that gap, by design; expect
      `JupiterLarPlaceholderHold`/stale alerts to open and clear.

---

## 5. The switch (owner-gated, live production)

Window: **a weekday between ~08:00Z and 14:30Z** (cloud up for the flow, far from the
evening peak, not inside a daily cutoff). Keep this document and §6 open.

1. **Freeze the picture.** Developer Tools → States, filter `office_buzzbrick`: write
   down the current values of
   `sensor.office_buzzbrick_battery_level`,
   `sensor.office_buzzbrick_ap3002532000565690_grid_input_power`,
   `sensor.office_buzzbrick_ap3002532000565690_alternating_current_out_power`,
   `sensor.office_buzzbrick_ap3002532000565690_photovoltaics_input_power`,
   `select.office_buzzbrick_ap3002532000565690_working_mode` (the five ids; the first
   three plus the PV one are the lar's `siteConfig.entities`, the select is the
   automation target). Also note `select.apex300_working_mode` (it is what the lar
   writes). Optionally pause the self-heal reload automations for the window
   (`automation.bluetti_self_heal_reload_integration_when_telemetry_frozen` and
   `automation.bluetti_force_refresh_reload_entry_when_rest_values_sit_unchanged_10_min`)
   so a reload does not race the re-add — remember to turn them back on in step 9.
2. **Make sure the phone app is not on Bluetooth** with the unit (close it, or it will
   hold the only BLE connection and the first polls fail).
3. **Delete the entry**: Settings → Devices & services → BLUETTI → ⋮ on "BLUETTI Power
   Integration" → Delete. The BuzzBrick device and its 13 entities disappear (the lar now
   404s: expected, it holds). Start a timer.
4. **Add it back in BLE mode**: Add integration → BLUETTI → the OAuth login →
   *Select devices*: tick `AP300 - AP3002532000565690-(Cloud)-(BLE)` and set **Control
   mode = Bluetooth Control** → Submit. The flow scans HA's Bluetooth discovery for a
   device named `AP3002532000565690`; expect the *Confirm mapping* form **without** the
   "No matching Bluetooth devices found" text. If that text appears: Submit anyway is
   allowed (the coordinator re-discovers by name at every poll), but it is a signal the
   adapter/app precondition is off — prefer Cancel, fix, retry.
   Leave `ble_polling_interval` 10, `ble_polling_timeout` 120, `ble_max_retries` 5 →
   Submit → the "down_ble_lib" progress (one-time ~3 MB download) → done.
5. **First data**: within ~60 s the device "AP3002532000565690" is back with its
   entities plus `binary_sensor.… Bluetooth Connected` (`on`, attribute
   `bluetooth_address: 30:ED:A0:AC:1B:52`). HA log should show
   `bluetti device AP3002532000565690 connect success!` and no `encrypt link timeout`,
   `proto file not down ok` or `Ble lib … no exist`.
6. **Verify the five entity ids — the step that protects the lar.** Developer Tools →
   States, filter `office_buzzbrick`: all five from step 1 must exist with **live, moving
   values** (SoC within a point of step 1, power values plausible for the time of day).
   If HA minted new ids instead (e.g. `sensor.ap3002532000565690_battery_level`,
   `sensor.buzzbrick_…`), rename each one back **now**: Settings → Devices & services →
   Entities → the entity → ⚙ → *Entity ID* → the old id → Update. Also put the device
   back in area **Office** with name **BuzzBrick** if that was not restored (the area
   itself does not matter to the lar; the ids do). Do not continue until the five ids
   resolve.
7. **Watch the lar recover** (Prometheus via Grafana, or the lar log):
   `jupiter_lar_battery_telemetry_stale` back to 0, `…placeholder_rejected_total` flat,
   `jupiter_lar_soc_pct` = the HA SoC, `degraded.ha=false` in the log, no `Entity not
   found`. Then one actuation cycle: the next time `select.apex300_working_mode` changes
   (or force it by waiting for the 5-min automation tick) confirm the Bluetti select
   follows and the unit's mode on the display/app matches — **the first control write
   over BLE**. If it does not follow, roll back (§6); do not leave the lar with a
   control path that does not act.
8. **Record the new placeholder triple** for gitops (read-only, SSH add-on):
   ```sh
   sudo jq -r '.data.entries[] | select(.domain=="bluetti") | .data.products[] | .stateList[] | select(.fnCode=="SOC" or .fnCode=="GridAllTotalPower" or .fnCode=="ACLoadAllTotalPower") | [.fnCode,.fnValue] | @tsv' /config/.storage/core.config_entries
   ```
   and open a gitops PR adding `{soc: <SOC>, grid_input_power: <Grid>, ac_output_power: <AC>}`
   as a second item under `ha.battery_placeholder_signatures` in
   `landingzones/jupiter-tervuren/values.yaml` (keep 51/2008/607). Also confirm
   `options.device_mapping` and `ble_setting` are stored:
   `sudo jq '.data.entries[] | select(.domain=="bluetti") | .options' /config/.storage/core.config_entries`.
9. **Re-enable** the two automations from step 1 if you paused them. Comment card #358
   with the time of the switch, the entity-id outcome and the first-poll log lines.
10. **Soak for 24 h** before calling it done: `sensor.bluetti_report_ages` should stay
    small (BLE polls every 10 s and re-writes changed values); `binary_sensor.bluetti_push_dead`
    should stay `off`; the Bluetooth Connected binary sensor `on`. Then the 15:00Z test, §7.

Things that may look wrong but are not: `sensor.bluetti_last_push_update` and the
self-heal's "push" wording were written for the cloud websocket — in BLE mode "push" =
"a value changed", which 10 s polling delivers whenever the battery is doing anything;
a long flat SoC at idle still re-stamps nothing (HA only re-writes on change), exactly
as in cloud mode, and the lar's `battery_freshness_mode: enforce` already handles that.

---

## 6. Rollback to cloud mode

Same mechanics, reversed; 5 minutes, the same entity gap:

1. Settings → Devices & services → BLUETTI → ⋮ → Delete.
2. Add integration → BLUETTI → OAuth → select the Apex, **Control mode = Cloud Control**
   → Submit (no mapping/lib steps).
3. Verify the five entity ids exactly as §5 step 6; rename if needed.
4. Confirm the #319 hand patch is still there (`sha256sum` = `d107921a…55b3`; if a HACS
   update replaced the files, re-apply
   [patches/bluetti-1.0.5-ws-handler-both-shapes.patch](patches/bluetti-1.0.5-ws-handler-both-shapes.patch)
   and **restart HA**, not reload — see bluetti-selfheal.md §2e).
5. Watch the lar recover as §5 step 7. The placeholder triple is again whatever the
   cloud returned at the add — read it as in §5 step 8 and keep gitops in sync.

The BLE library and proto files are harmless leftovers (`ble/lib/bluetti_ble_linux_aarch64_314_musl.so`;
the proto `.bin` is deleted on unload anyway).

---

## 7. The 15:00Z test — does BLE keep delivering through the daily cloud cutoff?

The first full day after the switch, at **14:55Z** open Grafana (jupiter dashboard) and
Developer Tools → States, and watch through **15:30Z**:

| Signal | Cloud mode (every day since 10-23) | BLE mode, success | BLE mode, failure |
|---|---|---|---|
| `sensor.office_buzzbrick_*` values | freeze at 15:00–15:06Z; the 15:15Z self-heal reload writes 51/2008/607 | keep changing every ≤ 10 s past 15:06Z | go `unavailable`, or freeze |
| `binary_sensor.…_bluetooth_connected` | n/a | `on` throughout | `off` |
| `jupiter_lar_battery_placeholder_rejected_total{consumer="soc"}` | +1 per 15-min cycle from 15:30Z | flat | climbs |
| `jupiter_lar_battery_telemetry_stale` | 0 then the hold via placeholder | 0 | 1 |
| alerts `JupiterLarPlaceholderHold(Long)` | fire 15:45Z / 17:15Z | silent | fire |
| Bluetti phone app at 15:05Z (over Wi-Fi/cloud, **not** BLE) | unit offline or stale | — the app's view now also tells unit-side vs cloud-side (#358 owner check 1) | — |

Interpretation:

- **BLE live, app offline/stale** → the unit itself is fine and only its **cloud session**
  drops nightly; BLE mode is the fix for #217 and the evening peak is recovered. Comment
  #358 and #217, move #358 to Done; the Bluetti ticket (#358 check 3) becomes "your cloud
  drops our unit at 23:00 CST daily" with the §2 table of the #355 report.
- **BLE also dies at ~15:00Z** → the unit's radio/firmware goes down with the cloud
  session (unit-side); BLE cannot fix it and the ticket must say so. Roll back or stay
  on BLE (it is no worse than cloud during the cutoff and better outside it) — owner
  decision; #357 (lar hold policy) becomes the only lever until Bluetti answers.
- **BLE flaky at other times** (`encrypt link timeout`, reconnects, garbage values as in
  upstream #174) → see §9 for the hardware options and consider `ble_polling_interval`
  15–20 s; the lar reads every 15 s, anything ≤ 20 s is fine.

Record the outcome in the #355 report's successor or a new `docs/soaks/` entry in gitops
(Clio), with the Prometheus queries from the #355 report's Appendix A.

---

## 8. Known risks and limits

- **The window has a hold in it**: 2–5 min without the entities. The lar's contract makes
  that a PASSTHROUGH hold, never a wrong actuation. Do not do it inside a planned
  discharge/charge slot if avoidable; the battery feeds the rack and vesta itself, so a
  mis-step costs availability, not safety — still, no power-cycles, and no control writes
  other than the lar's own.
- **One BLE central at a time.** With HA holding a persistent connection the phone app
  cannot reach the unit over Bluetooth (it uses the cloud instead). Conversely an app
  session over BLE blocks HA's polls → entities `unavailable` → stale hold.
- **The key and proto come from the cloud** at every (re)load (§3.2). A reload while the
  cloud is dead leaves the entities `unavailable` until a reload succeeds — the self-heal
  package keeps retrying every 15 min, as today. Upstream #174's crash path
  (`decrypt_info` `None` → `AttributeError` in `async_setup_entry`) is unhandled in
  v1.0.5: an entry that fails to set up shows "Failed to set up" and needs a manual
  reload once the cloud answers.
- **aarch64 + Python 3.14 is "untested"** upstream; the `.so` exists and is checksum-listed,
  but a load failure (`load ble lib failed`) would show at step 5 and means rollback.
- **Each poll runs a 10 s `BleakScanner.discover`** before reading; with the 10 s interval
  the adapter scans almost continuously. HA's wrapper multiplexes it with its own
  scanner, so it works, but a USB Wi-Fi/BT-coexistence Pi quirk could show as RSSI
  dips — watch `bluetooth_connected` flaps in the first day.
- **Control writes move to BLE.** `select.apex300_working_mode` → automation → Bluetti
  select → BLE write (`SetCtrlWorkMode`). Verified only by §5 step 7; a silent failure
  there is the one way the switch can harm the evening plan, so do not skip it.
- **Garbage values** on AP300 over BLE were reported upstream (#174). The lar's
  plausibility guard observes; if `jupiter_lar_battery_implausible_total` climbs, flip
  `battery_implausible_enforce` on (gitops) or roll back.
- **A HACS update** of the integration still wipes the #319 patch; in BLE mode that patch
  is dormant, so an update is only a problem after a rollback to cloud mode.

## 9. Hardware options if BLE from the rack turns out unstable

Not needed on today's evidence (−55 dBm), listed because the card asked:

1. **ESPHome Bluetooth proxy in the office** (any ESP32, `bluetooth_proxy:` + `esp32_ble_tracker:`,
   `active: true`). HA merges proxy scanners into its Bluetooth stack natively; v1.0.5
   added proxy support (fixes #153/#154). The integration's own `BleakScanner.discover`
   call goes through HA's wrapper, so proxied devices are seen. Cheapest fix for range.
2. **USB BLE dongle on vesta** (a BT 5.x adapter from HA's supported list) if the Pi's
   onboard radio is the weak part; HA adds it as a second adapter, the config flow does
   not care which one sees the unit.
3. **Modbus TCP** (#309, `bluetti_modbus` already installed today) once the firmware
   exposes it — the only path with no key, no proto and no cloud at all.

## 10. Commands used (all read-only, from WSL via the SSH add-on)

```sh
# vesta.local does not resolve inside WSL; use the IP with the known_hosts alias
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'ls -la /sys/class/bluetooth; bluetoothctl list; bluetoothctl show'
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'timeout 40 bluetoothctl --timeout 30 scan on | grep -v -e RSSI -e ManufacturerData; bluetoothctl devices'
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'bluetoothctl info 30:ED:A0:AC:1B:52'
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'sudo jq -r ".data.entries[] | select(.domain==\"bluetooth\" or .domain==\"bluetti\") | [.domain,.title,(.options|tostring)] | @tsv" /config/.storage/core.config_entries'
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'sudo jq -r ".data.entities[] | select(.platform==\"bluetti\") | [.entity_id,.unique_id] | @tsv" /config/.storage/core.entity_registry'
ssh -o HostKeyAlias=vesta.local admin@192.168.50.18 'cat /config/custom_components/bluetti/manifest.json; sudo sha256sum /config/custom_components/bluetti/models.py; ls /config/custom_components/bluetti/ble/lib/'
curl -sS https://download.bluetti.app/ha-libs/20260908/linux/SHA256SUMS
```

## 11. As-built — the switch was performed on 2026-11-07

Owner "go" at ~19:50Z, switch target: **Bluetooth Control**. Timeline (UTC):

| When | What |
|---|---|
| 20:03 | Cloud-mode config entry deleted (agent, from the HA UI in the Claude browser pane). 13 entities moved to `deleted_entities`. |
| 20:03–22:12 | Three attempts to re-add through the agent's browser pane lost the flow dialog at the `my.home-assistant.io` → `/auth/external/callback` hand-off (pane closes the tab, user-started flows are not listed by `config_entries/flow/progress`). **Do the add in your own browser**: the OAuth popup must return to the same HA tab that owns the dialog. |
| 22:12:39 | Owner re-added the integration in their own browser: device `AP300 - AP3002532000565690` ticked, Control mode **Bluetooth Control**, confirm mapping 10 / 120 / 5. New entry `01M6W149G1W8FET5YDCWNTFGF4`, `data.products[0].control_mode = bluetooth`, `server_key` stored (512 chars), entry keys `auth_implementation, products, token`. |
| 22:12 | All 14 entities re-created with **identical entity ids** (unique_id `<SN>_<fnCode>`, restored from `deleted_entities`, 0 left over). The five ids from §5 step 6 needed no rename. |
| 22:15 | First BLE reading reached the lar: SoC 64 (frozen since the 15:30Z cloud cutoff) → 47 live; `jupiter_lar_battery_report_ages_push_seconds` 25910 → 53 s (push-aware freshness works with the BLE feed, `sensor.bluetti_report_ages` keeps functioning); `jupiter_lar_battery_telemetry_stale` 0; placeholder rejections flat. |
| 22:15:10 | First control write over BLE: lar log `applied live: select -> 'PASSTHROUGH'`. `jupiter_lar_actual_mode_known` dipped 1 → 0 for ~4 min (automation runs on state change + every 5 min, then the BLE poll reads the mode back), then `jupiter_lar_actual_mode` 2 → 0 at 22:19:56 with `actual_mode_known` 1. **Actuation over BLE confirmed.** |

The lar held PASSTHROUGH for the whole 20:03–22:12 window (its metrics were frozen,
`jupiter_lar_battery_telemetry_age_seconds` constant), as it had done since the 15:30Z
cutoff anyway. No power interruption, no manual control write by the agent.

**Placeholder triple of the new entry** (§5 step 8):
`SOC 0 / GridAllTotalPower 0 / ACLoadAllTotalPower 0` — the stateList snapshot was taken
while the cloud was in its daily cutoff. In BLE mode the sensors are only added after the
coordinator's first successful poll and report `unavailable` (not the seed value) while
`bluetooth_connected` is off, so a placeholder publication is unlikely; the triple is
added to `ha.battery_placeholder_signatures` defensively anyway (gitops branch
`card-358`, PR linked on the Trello card). The old 51/2008/607 triple stays for the
Cloud-Control rollback.

**Not verified directly:** the HA states themselves (`binary_sensor …bluetooth_connected`,
the four sensors) — the agent path has no HA API token; the SSH add-on shell has no
`SUPERVISOR_TOKEN`; the HA MCP server only sees exposed entities. The evidence above is
the lar's own reads and log. Also not yet observed: the 15:00Z cutoff with BLE live
(§7) — first opportunity 2026-11-08 15:00–15:06Z.

**Still cloud-dependent after the switch:** every integration (re)load fetches the
product list and the proto file and may refresh `server_key` (≤ 1×/12 h). An HA
restart or integration reload during a Bluetti cloud outage therefore fails setup
(entities missing → lar hold). Prefer not to reload the integration between 15:00Z and
the evening recovery.

### 11.1 First 20 minutes on BLE: the link flaps

HA archive (`binary_sensor.office_buzzbrick_ap3002532000565690_bluetooth_connected`,
2026-11-07 UTC): off 22:12:40 → **on 22:13:05** → off 22:15:31 → **on 22:18:08** → off 22:20:24
→ **on 22:27:54**. Connected stretches of 146 s and 136 s, gaps of 157 s and 450 s. While the
link is off every Bluetti entity is `unavailable`: HA's `binary_sensor.bluetti_telemetry_stale`
turned on 22:20:24–22:27:54, `bluetti_integration_alive` off 22:21–22:27, and the lar's
`jupiter_lar_actual_mode_known` (measured mode from grid-in − AC-out, so it needs both
reads) follows the link exactly (avg 0.25 over 22:15–22:25 vs 1.0 all day in cloud mode).
`bluetoothctl info` on vesta at 22:28:29 showed `Connected: yes`, RSSI −56, so the drops are
not range; the integration's own read loop (`device_reader_v2.read_data`: a 10 s
`BleakScanner.discover` **before every poll** while the HA Bluetooth integration owns the
same hci0, then the encrypted session; a `TimeoutError`/`BleakError` → `_stop_notify`
→ disconnect) is the prime suspect, together with the integration setting the
connection up again on the next poll rather than keeping it.

Consequences to know about:

- **Self-heal interplay.** `bluetti_selfheal`'s reload automation fires when
  `bluetti_telemetry_stale` is on for 2 min, paced by its cooldown (15 min in the first
  hour of an episode, 60 min after that — the 22:22 outage hit the slow phase, last reload
  22:00:30, so nothing reloaded and BLE came back on its own). A reload in BLE mode
  re-runs setup, which needs the cloud (product list, proto file, `.so` checksum). With the
  cloud up that is a harmless BLE re-establish; **during the 15:00Z cutoff a BLE drop
  longer than the 2 min debounce + cooldown means a reload that FAILS setup → entities
  missing until the cloud returns** (the lar holds PASSTHROUGH either way, as it does
  today in cloud mode).
- **`sensor.bluetti_report_ages` / `bluetti_last_push_update` discount BLE reconnects**:
  the package treats "any of the four entities going unavailable → value" as a reload and
  ignores the first changes after it, so the push age the lar reads jumps at every
  reconnect (521 s at 22:28 although values had been live until 22:20). Hestia follow-up:
  teach the package the difference between a reload and a BLE reconnect (e.g. watch
  `…bluetooth_connected`).
- A ~50 % link duty cycle means roughly half of the lar's 15-min planning cycles find the
  entities unavailable and hold. Watch `jupiter_lar_battery_telemetry_stale` and
  `JupiterLarPlaceholderHold` tonight; if the holds dominate, roll back to Cloud Control
  (§6) in the morning and move BLE to a dedicated radio (§9: ESPHome proxy next to the
  rack, or a USB dongle on vesta with the HA Bluetooth integration's passive scanning
  off) before trying again.

### 11.2 Charge test 22:36–22:45Z: control works, power readings flap to 0, the lar's spike responder fights the charge

Owner-requested. `select.apex300_working_mode` → CHARGING made the automation write
`Backup` to the Bluetti select within 1 s; the HEM import rose 0.8 → 2.8 kW and
`jupiter_lar_actual_mode` read 1 (charging). PASSTHROUGH → `Time of Use` within 2 s. So
**both directions of control over BLE work.** The test was ended at 22:45:40Z with
PASSTHROUGH re-applied.

Two defects showed up:

1. **`…grid_input_power` and `…alternating_current_out_power` alternate between the true
   value and 0** on consecutive BLE polls (HA archive, 18 s spacing: grid-in 2093 → 0 →
   2091 → 0 while charging; AC-out 826 → 0 → 835 → 0 with ~800 W on the rack). SoC and
   the mode select do not flap. Most likely two register blocks in the device's proto
   file both map to the same fnCode and the second one carries 0 (`parse_oak_state_data`
   merges whatever each polling command returns). Needs the proto file / an upstream
   issue; in the meantime any consumer must treat a 0 from these two sensors as
   "unknown", not "zero watts".
2. **The lar's spike responder (#177/#178) fights every charge.** Its corrected house
   signal is `max(0, import − battery_grid_input)`; with battery_grid_input flapping to
   0 the battery's own 2 kW charge looks like a house spike: spike TRIGGER → DISCHARGING
   at 22:37:52 and 22:42:23 (each ~90 s after a `Backup`), spike RELEASE → PASSTHROUGH
   two minutes later. The HA automations are not involved. In cloud mode the readings
   do not flap, so this never happened there. On BLE, a night in which the plan charges
   means a CHARGING → DISCHARGING → PASSTHROUGH loop every 2–4 min — never unsafe, but
   it cycles the battery and defeats the charge.

Fix candidates: lar — hold the spike correction at the last non-zero battery grid-in
while the commanded mode is CHARGING (hephaestus card); integration — proto/upstream
fix for the duplicate field; or #309 Modbus as the local source. Until one lands,
**Cloud Control is the safe overnight mode** (§6).
