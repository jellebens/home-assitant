# ADR-0001: Home Assistant telemetry is archived in InfluxDB forever — unfiltered, bucket retention declared in git

- **Status:** Accepted (2026-09-11). First ADR in the home-assitant repo; platform half is gitops ADR-0002 (card #290). Nothing on vesta changes.
- **Date:** 2026-09-11
- **Deciders:** Jelle (owner), with Claude
- **Tags:** home-assistant, influxdb, recorder, retention, archive

## Context

Home Assistant on vesta writes every entity to the InfluxDB `homeassistant`
bucket through its InfluxDB integration (UI config flow, write-only token,
over the gateway at `influxdb.lab.local` — see
[`../../influxdb-and-recorder.md`](../../influxdb-and-recorder.md)). That
stream is deliberately **unfiltered**: a connection-less `influxdb:` YAML
block with include/exclude filters broke the integration on 2026-06-29, and
recording everything was judged harmless. The recorder (SQLite) is the
short-window, filtered store; InfluxDB is the long one.

The `homeassistant` bucket was created by hand with infinite retention. That
was a fact in a README, not something git enforced, and nothing in this repo
recorded that "forever" was the intent rather than an omission. Meanwhile HA
is the only path by which several project signals reach InfluxDB at all —
`sensor.pomona_pump_power` (the Fibaro plug, which Demeter treats as proof the
pump ran), the Bluetti and Aeotec energy series jupiter's forecaster trains on,
the Fluvius peak-power entity.

On 2026-09-11 the owner decided that all telemetry, across every project, is
archived in InfluxDB forever.

## Decision

1. **The `homeassistant` bucket keeps infinite retention, and that is now
   declared and reconciled from git** (gitops `platform/influxdb-config`
   `buckets.list`, retention `0`, applied hourly by the `influxdb-buckets`
   CronJob). Any drift is corrected without a vesta-side action.
2. **HA keeps recording every entity, unfiltered.** The 2026-06-29 lesson
   stands: no `influxdb:` YAML block, no include/exclude. Trimming noise
   (RSSI, link quality, uptime) is the recorder's job, not the archive's.
3. **HA-relayed project signals are part of the project archives by
   reference.** `sensor.pomona_pump_power` is also published to
   `pomona/pump/power` (package `pomona_schedule` ≥ 1.3.0) and lands in the
   `pomona` bucket's `pomona_events`; the battery/energy entities stay in
   `homeassistant` and are read from there by the forecaster (jupiter
   ADR-0024 union read path).
4. **The recorder's short window is unchanged** (`purge_keep_days: 10`) — the
   recorder is for HA's own history panels and statistics, not for training.

## Consequences

- **No action on vesta.** The integration, its token and its config flow are
  untouched. The only owner-visible change is that the gitops repo now owns
  the bucket's existence and retention.
- **Storage:** the bucket grows at its current ~670 points / 15 min
  indefinitely; it is included in the nightly full and the hourly
  incremental NAS backups (gitops `backup.incremental.buckets`).
- **This repo gains a `docs/adr/` series** in the demeter/jupiter format. New
  operational lessons still go in the flat runbooks (per `AGENTS.md`); ADRs
  are for decisions.
- **Revisit trigger:** if the `homeassistant` bucket's cardinality (one
  series per entity) ever becomes the dominant InfluxDB cost, the answer is
  the integration's own options-flow filter — never a YAML block.

## Alternatives considered

- **Filter HA's InfluxDB stream to "useful" entities** — rejected: proven to
  break the integration via YAML, and which entities matter for training is
  not known in advance.
- **A finite retention with the recorder as the archive** — rejected: the
  recorder is SQLite on vesta with a 10-day purge; it is not a durable store.
