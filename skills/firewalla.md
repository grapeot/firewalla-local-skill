---
name: firewalla-skill
description: Local-first, read-only Firewalla visibility and analysis through the firewalla-skill CLI.
---

# Firewalla Skill

Use this skill when the user asks about Firewalla network state, device inventory, alarms, flows, or AI-assisted network analysis.

## Core Rules

- Run commands from `adhoc_jobs/firewalla_skill/`.
- Activate the project environment first: `source .venv/bin/activate`.
- The CLI command is `firewalla-skill`.
- Live collection is dry-run by default; add `--execute` only when you intend to query the user's Firewalla.
- The integration is read-only. Do not write Redis, change iptables, alter Firewalla policies, or edit service files.
- Local JSON output is private by default and may contain real names, IPs, MACs, domains, and alarm messages.
- Use `--privacy redacted` for artifacts that may be shared in public docs, issues, PRs, screenshots, or messages.

## Local Configuration

Prefer a git-ignored `.firewalla.local.json`:

```json
{"ssh_alias": "firewalla"}
```

The CLI also supports `FIREWALLA_SSH_ALIAS`, or direct `FIREWALLA_HOST`, `FIREWALLA_SSH_USER`, and `FIREWALLA_SSH_KEY` environment variables.

## Collection Workflow

Start with health:

```bash
firewalla-skill health --execute
```

Collect full local report inputs into ignored `reports/` files:

```bash
firewalla-skill devices --execute --all --json --output reports/devices_all_latest.json
firewalla-skill alarms --execute --since-days 3 --include-archive --all --json --output reports/alarms_last3d_latest.json
```

Create public-safe versions only when needed:

```bash
firewalla-skill devices --execute --all --json --privacy redacted --output reports/devices_all_redacted.json
firewalla-skill alarms --execute --since-days 3 --include-archive --all --json --privacy redacted --output reports/alarms_last3d_redacted.json
```

Analyze collected artifacts locally:

```bash
firewalla-skill device-summary --devices reports/devices_all_latest.json --output reports/devices_summary_latest.json
firewalla-skill cluster --alarms reports/alarms_last3d_latest.json --output reports/alarms_last3d_cluster.json
firewalla-skill attribute --alarms reports/alarms_last3d_latest.json --devices reports/devices_all_latest.json --output reports/alarm_device_attribution_latest.json
firewalla-skill active-devices --devices reports/devices_all_latest.json --alarms reports/alarms_last3d_latest.json --since-days 3 --output reports/active_devices_last3d.json
```

Use snapshots for bounded AI context:

```bash
firewalla-skill snapshot --execute --limit 5 --output reports/snapshot_latest.json
firewalla-skill summary --input reports/snapshot_latest.json --output reports/summary_latest.json
```

Use `dump-format` only for local schema inspection:

```bash
firewalla-skill dump-format --execute --limit 5
```

It writes raw and redacted bounded dumps to `.firewalla_dumps/`, which is git-ignored.

## Attribution Rules

For alarm-to-device attribution, trust source/client fields only:

- `device`
- `p.device.id`
- `p.device.ip`
- `p.device.mac`
- `p.device.name`
- `p.flows[].device`

Ignore infrastructure/interface fields such as `p.intf.*`; they describe where Firewalla observed traffic, not which client caused the alarm.

When reading `attribute` output, use `device_summary` first. Device display names prefer current operational names: `name`, `dhcpName`, `localDomain`, `sambaName`, `ssdpName`. Treat `bname`, `bonjourName`, and `pname` as aliases. If `identity_conflict` is present, report both the current name and stale aliases instead of silently choosing the alias.

## Alert Guidance

- Do not recommend traffic or network rules only to reduce alert noise.
- Game and video alarms are usually visibility or notification noise.
- Large upload and abnormal bandwidth alarms need device and time context.
- UPNP, BRO_NOTICE, DUAL_WAN, and INTEL alerts should be reviewed before ignoring.
- Future write operations require a separate RFC and explicit opt-in. Prefer official Firewalla app alarm/notification tuning or local Encipher API over direct Redis writes.

## Redacted Token Lookup

Use `resolve-device` only for redacted artifacts or diagnostics:

```bash
firewalla-skill resolve-device --execute --token '<bname:aaaaaaaaaa>' --output reports/device_resolve_latest.json
firewalla-skill resolve-device --execute --token '<bname:aaaaaaaaaa>' --include-private --output reports/private_device_resolve_latest.json
```

Private attribution reports should already include readable device summaries, so token lookup is usually unnecessary for normal local analysis.

## Tests

Offline tests:

```bash
python -m pytest -q -m "not live"
```

Opt-in live tests:

```bash
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

Live tests must remain read-only.
