# Firewalla Local Skill — Test Plan

## Test Tiers

### Offline Tests

Run without Firewalla connectivity:

```bash
python -m pytest -q -m "not live"
```

### Live Tests

Gated by `FIREWALLA_LIVE_TESTS=1`. Require a live Firewalla on the local network with SSH access configured:

```bash
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

## Coverage Areas

### Dry-Run & Execution Guard
- All commands default to dry-run; no SSH connection opened without `--execute`.
- Dry-run output matches expected Redis command sequence, formatted for human review.
- `--execute` triggers live SSH connection and Redis interaction.

### Read-Only Allowlist
- All allowlisted commands (`SCAN`, `HGETALL`, `ZRANGE`, `ZREVRANGE`, `ZRANGEBYSCORE`, `ZREVRANGEBYSCORE`, `ZCARD`, `GET`, `MGET`, `PING`) pass through to Redis.
- Any command outside the allowlist is rejected at the dispatch layer before reaching SSH.
- Write-like commands (`SET`, `DEL`, `HSET`, `ZADD`, `CONFIG`, `FLUSHDB`, `SHUTDOWN`) are rejected.

### Mutation Rejection
- No Redis key is created, modified, or deleted by any implemented command.
- No Firewalla policy, iptables rule, or service file is altered.

### Configuration
- `.firewalla.local.json` is parsed correctly with valid `ssh_alias`.
- Missing config file falls back to environment variables or normal SSH target resolution.
- Environment variable fallback: `FIREWALLA_SSH_ALIAS` overrides config; `FIREWALLA_HOST`/`FIREWALLA_SSH_USER`/`FIREWALLA_SSH_KEY` provide direct connection when no alias is present.

### Privacy Mode
- `private` mode preserves all values unchanged.
- `redacted` mode replaces MAC addresses, IP addresses, device names, domains, and alarm messages with token format `<type:hash>`.
- Schema keys are never modified in redacted mode.
- Redaction is deterministic: same input produces same token on repeated calls.
- Tokens from one artifact can be joined with tokens in another (same value maps to same token across commands).

### Timestamp Filtering
- `alarms --since-days N` includes alarms with payload `timestamp` or `alarmTimestamp` within the window.
- Alarms outside the window are excluded.
- Time filtering uses payload timestamps, not Redis zset scores.
- Edge cases: zero days (no alarms returned), far-future `--since-days` (all alarms returned).

### Device Collection
- `devices --json --all` returns full `host:mac:*` inventory.
- Each device includes all operational identifiers and discovery aliases.
- Device count in output matches expected count from direct Redis key enumeration.

### Alarm Collection
- `alarms --json --all` includes both active and archived alarms.
- `--since-days` correctly bounds the result set.
- `--candidate-limit` bounds the number of archive entries scanned.
- `--include-archive` controls archive inclusion independently of active alarms.

### Alarm Attribution
- `attribute` uses source/client fields only: `device`, `p.device.id`, `p.device.ip`, `p.device.mac`, `p.device.name`, `p.flows[].device`.
- Infrastructure fields (`p.intf.*`) are excluded from attribution.
- Each attributed alarm links to exactly one output device record.
- `device_summary` is present in private mode and contains readable device identity.
- `device_summary` is tokenized in redacted mode.

### Identity Conflict
- `identity_conflict` flag is emitted when a device's operational name differs from its discovery alias.
- No conflict when all names are consistent.
- Conflict flag includes both the operational name and the conflicting alias for diagnosis.

### Snapshot & Summary
- `snapshot` produces bounded JSON within size constraints suitable for direct LLM context insertion.
- `summary` produces deterministic output; same input yields identical summary.
- `snapshot --privacy redacted` applies redaction to the snapshot content.

### Dump Format
- `dump-format` writes formatted output to `.firewalla_dumps/`.
- Raw format preserves all values.
- Redacted format applies tokenization.
- Output files are self-documenting with schema indicators.

### Cluster
- `cluster` assigns each alarm to one of: `routine_noise`, `review_bandwidth`, `review_network_security`, `unknown_review`.
- Cluster assignment is deterministic for the same alarm payload.
- All alarms in a given cluster share structural characteristics matching the cluster definition.

### Device Summary
- `device-summary` reports current-vs-historical activity buckets and device type counts.
- Devices with missing detect type are counted explicitly.
- Device type categorization preserves Firewalla's own detect type values.

### Active Devices
- `active-devices` filters devices by `lastActiveTimestamp` and `--since-days`.
- Devices outside the window and devices missing activity timestamps are counted in `excluded_counts`.
- When an alarm artifact is provided, source-attributed alarm categories and types are attached to each matching active device.
- Duplicate device display names remain distinct through record-level `device_key` output and record-index attribution.
- Investigation indicators are emitted for identity conflicts, missing metadata, bandwidth alarms, network-security alarms, and unknown alarm types.

### Resolve Device
- `resolve-device` accepts a redacted token and returns matching device fields from the current device inventory.
- Returns an empty result when no device matches the token.
- Works with tokens of type `<mac:...>`, `<ip:...>`, and `<bname:...>`.

### Live Read-Only Commands
- All commands execute against a live Firewalla without errors.
- No state mutation on the Firewalla.
- Output conforms to documented JSON schemas.

### Edge Cases
- Empty device inventory (rare but possible on newly provisioned boxes).
- No alarms in the requested time window.
- Firewalla unreachable (SSH timeout, wrong key, network down) produces a clear error with actionable message.
- Very large alarm archives with `--candidate-limit` bounding.
- Devices with partial or missing fields — output gracefully handles null fields without crashing.
