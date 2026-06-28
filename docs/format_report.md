# Firewalla Local Redis Format Report

## Bottom Line

The SSH + Redis path is enough for a useful read-only MVP. A bounded live dump confirmed that Firewalla local Redis exposes the four P0 surfaces we care about: box health, device inventory, active alarms, and recent system flows.

Raw live captures remain in `.firewalla_dumps/` and are git-ignored. This report describes field shapes without including real household values.

## P0 Surfaces Confirmed

### Box health

Confirmed fields from CLI collection:

1. `hostname`: box hostname
2. `uptime`: uptime/load string
3. `redis_ping`: Redis availability probe, expected `PONG`

Product value: tells the agent whether the Firewalla data source is reachable and roughly healthy before interpreting alarms or flows.

### Device inventory

Source key pattern: `host:mac:*`.

Representative fields:

1. identity-like fields: `mac`, `bname`, `pname`, `dhcpName`, `localDomain`, `userLocalDomain`
2. network fields: `ipv4`, `ipv4Addr`, `ipv6Addr`, `intf`, `intf_uuid`, `intf_mac`
3. timing fields: `firstFoundTimestamp`, `lastActiveTimestamp`, `bnameCheckTime`
4. classification fields: `detect`, `dtype`, `macVendor`, `lastFrom`
5. behavior/config hints: `spoofing`, `spoofingTime`, `stpPort`

Product value: device records are the join table for almost every other question. They can support new-device detection, active-device summaries, and device-class-aware alarm interpretation.

Artifact rule: preserve these values in local artifacts; use fake examples in public material.

### Active alarms

Source keys:

1. `alarm_active` for active alarm IDs
2. `_alarm:<aid>` for alarm payload
3. `_alarmDetail:<aid>` for detailed context

Representative fields:

1. `aid`: alarm ID
2. `type`: alarm type, for example `ALARM_GAME` or `ALARM_ABNORMAL_BANDWIDTH_USAGE`
3. `state`: alarm state, for example `active`
4. `timestamp` and `alarmTimestamp`
5. `device`: device name-like field
6. `message`: human-readable alarm message, often embedding device names/domains
7. detail payloads: alarm-specific structures, such as upload/download time series or remote service names

Product value: alarms are Firewalla's already-filtered anomaly layer. They should be the first user-facing summary because they are higher signal than raw flows.

Artifact rule: preserve endpoint-identifying values in local artifacts because they are needed for attribution and investigation.

### Recent flows

Initial source key: `flow:conn:system`.

Representative fields:

1. timing: `ts`, `_ts`, sorted-set score
2. direction and protocol: `fd`, `pr`, `dp`, `sp`
3. endpoints: `lh`, `sh`, `dh`, `mac`
4. byte/count metrics: `ob`, `rb`, `ct`, `du`
5. interface/tag fields: `intf`, `oIntf`, `dTags`, `ltype`
6. application metadata: `af` with domain/IP/protocol hints

Product value: flows are necessary for answering what changed and what generated traffic. They are P0 because the feature must exist, even if the user later chooses not to inspect detailed flows.

Artifact rule: flow output is local raw data and should remain in ignored local artifact paths.

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
    "local_raw": true
  }
}
```

This shape is intentionally compact. It gives an agent enough structure to reason over the current network state while keeping live Firewalla records in local ignored artifacts.

## Design Implications

1. `devices` should become the canonical local entity table.
2. `alarms` should drive first-pass narrative summaries because they are high-signal and already classified by Firewalla.
3. `flows` should stay bounded by default and should grow aggregate summaries before full-detail export.
4. `snapshot` should remain bounded by default. Raw local dump remains a separate `dump-format` workflow.
5. Future rule/policy reads should join against device and alarm context, but write operations remain out of MVP.
