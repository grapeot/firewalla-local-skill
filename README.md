# Firewalla Local Skill

AI-first skill and CLI for local-first, read-only Firewalla visibility.

## Status

Early but runnable CLI. The implementation target is local-first read-only access for Firewalla Gold-class boxes. The official Firewalla MSP API remains a paid optional path.

## Privacy

This repository is designed to be publishable. Operational privacy rules live in `AGENTS.md` and `skills/firewalla.md`.

## Install This Skill Into An AI Workspace

Give an AI coding agent this repo URL and ask it to install the public root skill:

```text
Install the Firewalla Local Skill from this repository. Start from my workspace AGENTS.md or CLAUDE.md, follow any WORKSPACE.md routing, and add a pointer to skills/firewalla.md in the workspace skill discovery chain. If the workspace has rules/skills/INDEX.md or skills/INDEX.md, update that index; otherwise add a short pointer in AGENTS.md or CLAUDE.md.
```

Expose exactly one public root skill: `skills/firewalla.md`. Keep private SSH aliases, local IPs, tokens, and device names in local config, `.env`, or workspace-private overlays.

## Credential Model

MVP local-first environment variables:

- `FIREWALLA_SSH_ALIAS`: optional SSH config alias, for example `firewalla`
- `FIREWALLA_HOST`: local IP or DNS name of the Firewalla box
- `FIREWALLA_SSH_USER`: SSH username, usually `pi`
- `FIREWALLA_SSH_KEY`: path to a local SSH private key

If `FIREWALLA_SSH_ALIAS` is set, the CLI uses it directly and lets OpenSSH read `~/.ssh/config`.

For a local machine, prefer a git-ignored `.firewalla.local.json`:

```json
{
  "ssh_alias": "firewalla"
}
```

The CLI reads this file automatically from the project root.

Optional official MSP API environment variables:

- `FIREWALLA_MSP_DOMAIN`: your MSP portal domain, for example `example.firewalla.net`
- `FIREWALLA_MSP_TOKEN`: personal access token created in Firewalla MSP
- `FIREWALLA_BOX_ID`: optional default box `gid` for box-scoped operations

Current finding: Firewalla MSP Lite does not appear to include API/Integration access. Professional or Business is required for official API access. See `docs/working.md`.

## MVP Direction

Use SSH to run read-only Redis queries on the Firewalla box. Do not require MSP API access.

## Install For Local Development

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

Run offline tests:

```bash
python -m pytest -q
```

## CLI

The CLI defaults to dry-run. It prints a redacted SSH command instead of connecting to the box.

Dry-run examples:

```bash
firewalla-skill health --host 192.0.2.1 --key /path/to/fake/key
firewalla-skill devices --host 192.0.2.1 --key /path/to/fake/key
firewalla-skill alarms --host 192.0.2.1 --key /path/to/fake/key
firewalla-skill flows --system --host 192.0.2.1 --key /path/to/fake/key
```

SSH config alias example:

```bash
FIREWALLA_SSH_ALIAS=firewalla firewalla-skill health
```

With `.firewalla.local.json`, this becomes:

```bash
firewalla-skill health
```

Add `--execute` only when running against your own box. The CLI is dry-run by default.

Current commands:

1. `health`: `hostname`, `uptime`, and a safe Redis `PING` probe
2. `devices`: Redis device records from `host:mac:*`, including `--all --json`
3. `alarms`: active/recent alarm records, including `--since-days` and `--include-archive --json`
4. `flows`: Redis `ZREVRANGE` for `flow:conn:system` or a MAC-specific flow key
5. `snapshot`: bounded redacted JSON snapshot for AI reasoning
6. `dump-format`: bounded local raw/redacted dump for format discovery
7. `summary`: compact JSON situation summary from a snapshot or live bounded read
8. `cluster`: redacted alarm clustering with read-only ignore recommendations
9. `device-summary`: current-vs-historical device inventory cleanup
10. `attribute`: redacted alarm-to-device attribution with stable anonymous IDs
11. `resolve-device`: map an anonymous device token to matching device records, redacted by default

Local format dump:

```bash
firewalla-skill dump-format --execute --limit 5
```

This writes to `.firewalla_dumps/`, which is ignored by git.

Local human-facing reports can go in `reports/`. The directory is present in git, but report files are ignored by default.

Summary from a snapshot:

```bash
firewalla-skill summary --input .firewalla_dumps/snapshot.json
```

Live bounded summary:

```bash
firewalla-skill summary --execute --limit 5
```

All devices and last-three-days alarms:

```bash
firewalla-skill devices --execute --all --json --output reports/devices_all_latest.json
firewalla-skill alarms --execute --since-days 3 --include-archive --all --json --output reports/alarms_last3d_latest.json
```

Cluster recent alarms:

```bash
firewalla-skill cluster --alarms reports/alarms_last3d_latest.json --output reports/alarms_last3d_cluster.json
```

Summarize devices and attribute alarms by source device:

```bash
firewalla-skill device-summary --devices reports/devices_all_latest.json --output reports/devices_summary_latest.json
firewalla-skill attribute --alarms reports/alarms_last3d_latest.json --devices reports/devices_all_latest.json --output reports/alarm_device_attribution_latest.json
```

Resolve an anonymous device token when a human needs to locate or verify it:

```bash
firewalla-skill resolve-device --execute --token '<bname:aaaaaaaaaa>' --output reports/device_resolve_latest.json
```

By default this remains redacted and suitable for AI analysis. `resolve-device` is a lookup/diagnostic helper, not the primary alarm parser. To locate the device in your own Firewalla App, explicitly include private local fields and keep the output in ignored `reports/`:

```bash
firewalla-skill resolve-device --execute --token '<bname:aaaaaaaaaa>' --include-private --output reports/private_device_resolve_latest.json
```

## Test Tiers

Tier 1 unit tests and Tier 2 offline integration tests run by default:

```bash
python -m pytest -q -m "not live"
```

Tier 3 live tests are read-only and opt-in:

```bash
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

Live tests require `FIREWALLA_SSH_ALIAS`, `.firewalla.local.json`, or equivalent target configuration.

## Skill Entry

Root skill: `skills/firewalla.md`

An AI agent can install this skill by adding a pointer to `skills/firewalla.md` in the target workspace's skill index or agent instructions.
