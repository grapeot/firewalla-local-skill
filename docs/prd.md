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
3. Provide stable read-only CLI commands that emit private-by-default local JSON snapshots, with an explicit redacted mode for sharing.
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
6. Local reports are useful to the user without reverse-mapping anonymous tokens by default.

## Product Value Hypothesis

The useful product is not a raw Firewalla database browser. The useful product is an AI-readable network situation snapshot: what changed, what looks risky, which devices matter, what alerts deserve attention, and whether the box/network itself is healthy.

The CLI should therefore prioritize facts that help an agent answer household-network questions:

1. What devices exist, and which ones are active or newly seen?
2. Which alarms are pending or active, and which devices/entities caused them?
3. Which devices or flows changed recently in a way that looks unusual?
4. Is the Firewalla box healthy enough that its observations are trustworthy?
5. What policies/rules exist, but only as read-only context for now?
6. Which small set of devices explains most alert volume?

## Information Priority

### P0: Must understand first

These are the first data surfaces to dump and normalize.

1. Device inventory from `host:mac:*`: device identity, last active time, IP mappings, vendor/type/name-like fields, online/offline hints, and group/user relationships if visible.
2. Active/recent alarms from `alarm_active`, `alarm_archive`, `_alarm:<aid>`, and `_alarmDetail:<aid>`: alarm type, payload timestamp, device/entity, severity-like fields, destination/domain/IP fields, and status. Time windows must use payload `timestamp` / `alarmTimestamp`, not Redis sorted-set score.
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
4. Which fields are sensitive and must be redacted before sharing outside the local machine?
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
    "privacy": "private",
    "redacted": false
  }
}
```

This is intentionally smaller than Firewalla's raw data. The product should preserve fields needed for AI reasoning. Local output defaults to `private`; users can request `--privacy redacted` when preparing public-safe artifacts.

## Device Cleanup And Attribution

The MVP should treat device cleanup and alarm attribution as first-class read-only analysis. Local attribution should show readable device summaries, including names, IPs, MACs, vendor/type, and last-active fields when available. Redacted artifacts must preserve stable anonymous tokens, such as `<mac:...>` or `<bname:...>`, so public-safe reports can still join devices and alarms without exposing raw identifiers.

Required outputs:

1. current-vs-historical device buckets by last active timestamp
2. device type distribution and missing classification count
3. alarm counts attributed to source devices using Firewalla source fields, not arbitrary token overlap
4. top noisy devices and top review-worthy devices

Alarm attribution must preserve Firewalla payload semantics. Source/client fields such as `device`, `p.device.id`, `p.device.ip`, `p.device.mac`, `p.device.name`, and `p.flows[].device` are candidates for device attribution. Infrastructure/interface fields such as `p.intf.id`, `p.intf.name`, `p.intf.subnet`, and `p.intf.subnet6` describe where Firewalla observed the event; they must not cause an alarm to be attributed to the Firewalla gateway itself.

`resolve-device` is a diagnostic and redacted-artifact lookup helper. It is useful when a user wants to map an anonymous token to a local Firewalla App-visible record, but normal private reports should already include readable device identity. If attribution frequently points to Firewalla itself, the parser is likely using the wrong alarm fields.

## Open Questions

MSP Lite shows API/Integration as locked. Current public pricing indicates API/Integration starts at Professional. The project should not require the paid MSP API for MVP.

Data questions to answer with the format dump:

1. Which host fields reliably identify a device in private mode and in redacted mode?
2. Are alarm payloads self-contained, or do they require joining host/flow/detail keys?
3. Are flow records compact enough for direct JSON output, or should the MVP only emit aggregates?
4. Which rule/policy keys are safe to read and useful for explanation?
5. Can we produce useful redacted snapshots for sharing while keeping local snapshots private-by-default?

## Preferred MVP Access Path

SSH into the Firewalla box and run read-only Redis queries. This requires local network reachability and SSH credentials, not an MSP API token.
