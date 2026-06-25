# PRD: Firewalla Local-First Skill

## Current Product Question

We have validated that local SSH plus Redis is viable on the user's Firewalla box. The next product question is not how to call Redis, but which Firewalla facts are useful enough to become stable AI-facing artifacts.

The immediate goal is to dump and understand local data formats, then decide which information deserves first-class CLI commands and summaries.

## Goal

Build a public-ready AI skill for Firewalla that starts with local-first access on Firewalla Gold-class boxes and supports safe read-only network inspection before any write automation.

## Initial User

A Firewalla Gold/Gold Plus owner who wants AI-assisted network visibility, alert review, device lookup, and eventually rule automation.

## MVP Scope

1. Dump representative local Redis data formats for devices, alarms, flows, and system health without committing private data.
2. Identify which fields are stable, high-signal, and safe to summarize.
3. Provide stable read-only CLI commands that emit redacted JSON snapshots.
4. Document local access paths and keep the official MSP API as a paid optional path.
5. Keep all examples fake and publishable.

## Non-Goals

1. No desktop cookie scraping in the MVP.
2. No Playwright automation in the MVP.
3. No write operations until read-only local access is verified.
4. No browser session token scraping in the MVP.

## Success Criteria

1. A user can understand exactly which credentials are needed.
2. An agent can use the skill without seeing private credentials in repo files.
3. The first implementation can collect basic local status without requiring a paid MSP API plan.
4. The MVP performs no mutation on the Firewalla box.
5. The project has one sanitized format report showing what Firewalla local Redis data looks like and what fields we will use.

## Product Value Hypothesis

The useful product is not a raw Firewalla database browser. The useful product is an AI-readable network situation snapshot: what changed, what looks risky, which devices matter, what alerts deserve attention, and whether the box/network itself is healthy.

The CLI should therefore prioritize facts that help an agent answer household-network questions:

1. What devices exist, and which ones are active or newly seen?
2. Which alarms are pending or active, and which devices/entities caused them?
3. Which devices or flows changed recently in a way that looks unusual?
4. Is the Firewalla box healthy enough that its observations are trustworthy?
5. What policies/rules exist, but only as read-only context for now?

## Information Priority

### P0: Must understand first

These are the first data surfaces to dump and normalize.

1. Device inventory from `host:mac:*`: device identity, last active time, IP mappings, vendor/type/name-like fields, online/offline hints, and group/user relationships if visible.
2. Active alarms from `alarm_active` plus `_alarm:<aid>` and `_alarmDetail:<aid>`: alarm type, timestamp, device/entity, severity-like fields, destination/domain/IP fields, and status.
3. Recent flows from `flow:conn:*` and `flow:local:*`: source device, direction, destination, port/protocol, bytes/counts, timestamps, and category fields if present.
4. Basic box health: hostname, uptime, Redis availability, Firewalla software/version candidates, WAN/LAN status candidates, and resource/load indicators.

### P1: Useful after P0 format is known

These are important, but their raw volume and privacy risk are higher.

1. Device last-flow indices such as `deviceLastFlowTs`: which devices were active recently and whether activity changed.
2. Rule/policy state in read-only mode: enough to explain why a flow or device is allowed/blocked, without changing rules.

### P2: Later enrichment

These become useful once the core snapshot is reliable.

1. Historical trends: daily device activity, alarm counts, bandwidth deltas, recurring destinations.
2. Group/user/watchlist metadata: context for household automation and parental-control-like interpretation.
3. Local Encipher API runtime data: richer snapshots and possible future write operations after a separate security review.

## First Artifact To Produce

The next concrete deliverable should be a local-only format dump report, stored outside public-tracked data unless sanitized. It should answer:

1. Which Redis keys exist on this box for P0 surfaces?
2. What does one representative record look like for each surface?
3. Which fields look stable and useful?
4. Which fields are sensitive and must be redacted?
5. Which fields should become the first JSON snapshot schema?

The public repo should only keep a sanitized summary and fake examples.

## Proposed First JSON Snapshot

The first stable output should be a compact object with these top-level sections:

```json
{
  "box": {},
  "devices": [],
  "alarms": [],
  "flows": [],
  "flows_summary": {},
  "collection": {
    "source": "ssh_redis",
    "redacted": true
  }
}
```

This is intentionally smaller than Firewalla's raw data. The product should preserve the fields needed for AI reasoning and hide fields that only increase privacy risk.

## Open Questions

MSP Lite shows API/Integration as locked. Current public pricing indicates API/Integration starts at Professional. The project should not require the paid MSP API for MVP.

Data questions to answer with the format dump:

1. Which host fields reliably identify a device without needing private names?
2. Are alarm payloads self-contained, or do they require joining host/flow/detail keys?
3. Are flow records compact enough for direct JSON output, or should the MVP only emit aggregates?
4. Which rule/policy keys are safe to read and useful for explanation?
5. Can we produce useful snapshots without exposing local IPs, MACs, domains, or device names by default?

## Preferred MVP Access Path

SSH into the Firewalla box and run read-only Redis queries. This requires local network reachability and SSH credentials, not an MSP API token.
