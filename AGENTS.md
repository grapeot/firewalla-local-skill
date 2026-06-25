# Firewalla Skill

## Project Role

This is a public-ready AI skill project for interacting with Firewalla through local-first read-only access first. The official Firewalla MSP API is a paid optional path.

## Project Structure

- `src/firewalla_skill/`: Python package and CLI implementation.
- `skills/firewalla.md`: public root skill for AI agents.
- `docs/`: PRD, RFC, test plan, and working log.
- `tests/`: unit, offline integration, and opt-in live tests.

## Privacy Rules

- This repository is designed to be publishable with only fake examples.
- Do not commit real Firewalla MSP domains, access tokens, box IDs, device names, IP addresses, MAC addresses, domains, flow data, alarms, raw snapshots, local SSH aliases, or screenshots.
- Local CLI JSON output is private by default. That is intentional: the primary use case is local AI analysis on the user's own machine. Keep private outputs in ignored paths instead of forcing redaction.
- Use `--privacy redacted` only for artifacts intended for public docs, tests, issues, PRs, or other sharing.
- Use `.env`, `.firewalla.local.json`, `~/.ssh/config`, or a password manager for real credentials and local routing. Keep those files out of git.
- Live captures belong in `.firewalla_dumps/`, which is git-ignored. Public docs and tests use fake or redacted examples only.
- Human-facing local reports belong in `reports/`. The directory has a tracked `.gitkeep`, but report files are ignored by default.
- Keep `.env.example` fake and publishable.
- If a workspace needs private routing or aliases, put them in the workspace-level private skill overlay, not in this repo.

## Working Rules

- Update `docs/working.md` after meaningful changes.
- Commit frequently when working in this repo, after tests pass and privacy checks are clean.
- Prefer SSH/Redis read-only collection over reverse-engineered desktop/app APIs when MSP API access is unavailable.
- Treat any write-capable API call as opt-in and dangerous. Dry-run first whenever possible.
- Keep CLI contracts stable once introduced.

## Python Environment

Use a project-local `.venv` managed by `uv` before running Python commands.

Default verification:

```bash
source .venv/bin/activate
python -m pytest -q -m "not live"
```
