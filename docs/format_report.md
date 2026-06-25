# Firewalla Local Redis Format Report

## Bottom Line

The SSH + Redis path is enough for a useful read-only MVP. A bounded live dump confirmed that Firewalla local Redis exposes the four P0 surfaces we care about: box health, device inventory, active alarms, and recent system flows.

Raw live captures remain in `.firewalla_dumps/` and are git-ignored. This report only describes sanitized field shapes.

## P0 Surfaces Confirmed

### Box health

Confirmed fields from CLI collection:

1. `hostname`: box hostname, redacted in public artifacts
2. `uptime`: uptime/load string
3. `redis_ping`: Redis availability probe, expected `PONG`

Product value: tells the agent whether the Firewalla data source is reachable and roughly healthy before interpreting alarms or flows.

### Device inventory

Source key pattern: `host:mac:*`.

Representative sanitized fields:

1. identity-like fields: `mac`, `bname`, `pname`, `dhcpName`, `localDomain`, `userLocalDomain`
2. network fields: `ipv4`, `ipv4Addr`, `ipv6Addr`, `intf`, `intf_uuid`, `intf_mac`
3. timing fields: `firstFoundTimestamp`, `lastActiveTimestamp`, `bnameCheckTime`
4. classification fields: `detect`, `dtype`, `macVendor`, `lastFrom`
5. behavior/config hints: `spoofing`, `spoofingTime`, `stpPort`

Product value: device records are the join table for almost every other question. They can support new-device detection, active-device summaries, and device-class-aware alarm interpretation.

Privacy rule: redact `mac`, IP fields, name-like fields, local domains, DHCP names, vendor strings when they can identify a household device, and interface MACs.

### Active alarms

Source keys:

1. `alarm_active` for active alarm IDs
2. `_alarm:<aid>` for alarm payload
3. `_alarmDetail:<aid>` for detailed context

Representative sanitized fields:

1. `aid`: alarm ID
2. `type`: alarm type, for example `ALARM_GAME` or `ALARM_ABNORMAL_BANDWIDTH_USAGE`
3. `state`: alarm state, for example `active`
4. `timestamp` and `alarmTimestamp`
5. `device`: device name-like field, redacted
6. `message`: human-readable alarm message, redacted because it often embeds device names/domains
7. detail payloads: alarm-specific structures, such as upload/download time series or remote service names

Product value: alarms are Firewalla's already-filtered anomaly layer. They should be the first user-facing summary because they are higher signal than raw flows.

Privacy rule: redact device, message, domains, IPs, IPv6, and any alarm details that directly identify endpoints.

### Recent flows

Initial source key: `flow:conn:system`.

Representative sanitized fields:

1. timing: `ts`, `_ts`, sorted-set score
2. direction and protocol: `fd`, `pr`, `dp`, `sp`
3. endpoints: `lh`, `sh`, `dh`, `mac`, all redacted
4. byte/count metrics: `ob`, `rb`, `ct`, `du`
5. interface/tag fields: `intf`, `oIntf`, `dTags`, `ltype`
6. application metadata: `af` with domain/IP/protocol hints, redacted

Product value: flows are necessary for answering what changed and what generated traffic. They are P0 because the feature must exist, even if the user later chooses not to inspect detailed flows.

Privacy rule: default output should be bounded and redacted. Full raw flow export should remain local-only.

## First Snapshot Shape

The current CLI emits this top-level shape:

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

This shape is intentionally compact. It gives an agent enough structure to reason over the current network state while keeping raw Firewalla records out of public artifacts.

## Design Implications

1. `devices` should become the canonical local entity table.
2. `alarms` should drive first-pass narrative summaries because they are high-signal and already classified by Firewalla.
3. `flows` should stay bounded by default and should grow aggregate summaries before full-detail export.
4. `snapshot` should remain redacted by default; raw local dump should remain a separate `dump-format` workflow.
5. Future rule/policy reads should join against device and alarm context, but write operations remain out of MVP.
