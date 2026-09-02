# Pomona — pump and grow-light scheduling (runbook)

Companion to [packages/pomona_schedule.yaml](packages/pomona_schedule.yaml)
(pump + light scheduling) and
[packages/pomona_telemetry.yaml](packages/pomona_telemetry.yaml)
(tower telemetry into HA over MQTT, and the level interlock).

The Pomona tower was planted on **2026-08-31** (18 of 30 pods: 9 alpine
strawberry, 4 paprika, 3 Dulce Italiano, 2 chili — see the pomona repo's
`docs/planting-plan.md`). Until then the pump ran continuously off a dumb power
pack and there was no light schedule at all. This package gives both a duty
cycle.

## Design decisions

**Control lives in Home Assistant, not in the GIGA firmware.** The project
deliberately deferred automated control, and this does not reverse that for the
unit: the GIGA still only measures and publishes. Scheduling runs on HA smart
plugs, because the GIGA reboots for OTA updates and a reboot must never be able
to strand the pump off or the lamps on. It also keeps the schedule editable
without reflashing anything.

**Two modes, one toggle.** `input_boolean.pomona_establishment` is ON now and
should be turned **OFF around 2026-09-14**, roughly two weeks after transplant.

| | establishment | established |
|---|---|---|
| Pump, light hours | 15 min on / 15 min off | 15 min on / 45 min off |
| Pump, dark hours | 15 min on / 15 min off | 15 min on, every 2 h |
| Photoperiod | 12 h (08:00–20:00) | 14 h (06:00–20:00) |

*Why establishment is wetter:* freshly transplanted roots are still confined to
the sponge and have not reached down into the tower interior. They cannot ride
out a long dry gap, and a sponge that dries out once takes the plant with it.
Once roots hang free in the tower the logic inverts — roots need oxygen, so
cycling beats soaking and the off-periods lengthen.

*Why the photoperiod ramps:* the seedlings came straight off a propagation tray
and want shade for the first few days. 14 h is the steady-state target for
fruiting crops indoors. The dark period is **not** optional — never run these
lamps 24 h.

## Firmware in command — event → HA → Fibaro

The GIGA can take over the deciding, with HA reduced to relaying its requests
to the Fibaro plugs. This is the first half of the target architecture in the
pomona repo's `docs/control-architecture.md` (Trello **#260**): the decision
moves to the device that actually holds the sensors, while actuation stays in
certified smart plugs and **no mains wiring is touched**.

### The contract

Must match the firmware and the pomona repo's `docs/mqtt.md`:

| Topic | Payload | Retained |
|---|---|---|
| `pomona/pump/request` | `on` / `off` | **yes**, QoS 1 |
| `pomona/light/request` | `on` / `off` | **yes**, QoS 1 |
| `pomona/pump/reason` | free text — why the last request was made | yes |

**Retained is load-bearing.** On an HA restart the broker replays the current
request immediately, so HA does not sit with the plugs in a stale state waiting
for the next firmware decision.

### Exactly one controller at a time

`binary_sensor.pomona_firmware_in_command` decides who is driving, and it is on
only when the firmware is **both enabled and reachable**:

```
firmware_in_command = input_boolean.pomona_firmware_control (on)
                      AND binary_sensor.pomona_unit_online (on)
```

Every HA scheduling automation now stands down while that is on, and the two
`follow firmware request` automations only act while it is on. There is no
window where both are driving.

### The fallback is the point

A GIGA that crashes, wedges, or goes out for an OTA **hands the schedule
straight back to HA**, and a notification says so. Without that, a dead unit
would freeze the pump in whatever state it last requested — which is why the HA
schedule is *kept* at cutover rather than deleted. Firmware control resumes by
itself when the unit comes back.

The HA-side sustained-low inhibit also stays in place as a second opinion on
pump-on requests. The firmware owns the interlock once it has one, but a
tested second check costs nothing.

### Cutting over, and rolling back

1. Flash firmware that publishes `pomona/pump/request` and
   `pomona/light/request`. **Do this first** — the switch below does nothing
   useful until something is publishing.
2. Watch the topics with a broker client and confirm the requests look sane
   against the schedule you expect.
3. Turn **`input_boolean.pomona_firmware_control` ON**. HA stands down and
   starts relaying.
4. **Rollback is one click**: turn it back off and the HA schedule resumes
   immediately.

## Applying it

This repo does **not** sync to vesta. Apply by hand:

1. Copy `packages/pomona_schedule.yaml` to `/config/packages/` on vesta
   (`vesta.local` / `192.168.50.18`).
2. Confirm `configuration.yaml` has packages enabled:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. **Verify the entity IDs first** — see below.
4. Developer Tools → YAML → Check configuration, then Restart.
5. Confirm `input_boolean.pomona_establishment` exists and is **ON**.

## Relay reconciliation (#277)

The follow-firmware relays are edge-triggered; a dropped Z-Wave frame once
left the pump OFF while the firmware wanted it ON (2026-09-03). The package
therefore also mirrors the retained request topics into
`binary_sensor.pomona_pump_requested` / `pomona_light_requested` and runs
`Pomona — reconcile plugs with firmware requests` every 5 minutes while the
firmware is in command: any plug that disagrees with the retained request is
re-asserted (ON path still honors the level interlock; unknown/unavailable
request sensors assert nothing). Applying this update needs a **restart** (new
MQTT entities + automation), or reload both "Automations" and "Manually
configured MQTT entities" from Developer Tools → YAML.

