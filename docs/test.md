# Test Plan

## Offline Tests

Run:

```bash
source .venv/bin/activate
python -m pytest -q
```

Use fake fixtures and dry-runs for:

1. SSH command construction
2. Redis read-only command allowlist
3. mutation command rejection
4. device/alarm/flow dry-run commands
5. redaction of SSH key paths, hosts, MACs, and local IPs
6. git-ignored local JSON config loading
7. alarm time-window filtering by payload timestamp instead of Redis sorted-set score
8. stable anonymous token redaction for safe joins
9. device-summary and alarm-to-device attribution outputs
10. preservation of Firewalla schema keys such as `p.device.ip` while redacting sensitive values
11. source-aware alarm attribution that uses `p.device.*` / `p.flows[].device` and excludes `p.intf.*` infrastructure fields
12. private-by-default JSON output with explicit `--privacy redacted` export mode
13. readable `device_summary` in attribution output for private inputs
14. device display precedence that prefers current names over stale Bonjour/BName aliases and flags identity conflicts

## Live Tests

Live tests must be opt-in and require explicit environment variables:

- `FIREWALLA_LIVE_TESTS=1`
- `FIREWALLA_HOST`
- `FIREWALLA_SSH_USER`
- `FIREWALLA_SSH_KEY`

Or:

- `FIREWALLA_SSH_ALIAS`

Or a git-ignored `.firewalla.local.json` with `ssh_alias`.

Live tests must start with `firewalla-skill health --execute` only. Any write operation needs a separate RFC and opt-in flag.

Live read-only alarm tests must cover `alarms --since-days 3 --include-archive --all --json` to verify active/archive candidate collection and payload timestamp filtering.

Live read-only report tests must cover `device-summary` and `attribute` on live private artifacts to verify device cleanup and source-aware alarm attribution produce readable device summaries. Live tests should also exercise `--privacy redacted` for at least one bounded artifact.

Optional MSP API tests are separate and only apply when a paid MSP token is available.

## Verified On 2026-06-24

`python -m pytest -q -m "not live"` passes with the offline tests. Live tests require explicit authorization and `FIREWALLA_LIVE_TESTS=1`.

## Privacy Check

Before publishing, scan tracked files for real credentials, private domains, local IPs, MAC addresses, device names, alarm payloads, flow payloads, and password-manager references. Private local artifacts are allowed only under ignored paths such as `reports/` and `.firewalla_dumps/`.
