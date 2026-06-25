中文版本：见 [rfc.zh.md](rfc.zh.md).

# Firewalla Local Skill — Architecture

## Overview

The tool runs as a local Python CLI that connects to a Firewalla device over SSH, issues read-only Redis commands, and produces structured JSON artifacts on the local filesystem. It has no server component, no daemon, and no persistent state beyond the artifacts it writes.

```
User Machine                          Firewalla
┌─────────────┐     SSH + key       ┌──────────┐
│  CLI (Python) │ ◄──────────────► │  Redis     │
│               │   read-only cmds   │            │
│  JSON artifacts│                   │            │
│  → filesystem  │                   └──────────┘
└─────────────┘
```

## Transport Layer

SSH connection is configured through one of three mechanisms, checked in order:
1. `.firewalla.local.json` — local config file with `ssh_alias` key.
2. `FIREWALLA_SSH_ALIAS` environment variable — SSH config alias.
3. `FIREWALLA_HOST` / `FIREWALLA_SSH_USER` / `FIREWALLA_SSH_KEY` environment variables — direct connection parameters.

The CLI invokes the system `ssh` command in batch mode and runs `redis-cli --raw` on the Firewalla. Connection lifecycle is per command: each invocation starts SSH, runs a bounded read pipeline, captures stdout/stderr, and exits.

## Read-Only Allowlist

Before any Redis command is issued, the CLI checks the command against a hardcoded allowlist:

```
SCAN, HGETALL, ZRANGE, ZREVRANGE, ZRANGEBYSCORE, ZREVRANGEBYSCORE, ZCARD, GET, MGET, PING
```

Any command outside this list is rejected with an error before SSH transmission. This is a code-level enforcement, not a Firewalla-side ACL. It guarantees that even if the Firewalla Redis instance were misconfigured to be writable, the tool cannot issue writes.

## Dry-Run Guard

The CLI is dry-run by default. When `--execute` is absent:
- SSH connection is not established.
- Redis commands are printed to stdout instead of sent.
- Artifact files are not written.

This provides a safe preview path. `--execute` must be explicitly passed to perform any live operation.

## Collector Contracts

Each command is backed by a collector module that defines:
- Which Redis keys to read.
- Which Redis commands to issue.
- How to transform raw Redis responses into the output JSON schema.
- Privacy mode handling (identity function vs. redaction).

Collectors are stateless functions. They build read-only remote Redis commands, parse `redis-cli --raw` output, apply command-level parameters and privacy mode, and return JSON-serializable objects.

### Alarm Time Windowing

The alarm collector reads `alarm_active`, then scans `alarm_archive` (a zset) with `--candidate-limit` bounding the scan range. For each candidate, it fetches `_alarm:<aid>` and `_alarmDetail:<aid>`. Time filtering uses the payload-level `timestamp` and `alarmTimestamp` fields, not the zset score. This avoids clock-skew between Redis zset score semantics and the alarm's own timestamp. `--since-days` is converted to a Unix timestamp cutoff; only alarms with payload timestamps after the cutoff are included.

### Device Identity Resolution

The device collector reads all `host:mac:*` keys. For each device, it extracts both operational names and discovery aliases. The `identity_conflict` flag is set when the preferred operational name (highest-precedence non-null name from `name`, `dhcpName` etc.) differs from any discovery alias. This flag is emitted in the output rather than being resolved automatically, because the correct resolution depends on operator knowledge.

## Privacy Modes

Privacy transformation is applied at the collector output level, not at the Redis read level. The collector always reads raw values. The privacy module then scans the output dictionary and either passes it through (`private`) or redacts it (`redacted`).

### Redaction Algorithm

1. Parse the JSON output tree.
2. For each string leaf value, match against known patterns (MAC address, IP address, domain, device name token).
3. If matched, replace with `<type:hash>` where hash is a deterministic SHA-256 prefix of the value (first 10 hex chars).
4. Schema keys (dictionary keys) are never modified.
5. The same value always produces the same token, enabling joins across artifacts.

