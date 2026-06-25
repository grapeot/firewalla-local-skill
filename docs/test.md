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

Optional MSP API tests are separate and only apply when a paid MSP token is available.

## Verified On 2026-06-24

`python -m pytest -q -m "not live"` passes with the offline tests. Live tests require explicit authorization and `FIREWALLA_LIVE_TESTS=1`.

## Privacy Check

Before publishing, scan for real credentials, private domains, local IPs, MAC addresses, device names, alarm payloads, flow payloads, and password-manager references.
