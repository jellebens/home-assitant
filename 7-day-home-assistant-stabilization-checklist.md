# 7-Day Home Assistant Stabilization Checklist

Start date: ____________________
Home Assistant URL: ____________________
Owner: ____________________

## How to use this
- Run one daily block of 45-60 minutes.
- Start with discovery prompts, then apply fixes.
- Record outcomes in the daily log template.
- Track KPIs at the end of each day.

## KPIs (track daily)
- Unavailable entities (total): ______
- Unavailable critical entities: ______
- Automations failing per day: ______
- Battery entities below 20%: ______
- Noisy alerts per day: ______

---

## Day 1 - Baseline and Risk Map
Goals:
- Build full entity and area inventory.
- Identify top critical risks.

Prompts:
- List all entities grouped by domain and area.
- List entities with state unavailable or unknown.
- Show entities not updated in the last 24 hours.

Actions:
- Mark critical entities (doors, leak, smoke, climate, security).
- Create a top-10 unstable entity list.

Done criteria:
- Priority tiers documented: critical, important, non-critical.
- Top-10 unstable list complete.

Status: [ ] Complete
Notes:

---

## Day 2 - Connectivity and Availability
Goals:
- Reduce intermittent unavailable states.

Prompts:
- Show entities with frequent unavailable transitions in 7 days.
- Group unstable entities by integration.

Actions:
- Wi-Fi devices: verify signal quality and DHCP reservation.
- Zigbee/Z-Wave: identify weak nodes and routing improvements.
- MQTT: verify topic freshness and retained states.

Done criteria:
- 50%+ of frequent-unavailable entities resolved.
- No critical entity unstable without owner and next action.

Status: [ ] Complete
Notes:

---

## Day 3 - Battery and Power Health
Goals:
- Remove battery surprise failures.

Prompts:
- List all battery sensors sorted ascending.
- Flag battery sensors under 30%, then under 20%.

Actions:
- Replace low batteries or schedule replacement.
- Create low-battery alert automation (daily).

Done criteria:
- Battery watch list complete.
- Low-battery alert tested.

Status: [ ] Complete
Notes:

---

## Day 4 - Automation Reliability Pass
Goals:
- Stabilize automations and reduce silent failures.

Prompts:
- List automations disabled, failing, or noisy recently.
- Summarize top-5 failing automations and likely causes.

Actions:
- Disable unsafe/noisy automations temporarily.
- Repair top-3 broken automations.
- Add debounce/delay where triggers are noisy.

Done criteria:
- Top-3 automations pass dry run.
- Noticeable alert spam reduction.

Status: [ ] Complete
Notes:

---

## Day 5 - Entity Hygiene and Area Mapping
Goals:
- Improve maintainability and naming consistency.

Prompts:
- Find duplicate or near-duplicate entities.
- Identify entities missing area assignments.
- Propose naming normalization by room and type.

Actions:
- Standardize names for most-used entities.
- Assign missing areas for core domains.

Done criteria:
- Core naming pattern applied.
- Important entities all have area assignments.

Status: [ ] Complete
Notes:

---

## Day 6 - Dashboard and Alert Quality
Goals:
- Improve visibility and reduce notification noise.

Prompts:
- Propose a minimal operations dashboard.
- Classify last-week alerts as useful vs noisy.

Actions:
- Remove or tune noisy alerts.
- Add concise morning summary card/report.

Done criteria:
- Critical status visible in under 30 seconds.
- Non-actionable alerts reduced.

Status: [ ] Complete
Notes:

---

## Day 7 - Hardening and Weekly Runbook
Goals:
- Lock in gains and prevent regression.

Prompts:
- Re-run Day 1 inventory and compare differences.
- Show unresolved unstable entities and next actions.

Actions:
- Create weekly 15-20 minute maintenance checklist.
- Save top operational prompts.

Done criteria:
- Before/after metrics captured.
- Weekly maintenance routine defined.

Status: [ ] Complete
Notes:

---

## Weekly Maintenance Checklist (after Day 7)
- [ ] Review unavailable/unknown entities.
- [ ] Review battery < 20%.
- [ ] Review automation failures and traces.
- [ ] Review noisy alerts and tune thresholds.
- [ ] Verify critical entities report healthy state.
- [ ] Update dashboard for any new critical devices.
