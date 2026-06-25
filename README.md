中文版本：见 [README.zh.md](README.zh.md).

# Firewalla Local Skill

AI-first CLI and root skill for local-first, read-only visibility and analysis of a Firewalla device. Runs entirely on your own machine over SSH — no cloud relay, no MSP API required.

**Read-only by design.** The tool issues only read-only Redis commands against your Firewalla. It never modifies firewall rules, policies, Redis state, iptables, or system services.

**Privacy-first.** All JSON artifacts are private by default. When you need to share artifacts (docs, issues, PRs), use `--privacy redacted` to replace real values with stable anonymous tokens while preserving schema keys for joins.

## Installation

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Quick Start

Create `.firewalla.local.json` (git-ignored):

```json
{"ssh_alias": "firewalla"}
```

Or use environment variables: `FIREWALLA_SSH_ALIAS`, `FIREWALLA_HOST`, `FIREWALLA_SSH_USER`, `FIREWALLA_SSH_KEY`.

All commands are **dry-run by default**. Add `--execute` to connect to Firewalla.

```bash
firewalla-skill health --execute
firewalla-skill devices --json --all --execute
firewalla-skill alarms --json --since-days 7 --include-archive --all --execute
firewalla-skill snapshot --execute
```

## Privacy Modes

| Mode | Behavior |
|------|----------|
| `private` (default) | Real values preserved. Artifacts stay in ignored paths. |
| `redacted` | Values replaced with stable tokens such as `<mac:0123456789>`, `<ip:0123456789>`, and `<bname:0123456789>`. Schema keys unchanged. Tokens are deterministic per value, so joins work. |

Use `--privacy redacted` when creating artifacts for public docs, issues, or PRs.

## Security Model

- SSH connection to Firewalla, authenticated with key.
- Read-only Redis command allowlist: `SCAN`, `HGETALL`, `ZRANGE`, `ZREVRANGE`, `ZRANGEBYSCORE`, `ZREVRANGEBYSCORE`, `ZCARD`, `GET`, `MGET`, `PING`.
- No Redis writes. No iptables changes. No policy changes. No service file changes.
- Dry-run by default; `--execute` required for live connections.

## Commands

| Command | Purpose |
|---------|---------|
| `health` | Hostname, uptime, Redis PING |
| `devices --json --all` | Device inventory from `host:mac:*` |
| `alarms --json --since-days N --all` | Active and archived alarms with time-based windowing |
| `flows` | Recent flow records by system or selected MAC |
| `snapshot` | Bounded AI-readable snapshot |
| `dump-format` | Local raw + redacted format dumps |
| `summary` | Deterministic JSON brief from snapshot or live read |
| `cluster` | Alarm actionability clusters |
| `device-summary` | Current-vs-historical device inventory buckets |
| `attribute` | Source-aware alarm-to-device attribution |
| `resolve-device` | Diagnostic helper for redacted artifacts |

## Alarm Attribution

Attribution uses source/client fields only: `device`, `p.device.id`, `p.device.ip`, `p.device.mac`, `p.device.name`, `p.flows[].device`. Infrastructure/interface fields like `p.intf.*` are excluded; they describe Firewalla observation interfaces, not client sources.

Device display IDs prefer current operational names (`name`, `dhcpName`, `localDomain`, `sambaName`, `ssdpName`). Stale discovery aliases (`bname`, `bonjourName`, `pname`) are secondary. `identity_conflict` is emitted when operational names disagree with aliases.

## Alert Guidance

- Do not create traffic/network rules merely to suppress alert noise.
- Game/video alarms are typically notification noise.
- Large upload and abnormal bandwidth alarms need device and time context.
- UPNP, BRO_NOTICE, DUAL_WAN, and INTEL alerts should be reviewed before ignoring.
- Prefer official/app-supported alarm tuning or local Encipher API over direct Redis writes.

## Ignored Paths

These paths are git-ignored and contain real local data:

- `reports/`
- `.firewalla_dumps/`
- `.firewalla.local.json`
- `.env`
- SSH config files

## Tests

```bash
# Offline tests
python -m pytest -q -m "not live"

# Live tests (requires Firewalla connection)
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

## License

MIT
