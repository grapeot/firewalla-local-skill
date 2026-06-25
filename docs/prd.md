中文版本：见 [prd.zh.md](prd.zh.md).

# Firewalla Local Skill — Product Requirements

## Goals

Provide a local-first, AI-friendly CLI for read-only visibility into a Firewalla device. The primary use case is user-authorized AI analysis on the user's own machine. No cloud dependency. No paid MSP API required.

The tool produces structured JSON artifacts that an AI agent can consume directly — device inventory, alarm history with attribution, flow records, and bounded snapshots of system state. These artifacts enable automated analysis without any write access to the Firewalla.

## Users

- Firewalla owners who want AI-assisted network visibility without sending data to cloud services.
- AI agents running on the user's local machine, consuming structured Firewalla data for analysis, alert triage, and network diagnostics.

## Scope

- SSH-based access to Firewalla Redis.
- Read-only Redis command execution with a strict allowlist.
- JSON artifact generation across the CLI command set: health, devices, alarms, flows, snapshot, dump-format, summary, cluster, device-summary, attribute, active-devices, and resolve-device.
- Two privacy modes: `private` (real values, private paths) and `redacted` (stable anonymous tokens, shareable).
- Time-bounded alarm collection with configurable candidate limits.
- Source-aware device attribution with identity conflict detection.
- Active-device investigation views that join inventory, recent alarms, identity metadata, and triage indicators.
- Offline and live test suites.
- `resolve-device` diagnostic tool for redacted artifacts.

## Non-Goals

- Firewalla configuration or policy changes.
- Redis writes, iptables modifications, or service file changes.
- Cloud-hosted analysis or data exfiltration.
- Real-time monitoring or persistent daemon mode.
- MSP API integration (optional and paid-gated; the tool acknowledges it but does not depend on it).
- Historical device state reconstruction beyond what Redis keys directly expose.

## Data Model

### Devices

Stored under `host:mac:*` keys in Firewalla Redis. Each device carries operational identifiers (`name`, `dhcpName`, `localDomain`, `sambaName`, `ssdpName`) and discovery aliases (`bname`, `bonjourName`, `pname`). MAC address, IP assignment, DHCP fingerprint, and vendor metadata are included where available.

### Alarms

Three key spaces:
- `alarm_active` — current unresolved alarms.
- `alarm_archive` — resolved alarm records, stored as zset.
- `_alarm:<aid>` and `_alarmDetail:<aid>` — per-alarm payload keys with structured JSON.

Time windowing uses the payload fields `timestamp` and `alarmTimestamp`, not the Redis zset score. A `--candidate-limit` parameter bounds the number of archive entries scanned.

### Flows

Recent flow records keyed by system or device MAC, exposing connection metadata, byte counts, application classification, and port information.

### Reports

Each command produces deterministic JSON output. The `snapshot` command produces a bounded AI-readable aggregate suitable for passing directly into an LLM context. The `summary` command computes a deterministic brief from either a snapshot or a live bounded read.

The `active-devices` command reads local device and alarm artifacts and produces a last-N-days investigation view. It includes only devices whose `lastActiveTimestamp` falls inside the requested window, joins source-attributed alarm context when provided, and emits triage indicators for identity conflicts, missing metadata, bandwidth alarms, network-security alarms, and unknown alarm types.

## Device Identity Semantics

Device display ID resolution prefers current operational names over stale discovery aliases. The precedence chain:
1. `name` — current name in Firewalla
2. `dhcpName` — DHCP-supplied hostname
3. `localDomain` — mDNS/LLMNR local domain
4. `sambaName` — Samba/NetBIOS name
5. `ssdpName` — SSDP-discovered name
6. `bname` / `bonjourName` / `pname` — stale discovery aliases (secondary)

When operational names disagree with aliases (e.g., device renamed but old Bonjour name still cached), the tool emits an `identity_conflict` flag rather than silently picking one side.

## Privacy Model

**Private mode (default):** Artifacts contain real device names, IPs, MACs, domains, and alarm messages. These artifacts live in git-ignored paths (`reports/`, `.firewalla_dumps/`, `.firewalla.local.json`, `.env`). They never enter the repository.

**Redacted mode:** All identifiable values are replaced with stable, deterministic tokens prefixed by type (`<mac:...>`, `<ip:...>`, `<bname:...>`, `<domain:...>`). Schema keys are preserved verbatim. Token mapping is deterministic per value — the same MAC always maps to the same token, allowing cross-record joins on redacted artifacts. Redacted mode is for sharing in docs, issues, and PRs.

## Acceptance Criteria

- All commands execute successfully in dry-run mode without a Firewalla connection.
- All commands execute successfully against a live Firewalla with `--execute`.
- `devices` returns a complete device inventory with all operational identifiers and aliases.
- `alarms` returns active and archived alarms within the specified time window, bounded by candidate limit.
- `alarms` time-filtering uses payload timestamps, not zset scores.
- `attribute` correctly separates source/client fields from infrastructure/interface fields.
- `active-devices` emits active devices with readable identity summaries, alarm context, and investigation indicators.
- `identity_conflict` is emitted when operational names disagree with discovery aliases.
- `redacted` mode produces deterministic tokens: same input yields same token, schema keys are unchanged.
- Read-only allowlist is enforced: any write command is rejected.
- Offline tests pass without Firewalla connectivity.
- Live tests pass with `FIREWALLA_LIVE_TESTS=1`.
- Public repository contains zero real local data.
