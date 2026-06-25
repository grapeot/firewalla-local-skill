# RFC: Firewalla Skill Architecture

## Decision

Use a local-first integration path for the MVP. Treat the official Firewalla MSP API as a paid optional integration.

The implementation target is an AI-facing CLI and root skill. The CLI collects read-only local data through SSH/Redis, redacts it by default, and emits JSON artifacts. The skill tells future agents when to use the CLI, how to install it, what privacy boundaries apply, and how to verify outputs.

## Rationale

The official API is clean but appears gated behind paid MSP Professional/Business plans. The target user already owns Firewalla hardware and does not want an additional subscription for basic automation. Firewalla Gold-class devices expose SSH and can run Docker, so a local sidecar may provide useful read-only inspection without relying on MSP API access.

## Planned Layers

1. `skills/firewalla.md`: root agent workflow and safety policy.
2. `src/firewalla_skill/`: future Python package for local collectors and optional MSP client.
3. `scripts/`: future stable CLI wrappers.
4. `tests/`: offline tests with fake fixtures; live tests opt-in only.

## Credential Inputs

The optional official path needs:

1. MSP portal domain, such as `example.firewalla.net`.
2. MSP personal access token.
3. Optional default box ID (`gid`) after listing boxes.

The local-first path likely needs SSH access to the Firewalla box, or a sidecar container running on/near the box. The user should not provide credentials in chat. Store secrets locally in `.env` or a password manager and pass them through environment variables.

## Local Surface For MVP

Read-only first:

1. basic box health through SSH commands or local files
2. local log discovery
3. read-only device inventory candidates
4. read-only flow/alarm candidates
5. optional `GET /v2/boxes` only if a paid MSP token exists

## Local-First Alternatives Survey

### Option A: SSH + Redis read-only collector

Firewalla's public source shows that core runtime data is stored in local Redis. The repository uses `util/redis_manager.js` to create localhost Redis clients, including DB 0 and DB 1. Host, flow, and alarm modules read and write Redis directly.

Useful confirmed keys and patterns from source:

1. hosts: `host:mac:<mac>` and `host:ip4:<ip>` via `net2/HostTool.js`
2. flow zsets: `flow:conn:in:<mac>`, `flow:conn:out:<mac>`, `flow:local:<mac>`, and `flow:conn:system` via `net2/FlowTool.js`
3. active alarms: `alarm_active`, alarm payloads `_alarm:<aid>`, and alarm details `_alarmDetail:<aid>` via `alarm/AlarmManager2.js`
4. archived alarms: `alarm_archive`
5. active device last-flow index: `deviceLastFlowTs` via flow aggregation code

This is the best MVP route because it requires no paid MSP plan and no browser/app token. The skill can SSH into the Firewalla box and run read-only `redis-cli` queries, then normalize the output locally. This avoids modifying Firewalla services or enabling unauthenticated local APIs.

Security posture:

1. require SSH key auth, not password automation
2. use read-only commands only: `SCAN`, `HGETALL`, `ZRANGE`, `ZREVRANGE`, `ZRANGEBYSCORE`, `ZREVRANGEBYSCORE`, `ZCARD`
3. no writes to Redis, iptables, policy, or service files in MVP
4. redact device names, MACs, local IPs, public IPs, and flow destinations before writing public artifacts

### Option B: Official local Encipher runtime protocol

The community project `ccpk1/firewalla-local-ha` implements a cloud-assisted Additional Pairing flow followed by 100% local encrypted HTTP communication. Its architecture docs describe local runtime communication as encrypted POST requests to `http://{local_ip}:8833/v1/encipher/message/{gid}`. Credentials include `gid`, `eid`, `aid`, and a decrypted symmetric key.

This route gives much richer access: runtime snapshots, system status, hosts, rules, user usage, WAN usage, speed tests, and mutations like pause/resume rules. It is likely the best V2 route, especially if we want Home Assistant-like control without MSP fees.

Tradeoff: implementation cost and security surface are higher. Pairing requires raw QR JSON from Firewalla's Additional Pairing flow, RSA key generation, cloud rendezvous, group polling, symmetric key decryption, and encrypted message construction. It also stores high-trust local credentials.

### Option C: Enable bundled local API manually

Firewalla source includes `api/app-local.js`, which exposes local `/v1` routes. In production/beta it appears to expose only `encipher` and `host`; flow/alarm/mode/test/policy/system routes are gated behind `!firewalla.isProductionOrBeta()`. An older Home Assistant integration (`my-given-name-is-jeremy/FirewallaForHASS`) used SSH tunneling to a localhost-bound unauthenticated API and a script under `~/.firewalla/config/post_main.d/` to enable `app-local`.

