# Firewalla Skill

## Project Role

This is a public-ready AI skill project for interacting with Firewalla through local-first read-only access first. The official Firewalla MSP API is a paid optional path.

## Project Structure

- `src/firewalla_skill/`: Python package and CLI implementation.
- `skills/firewalla.md`: public root skill for AI agents.
- `docs/`: PRD, RFC, test plan, and working log.
- `tests/`: unit, offline integration, and opt-in live tests.

## Privacy Rules

- Do not commit real MSP domains, access tokens, box IDs, device names, IP addresses, flow data, alarms, or screenshots.
- Use `.env` for real credentials and keep `.env` out of git.
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
