---
name: firewalla-skill
description: Firewalla local-first skill for safe network visibility, alert review, device lookup, and future rule automation.
---

# Firewalla Skill

Use this skill when working with Firewalla firewalls, especially Firewalla Gold-class boxes, through local-first access paths. The official Firewalla MSP API is a paid optional path.

## Goal

Produce safe, AI-readable Firewalla network visibility artifacts without requiring a paid MSP API subscription.

Successful use of this skill means:

1. read-only local access is configured through SSH or a local config file
2. outputs are JSON artifacts suitable for AI analysis
3. raw live data stays outside git
4. no Firewalla mutation occurs unless a future write-specific workflow explicitly authorizes it

## Safety Model

- Prefer local SSH/Docker/read-only collectors over browser cookies, Playwright automation, or reverse-engineered Internal Box API when the official MSP API is not available.
- Start read-only: box health, devices, alarms, flows, and statistics.
- Do not create, delete, pause, or resume rules unless the user explicitly asks for a write operation.
- Never print real tokens, box IDs, private device names, or flow records into public files.
- Local JSON output is private by default so the user and their local AI can reason over real device names, IPs, MACs, domains, and alarm messages.
- Use `--privacy redacted` only for artifacts intended for sharing, public docs, tests, issues, or PRs.
- Keep live captures in `.firewalla_dumps/` or another git-ignored path.

## Optional MSP API Environment

Local-first MVP environment:

```bash
FIREWALLA_HOST=192.0.2.1
FIREWALLA_SSH_USER=pi
FIREWALLA_SSH_KEY=/path/to/fake/firewalla_id_ed25519
```

If the user already has an SSH config entry, prefer:

```bash
FIREWALLA_SSH_ALIAS=firewalla
```

For persistent local config, use git-ignored `.firewalla.local.json`:

```json
{
  "ssh_alias": "firewalla"
}
```

Optional paid MSP API environment:

```bash
FIREWALLA_MSP_DOMAIN=example.firewalla.net
FIREWALLA_MSP_TOKEN=replace-token
FIREWALLA_BOX_ID=00000000-0000-0000-0000-000000000000
```

`FIREWALLA_BOX_ID` is optional for discovery; it becomes useful after `boxes` returns a `gid`.

## Current MVP Workflow

1. Confirm local SSH access to Firewalla.
2. Start with dry-run CLI commands: `firewalla-skill health`, `devices`, `alarms`, `flows`, `snapshot`, `summary`, and `dump-format`.
3. Only use MSP API if the user has a paid plan token.
4. Keep all mutation operations out of scope until read-only access is working.

Add `--execute` only after reviewing the dry-run command.

## Output Contract

For AI analysis, prefer:

```bash
firewalla-skill snapshot --execute --limit 5 --output .firewalla_dumps/snapshot.json
```

Then summarize:

```bash
firewalla-skill summary --input .firewalla_dumps/snapshot.json
```

For full local report inputs, use the CLI instead of ad hoc SSH scripts. These outputs are private by default and belong in ignored `reports/`:

```bash
firewalla-skill devices --execute --all --json --output reports/devices_all_latest.json
firewalla-skill alarms --execute --since-days 3 --include-archive --all --json --output reports/alarms_last3d_latest.json
```

For a public-safe artifact, explicitly request redaction:

```bash
firewalla-skill alarms --execute --since-days 3 --include-archive --all --json --privacy redacted --output reports/alarms_last3d_redacted.json
```

Cluster alarms before recommending what to ignore:

```bash
firewalla-skill cluster --alarms reports/alarms_last3d_latest.json --output reports/alarms_last3d_cluster.json
```

Clean up device scope and attribute alarms before giving user-facing advice. Attribution should use source-like alarm fields such as `p.device.*` and exclude `p.intf.*` infrastructure fields, which describe the Firewalla interface rather than the client device:

```bash
firewalla-skill device-summary --devices reports/devices_all_latest.json --output reports/devices_summary_latest.json
firewalla-skill attribute --alarms reports/alarms_last3d_latest.json --devices reports/devices_all_latest.json --output reports/alarm_device_attribution_latest.json
```

When reading attribution output, prefer `device_summary.name`, `dhcpName`, `localDomain`, or `sambaName` over stale `bname` / `bonjourName` aliases. If `identity_conflict` is present, report the current name and mention the stale alias separately.

When an attribution report surfaces an anonymous token that needs human verification, resolve it before asking the user to manually hunt through the app:

```bash
firewalla-skill resolve-device --execute --token '<bname:aaaaaaaaaa>' --output reports/device_resolve_latest.json
```

`resolve-device` is mainly for redacted artifacts or diagnostics. Private attribution reports should already include readable `device_summary` fields. If attribution points mostly to Firewalla itself, treat that as a parser bug or infrastructure-field match, not as a normal device finding.

Do not recommend creating network rules merely to reduce alert noise. Prefer Firewalla alarm/notification tuning where available; traffic rules are for changing traffic behavior.

For format discovery, prefer:

```bash
firewalla-skill dump-format --execute --limit 5
```

The public repo may document field shapes and fake examples. It must not include raw live artifacts.

Human-readable local reports should be written under `reports/`. That directory is present for discoverability, while report files are git-ignored by default.

## Verification

Default tests:

```bash
python -m pytest -q -m "not live"
```

Opt-in live tests:

```bash
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

Live tests must remain read-only.

## Known Plan Issue

MSP Lite shows API/Integration as locked in current pricing/UI. Avoid designing the MVP around official API access unless the user upgrades.