This route is not recommended for MVP. It may require modifying box startup behavior, can expose an unauthenticated local API if misconfigured, and is less clean than querying Redis read-only.

### Option D: Browser / desktop cookie / Playwright

This remains a last resort. It is fragile, creates session-token handling risk, and duplicates a UI workflow when better local routes exist.

## Updated MVP Decision

The MVP should implement Option A: SSH + Redis read-only collector.

Target first commands:

1. list box health: use safe shell commands and Redis `sys:*` keys after discovery
2. list devices: scan `host:mac:*`, normalize selected fields
3. list active alarms: read `alarm_active`, then `_alarm:<aid>` and `_alarmDetail:<aid>`
4. recent flows: for selected device MAC or `system`, read `flow:conn:*` zsets within a time window

Option B should be documented as the V2 path if we need rule control or richer runtime snapshots.

## CLI Contract

The first CLI is `firewalla-skill`. It defaults to dry-run and prints a redacted SSH command. Users must add `--execute` before the CLI connects to a Firewalla box.

Initial commands:

1. `firewalla-skill health`: run `hostname`, `uptime`, and a safe Redis `PING` probe
2. `firewalla-skill devices`: scan `host:mac:*`
3. `firewalla-skill alarms`: list active alarm IDs from `alarm_active`
4. `firewalla-skill flows --system`: list recent system flow entries
5. `firewalla-skill flows --mac <mac>`: list recent flow entries for one device MAC
6. `firewalla-skill dump-format`: collect bounded examples for P0 surfaces into a git-ignored local artifact
7. `firewalla-skill snapshot`: emit a redacted AI-readable JSON snapshot for box, devices, alarms, flows, and collection metadata
8. `firewalla-skill summary`: emit a compact JSON situation summary from an existing snapshot or live bounded read

The command builder enforces a Redis read-only allowlist. Mutation commands such as `SET` are rejected before execution.

## Data Artifacts

The CLI writes three kinds of artifacts:

1. public-safe examples in `tests/fixtures/`, always fake
2. local raw or semi-raw captures in `.firewalla_dumps/`, always git-ignored
3. redacted snapshot JSON on stdout or a user-selected path

Raw live output must never be committed. The public repo may include sanitized format reports, but only after replacing device names, MACs, IPs, domains, destination hosts, alarm payloads, and flow payloads with fake values.

## Snapshot Schema

The first stable schema is intentionally compact:

```json
{
  "box": {
    "hostname": "Firewalla",
    "uptime": "redacted uptime string",
    "redis": "PONG"
  },
  "devices": [],
  "alarms": [],
  "flows": [],
  "flows_summary": {},
  "collection": {
    "source": "ssh_redis",
    "redacted": true,
    "generated_at": "2026-01-01T00:00:00Z"
  }
}
```

`devices`, `alarms`, and `flows` start as bounded samples, not complete database exports. Aggregation can grow once the field formats are known.

## Summary Schema

`summary` produces a rule-based JSON brief that an AI agent can read before deciding whether deeper analysis is needed:

```json
{
  "headline": "Snapshot contains 2 devices, 1 alarms, and 5 sampled flows.",
  "counts": {},
  "box": {},
  "alarm_types": {},
  "flow_top_ports": {},
  "notable_items": [],
  "next_questions": []
}
```

The summary is deterministic and does not call an LLM. It is a compact analysis substrate, not the final natural-language report.

## Test Tiers

Tier 1 unit tests run by default with no network and no Firewalla. They cover command construction, read-only allowlists, parsing helpers, schema shape, and redaction.

Tier 2 integration tests run by default unless explicitly deselected. They exercise the installed CLI using fake subprocess/fixture data and verify artifact behavior. They must not require SSH or real credentials.

Tier 3 live tests are skipped unless `FIREWALLA_LIVE_TESTS=1` and a target is configured through `FIREWALLA_SSH_ALIAS` or equivalent env/config. Live tests are read-only and must start with `health`, then bounded P0 reads. No live test may write to Firewalla.

## Skill Integration

The public root skill is `skills/firewalla.md`. It should be installed into a target workspace by adding one pointer to that file from the workspace's `AGENTS.md`, `CLAUDE.md`, `rules/skills/INDEX.md`, or equivalent skill index.

Private aliases belong outside the public repo. A user's local machine may use `.firewalla.local.json`, `.env`, or `~/.ssh/config`, all ignored or external to the repo.

## Write Operations

Rule creation, pause/resume, target list updates, alarm deletion, and other mutations are explicitly out of MVP. They require a separate RFC section and dry-run behavior.

## Fallbacks

If local sources are insufficient:

1. Consider the Home Assistant local integration approach.
2. Consider reverse-engineered Internal Box API only as a later, explicitly accepted path.
3. Consider the paid MSP API only if its value exceeds the subscription cost.