## ⚠ Verify the entity IDs before applying

The package assumes:

- `switch.pomona_pump`
- `switch.office_pomona_lamps` — NOT the standard slug for "Pomona Lamps":
  the entity was created as `office_pomena_lamps` and the #255/#256 typo fix
  renamed it to `office_pomona_lamps`, keeping the `office_` prefix. Verified
  against live HA 2026-08-31.

A renamed entity keeps its slug even when the friendly name changes. If either
is wrong, **the automations fail silently** — no error, just a pump that never
cycles. Check Developer Tools → States and correct the package.

## Level awareness — what the probe can and cannot do

The GIGA already pushes everything needed, so **no firmware change was
required**: it publishes `pomona/<zone>/<metric>` to `mqtt.lab.local:1883`
every 30 s with a retained `pomona/unit/status` backed by an MQTT Last Will.
HA simply was not subscribing. [packages/pomona_telemetry.yaml](packages/pomona_telemetry.yaml)
subscribes, and the pump schedule now has level awareness.

**Why state rather than an event.** The intuitive design is "have the Arduino
push an event when the water gets low". Periodic state is strictly better for
an interlock: an event fires once, and anything that misses it — an HA restart,
a dropped QoS-0 message, a broker blip — leaves the pump unguarded with no way
to notice. Periodic state plus an LWT means HA always knows both the current
value *and* whether the reading can be trusted. Events are for notifying
humans; state is for interlocks.

### ⚠ This is still not true dry-run protection

The CQRSENYW003 is mounted as a **top-up gauge**: point 1 wets at 8.2 L, point
3 at 9.7 L. A reading of **0 points means "below 8.2 L", and the probe is blind
below that line** — it cannot tell 8 L from empty.

So cutting the pump at 0 points would be wrong twice over. It would stop
irrigation at a perfectly healthy ~8 L, and it would fire routinely between
top-ups. Killing the watering every time a top-up is a day late would destroy
the crop far more reliably than the dry-run it was meant to prevent.

What is implemented instead:

| Signal | Behaviour |
|---|---|
| 0 points for 30 min | **Refill notification.** A prompt, not a cutoff. |
| 0 points for **24 h** | `binary_sensor.pomona_level_critically_low` turns on and **inhibits the pump**. No longer "time to top up" but "nobody topped up and this tank may be running out". |
| Sensor unknown / unit offline | **Fails open — the pump keeps running**, plus an offline notification. Over any 24 h window, plants dying of no water is a near certainty while an unnoticed empty tank is not, and the reservoir drains over days rather than hours. |

### The settle check — believing a 0 only after the water has settled

Remounting the probe at pump-intake height was the clean fix, and it is **not
possible** — the tank geometry does not allow it. So the compensating control
is in software.

A raw 0 read *while the pump is running* is not even a trustworthy "below
8.2 L". An aeroponic tower holds a real volume **in transit** — in the riser,
the drip line and the six tiers — so the reservoir sits visibly lower during a
cycle than the total water justifies, and turbulence at the optical tips adds
flicker on top. That is exactly why the raw signal was unusable as an interlock.

So on a sustained raw 0, HA now:

1. **stops the pump**, so the tower drains back and the surface stills;
2. **waits 5 minutes** — comfortably longer than the drain-back, and costing at
   most one skipped 15-minute cycle;
3. **re-reads and decides**:
   - **recovered (≥ 1 point)** → it was water in transit. Clear the flag,
     resume, say nothing.
   - **still 0** → this is a reading worth acting on. Notify to top up, and set
     `input_boolean.pomona_level_confirmed_low`.
   - **sensor unknown** → unknown is not empty. Resume, leave the flag alone.

Rate-limited to one check per hour so it cannot thrash the pump.

The 24 h pump inhibit is now keyed off the **settled verdict** rather than the
raw probe, so in-transit water can never trip it.

**What this still cannot do:** detect an empty tank. Nothing mounted at the
8.2 L line can see below it. What it does do is turn the one honest low signal
available into a reliable one, and stop the pump the moment that signal is
confirmed.

### Prerequisite for the telemetry package

The **MQTT integration must be configured** on this HA instance against
`mqtt.lab.local:1883`, with credentials allowed to subscribe to `pomona/#`.
The EMQX `pomona` account is the unit's own publisher credential and is
ACL-limited to that prefix — give HA its own user rather than sharing the
device's.

## Tuning it later

- **Pump too wet / algae or root rot appearing:** shorten to 10 min on, or drop
  the establishment half-hour trigger early.
- **Sponges drying between cycles:** stay in establishment mode longer, or add
  a `:45` ON trigger.
- **Light level:** the target is **≥10 klx at canopy** on the BH1750. If the
  lamps cannot reach it, more hours will not substitute for intensity —
  fruiting crops need the photon count, not the clock time.
- **Reservoir warming:** a pump running more heats a 10 L tank. If water
  temperature climbs above ~22 °C, shorten the cycles rather than the
  photoperiod.

## Related

- Planting as-built and nutrient targets: pomona repo `docs/planting-plan.md`
  (EC 0.8–1.0 now, ramping to the shared 1.4–1.6 over 2–3 weeks; pH ~6.0)
- Seedling history and the lettuce post-mortem: pomona repo `docs/seeding/`
- Trello #219 (design/crops), #224 (phase 2 — peristaltic dosing pumps)
