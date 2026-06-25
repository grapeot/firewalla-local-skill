# Working Log

## Changelog

### 2026-06-24

- Scaffolded public-ready Firewalla skill project.
- Initially considered official Firewalla MSP API first.
- Updated direction after plan check: MSP Lite does not appear to include API/Integration; MVP should be local-first instead.
- Investigated Firewalla public source and community projects. Found viable no-subscription paths: SSH + Redis read-only collector for MVP; `ccpk1/firewalla-local-ha` Additional Pairing + encrypted local runtime protocol for V2.
- Added PRD/RFC/test docs, root skill, `.env.example`, `.gitignore`, and project rules.
- Current implementation recommendation: start with SSH + Redis read-only collector, then consider local Encipher runtime protocol if richer control is needed.
- Added an initial Python CLI skeleton with dry-run-first SSH/Redis commands: `health`, `devices`, `alarms`, and `flows`.
- Added offline tests for read-only Redis command construction, mutation rejection, redaction, and dry-run output. `python -m pytest -q` passes with 5 tests.
- Added SSH config alias support through `--ssh-alias` / `FIREWALLA_SSH_ALIAS`, so an existing SSH config setup can be reused without copying host/user/key into project config.
- Live read-only health check succeeded with the `firewalla` SSH alias: `hostname`, `uptime`, and `redis-cli PING` returned successfully.
- Added git-ignored `.firewalla.local.json` support so local target config can live outside public repo files.
- Promoted flows into P0 per product direction.
- Added `snapshot` and `dump-format` CLI commands for bounded redacted JSON artifacts and local-only raw format dumps.
- Added three test tiers: unit, offline integration, and opt-in live tests.
- Ran bounded live format dump and wrote sanitized findings to `docs/format_report.md`.
- Final verification before publishing: offline tests `14 passed, 3 deselected`; live tests `3 passed, 14 deselected`; privacy scan returned no matches.
- Published public GitHub repo: `https://github.com/grapeot/firewalla-local-skill`.
- Configured GitHub Actions CI and main branch protection with required `test` status check, no required reviewers, no force pushes, and no branch deletion.
- Added `summary` command for deterministic JSON situation summaries from existing snapshots or live bounded reads.
- Moved detailed privacy operating rules out of README and into `AGENTS.md` / `skills/firewalla.md`; README now keeps only a short publishable privacy pointer.
- Added git-ignored `reports/` directory for local human-facing reports, with tracked `.gitkeep` for discoverability.
- Added first-class CLI support for full device inventory and recent alarm windows: `devices --all --json` and `alarms --since-days N --include-archive --all --json`.
- Updated local Chinese report using CLI-generated all-device and last-three-days alarm artifacts.
- Added `cluster` command for read-only alarm actionability clusters and ignore recommendations.
- Updated local Chinese report with alarm cluster results and guidance against using network rules as the default alert-noise solution.
- Fixed alarm archive time-window filtering: `--since-days` now filters by `_alarm:<aid>` payload `timestamp` / `alarmTimestamp` instead of trusting Redis sorted-set scores. Added `--candidate-limit` to bound candidate IDs before payload filtering.
- Added stable anonymous token redaction plus `device-summary` and `attribute` commands. Live attribution shows most recent alarm volume can be reduced to a small anonymous device set before human review.
- Added `resolve-device` for the attribution follow-up loop. The command resolves a stable anonymous token to matching device records through read-only Redis. It defaults to redacted JSON for normal AI workflows; `--include-private` explicitly reveals real local fields for locating the device in the user's own Firewalla App.

## Lessons Learned

- Official API exists but appears paid-gated from Professional upward.
- Do not start from desktop cookie or Playwright reverse engineering while SSH/local sidecar options remain unexplored.
- Firewalla public source confirms Redis key patterns for hosts (`host:mac:*`), flows (`flow:conn:*` / `flow:local:*`), and alarms (`alarm_active`, `_alarm:*`, `_alarmDetail:*`).
- The local HA project confirms a richer local protocol over `http://{local_ip}:8833/v1/encipher/message/{gid}`, but it requires high-trust local credential handling.
- The CLI defaults to dry-run and requires `--execute` before connecting to a real box.
- Device resolution is a public workflow capability. Only the private-field reveal mode requires local-only handling.
