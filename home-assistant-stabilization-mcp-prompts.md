# Home Assistant Stabilization MCP Prompt Pack

Use these prompts in Copilot Chat while your Home Assistant MCP server is running.
Replace placeholders like <AREA_NAME> only when needed.

## Day 1 - Baseline and Risk Map

Prompt 1
```text
List all Home Assistant entities grouped by domain and area. Include entity_id, friendly_name, area, state, and last_changed.
```

Prompt 2
```text
List all entities with state unavailable or unknown. Sort by criticality and include likely impact.
```

Prompt 3
```text
Show entities that have not updated in the last 24 hours. Include integration, area, and suspected cause.
```

Prompt 4
```text
Create a prioritized risk table with three levels: critical, important, non-critical. Put doors, leak, smoke, climate, and security entities in critical unless proven otherwise.
```

## Day 2 - Connectivity and Availability

Prompt 1
```text
Show entities with frequent unavailable transitions in the last 7 days. Group by integration and area.
```

Prompt 2
```text
For each unstable entity, suggest one likely root cause and one concrete remediation step.
```

Prompt 3
```text
Generate a short action plan to improve reliability for Wi-Fi, Zigbee/Z-Wave, and MQTT devices based on current instability patterns.
```

Prompt 4
```text
Re-check critical entities and confirm whether any are still unstable. Return only unresolved critical issues.
```

## Day 3 - Battery and Power Health

Prompt 1
```text
List all battery-related sensors sorted from lowest to highest. Include entity_id, area, and percentage.
```

Prompt 2
```text
Show a replacement queue for batteries under 30% and highlight urgent replacements under 20%.
```

Prompt 3
```text
Draft a daily low-battery notification automation at 09:00 with grouped output by area.
```

Prompt 4
```text
Validate the low-battery automation logic and identify any edge cases that could cause false positives.
```

## Day 4 - Automation Reliability Pass

Prompt 1
```text
List disabled, failing, or noisy automations from the recent history. Include likely failure reason.
```

Prompt 2
```text
Rank the top 5 problematic automations by impact and failure frequency.
```

Prompt 3
```text
Provide corrected logic for the top 3 broken automations, including trigger, condition, and action improvements.
```

Prompt 4
```text
Suggest debounce or delay settings for noisy triggers to reduce false activations.
```

## Day 5 - Entity Hygiene and Area Mapping

Prompt 1
```text
Find duplicate or near-duplicate entities and propose a safe cleanup plan.
```

Prompt 2
```text
List entities with missing area assignments and suggest best-fit areas.
```

Prompt 3
```text
Propose a naming normalization convention by room and device type, then map current names to proposed names.
```

Prompt 4
```text
Generate a staged rename plan that minimizes dashboard and automation breakage.
```

## Day 6 - Dashboard and Alert Quality

Prompt 1
```text
Design a minimal operations dashboard with critical alerts, battery summary, availability, climate exceptions, and top power consumers.
```

Prompt 2
```text
Classify last-week alerts into useful and noisy, with tuning recommendations for noisy alerts.
```

Prompt 3
```text
Suggest threshold, delay, and cooldown settings to reduce alert fatigue while preserving safety-critical notifications.
```

Prompt 4
```text
Create a concise morning status summary template for daily operational review.
```

## Day 7 - Hardening and Weekly Runbook

Prompt 1
```text
Re-run Day 1 baseline and compare with current state. Show what improved, what regressed, and what remains unresolved.
```

Prompt 2
```text
List unresolved instability items with owner, impact, and next action.
```

Prompt 3
```text
Create a weekly 15-20 minute maintenance checklist covering availability, battery, automation failures, and noisy alerts.
```

Prompt 4
```text
Generate a final stabilization report with current KPIs and recommended follow-up priorities for next week.
```

## Fast Reuse Prompts

Prompt A
```text
Show unavailable and unknown entities grouped by area, critical first, with one remediation step per entity.
```

Prompt B
```text
Show battery sensors under 20% grouped by area with urgency ranking.
```

Prompt C
```text
Show failed automations in last 24 hours and provide corrected logic proposals.
```

Prompt D
```text
Summarize current operational health in 10 lines: availability, battery, automations, alerts, and climate exceptions.
```