### Redaction Token Types

| Token prefix | Matched pattern |
|-------------|-----------------|
| `<mac:...>` | MAC address |
| `<ip:...>` | IPv4/IPv6 address |
| `<bname:...>` | Device name / hostname |
| `<domain:...>` | Domain name / FQDN |
| `<message:...>` | Alarm message content |

## Alarm Attribution Semantics

Attribution maps alarms to devices. The attribution module only considers source/client fields from the alarm payload:

- `device` (top-level device identifier)
- `p.device.id`, `p.device.ip`, `p.device.mac`, `p.device.name`
- `p.flows[].device`

Infrastructure fields (`p.intf.*`, interface identifiers, observation metadata) are excluded. These fields describe which Firewalla interface observed the traffic, not which client device generated it. Including them would produce incorrect attributions where network infrastructure appears to be the alarm source.

In `private` mode, the attribution output includes a `device_summary` field with human-readable device identity information from the device inventory. In `redacted` mode, this field is tokenized.

## Artifact Schemas

Collection commands include command-specific data plus a `collection` metadata object:

```json
{
  "alarms": [],
  "collection": {
    "source": "ssh_redis",
    "privacy": "private",
    "private": true,
    "redacted": false,
    "since_days": 3,
    "include_archive": true,
    "candidate_limit": 2000
  }
}
```

Analysis commands such as `cluster`, `device-summary`, `attribute`, and `active-devices` read these JSON artifacts and preserve their privacy metadata in their own output.

### Active-Device Investigation Schema

`active-devices` is a local artifact join. It reads a device inventory and, optionally, an alarm artifact. It does not connect to Firewalla. The command filters devices by `lastActiveTimestamp` using `--since-days`, attaches alarm context through the same source-only attribution semantics used by `attribute`, and emits `investigation_indicators` for triage.

```json
{
  "active_devices": [
    {
      "device_id": "Example Device",
      "last_active_timestamp": 2000000000,
      "last_active_age_days": 0.01,
      "device_summary": {},
      "alarm_context": {"alarm_count": 1, "categories": {}, "types": {}},
      "investigation_indicators": ["network_security_alarm"]
    }
  ],
  "summary": {
    "active_device_count": 1,
    "indicator_counts": {}
  }
}
```

## Safety Boundaries

Hard boundaries enforced in code:

1. **Read-only Redis.** The allowlist is checked in the Redis command dispatch layer. No code path can bypass it.
2. **Dry-run default.** `--execute` is a required flag for any live operation. Absent the flag, no SSH connection is opened.
3. **No iptables, no policy changes, no service files.** The tool has no code paths for these operations.
4. **No data exfiltration.** All artifacts are written to local filesystem paths. No network upload.
5. **Git-ignored private data.** `.gitignore` covers `reports/`, `.firewalla_dumps/`, `.firewalla.local.json`, `.env`, and SSH config patterns.

## Future Write Path Constraints

Any future write functionality must be introduced through a separate RFC, require explicit user opt-in at both configuration and command-invocation level, and prefer official Firewalla mechanisms (app-supported alarm/notification tuning, local Encipher API) over direct Redis writes. Direct Redis writes carry risk of desynchronizing the Firewalla software's internal state assumptions.

## Testing Architecture

Tests are organized into two tiers:

**Offline tests** (`-m "not live"`): Run without Firewalla connectivity. Cover dry-run behavior, allowlist enforcement, mutation rejection, config parsing, privacy redaction logic, timestamp filtering, schema key preservation, alarm attribution rules, identity conflict handling, and JSON schema conformance. Use mock Redis responses.

**Live tests** (`-m live`): Gated by `FIREWALLA_LIVE_TESTS=1`. Require a live Firewalla on the local network with SSH access configured. Cover all read-only commands end-to-end. Do not modify any Firewalla state.

## Dependencies

- **Python 3.11+** — runtime.
- **pytest** — test framework.
- **uv** — package management and venv.
