from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


READ_ONLY_REDIS_COMMANDS = {
    "SCAN",
    "HGETALL",
    "ZRANGE",
    "ZREVRANGE",
    "ZRANGEBYSCORE",
    "ZREVRANGEBYSCORE",
    "ZCARD",
    "GET",
    "MGET",
    "PING",
}

DEFAULT_SSH_USER = "pi"
LOCAL_CONFIG = ".firewalla.local.json"
DEFAULT_DUMP_DIR = ".firewalla_dumps"
SENSITIVE_STRING_KEYS = {
    "device",
    "name",
    "bname",
    "pname",
    "hostname",
    "message",
    "macvendor",
    "manufacturer",
    "localdomain",
    "userlocaldomain",
    "dhcpname",
    "uid",
}


@dataclass(frozen=True)
class SshTarget:
    host: str | None = None
    user: str = DEFAULT_SSH_USER
    key: str | None = None
    port: int | None = None
    alias: str | None = None

    @property
    def destination(self) -> str:
        if self.alias:
            return self.alias
        if not self.host:
            raise ValueError("missing SSH host or alias")
        return f"{self.user}@{self.host}"


def build_redis_command(parts: Sequence[str]) -> str:
    if not parts:
        raise ValueError("redis command cannot be empty")

    command = parts[0].upper()
    if command not in READ_ONLY_REDIS_COMMANDS:
        allowed = ", ".join(sorted(READ_ONLY_REDIS_COMMANDS))
        raise ValueError(f"redis command {command!r} is not allowed; allowed: {allowed}")

    return " ".join(shlex.quote(part) for part in ("redis-cli", *parts))


def build_redis_raw_command(parts: Sequence[str]) -> str:
    if not parts:
        raise ValueError("redis command cannot be empty")
    command = parts[0].upper()
    if command not in READ_ONLY_REDIS_COMMANDS:
        allowed = ", ".join(sorted(READ_ONLY_REDIS_COMMANDS))
        raise ValueError(f"redis command {command!r} is not allowed; allowed: {allowed}")
    return " ".join(shlex.quote(part) for part in ("redis-cli", "--raw", *parts))


def build_ssh_command(target: SshTarget, remote_command: str) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
    ]
    if target.port:
        command.extend(["-p", str(target.port)])
    if target.key:
        command.extend(["-i", target.key])
    command.extend([target.destination, remote_command])
    return command


def redacted_command(command: Sequence[str]) -> list[str]:
    redacted = list(command)
    for index, part in enumerate(redacted):
        if index > 0 and redacted[index - 1] == "-i":
            redacted[index] = "<ssh-key>"
    if len(redacted) >= 2:
        destination_index = -2
        if "@" in redacted[destination_index]:
            user, _host = redacted[destination_index].split("@", 1)
            redacted[destination_index] = f"{user}@<firewalla-host>"
        elif redacted[destination_index] != "ssh":
            redacted[destination_index] = "<ssh-alias>"
    return redacted


def redact_sensitive_text(text: str) -> str:
    text = re.sub(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "<mac>", text)
    text = re.sub(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "<ip>",
        text,
    )
    text = re.sub(r"\b[0-9a-fA-F]{0,4}::[0-9a-fA-F:]+(?:/\d{1,3})?\b", "<ipv6>", text)
    text = re.sub(r"\b(?:[0-9a-fA-F]{1,4}:){3,}[0-9a-fA-F]{1,4}(?:/\d{1,3})?\b", "<ipv6>", text)
    text = re.sub(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", "<domain>", text)
    return text


def json_loads_maybe(value: str) -> object:
    stripped = value.strip()
    if not stripped:
        return value
    if stripped[0] not in "[{\"-0123456789tfn":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def redacted_json_value(value: object, key_hint: str | None = None) -> object:
    if isinstance(value, str):
        if key_hint and key_hint.lower() in SENSITIVE_STRING_KEYS:
            return f"<{key_hint.lower()}>"
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redacted_json_value(item, key_hint=key_hint) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            redacted_key = str(redacted_json_value(str(key)))
            redacted[redacted_key] = redacted_json_value(item, key_hint=str(key))
        return redacted
    return value


def pair_lines_to_dict(lines: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for index in range(0, len(lines) - 1, 2):
        key = lines[index]
        value = lines[index + 1]
        result[key] = json_loads_maybe(value)
    return result


def zrange_with_scores_to_pairs(lines: list[str]) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    for index in range(0, len(lines) - 1, 2):
        score: object = lines[index + 1]
        try:
            score = float(str(score))
        except ValueError:
            pass
        pairs.append({"value": json_loads_maybe(lines[index]), "score": score})
    return pairs


def load_local_config(path: str | None = None) -> dict[str, object]:
    config_path = Path(path or LOCAL_CONFIG)
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return data


def config_value(args: argparse.Namespace, config: dict[str, object], attr: str, env_name: str) -> str | None:
    value = getattr(args, attr, None) or os.environ.get(env_name) or config.get(attr)
    if value is None:
        return None
    return str(value)


def env_target(args: argparse.Namespace) -> SshTarget:
    config = load_local_config(args.config)
    explicit_alias = args.ssh_alias or os.environ.get("FIREWALLA_SSH_ALIAS")
    explicit_host = args.host or os.environ.get("FIREWALLA_HOST")
    host = explicit_host or config_value(args, config, "host", "FIREWALLA_HOST")
    alias = explicit_alias or (None if explicit_host else config_value(args, config, "ssh_alias", "FIREWALLA_SSH_ALIAS"))
    if not alias and not host:
        raise SystemExit("missing Firewalla SSH target; set FIREWALLA_SSH_ALIAS, FIREWALLA_HOST, --ssh-alias, or --host")
    port_value = config_value(args, config, "port", "FIREWALLA_SSH_PORT")
    return SshTarget(
        host=host,
        user=config_value(args, config, "user", "FIREWALLA_SSH_USER") or DEFAULT_SSH_USER,
        key=config_value(args, config, "key", "FIREWALLA_SSH_KEY"),
        port=int(port_value) if port_value else None,
        alias=alias,
    )


def run_remote(target: SshTarget, remote_command: str, *, execute: bool) -> int:
    ssh_command = build_ssh_command(target, remote_command)
    if not execute:
        print(json.dumps({"dry_run": True, "command": redacted_command(ssh_command)}, indent=2))
        return 0

    completed = subprocess.run(ssh_command, check=False, text=True, capture_output=True)
    if completed.stdout:
        print(redact_sensitive_text(completed.stdout), end="")
    if completed.stderr:
        print(redact_sensitive_text(completed.stderr), end="", file=sys.stderr)
    return completed.returncode


def capture_remote(target: SshTarget, remote_command: str, *, execute: bool) -> tuple[int, str, str, list[str]]:
    ssh_command = build_ssh_command(target, remote_command)
    if not execute:
        return 0, "", "", redacted_command(ssh_command)
    completed = subprocess.run(ssh_command, check=False, text=True, capture_output=True)
    return completed.returncode, completed.stdout, completed.stderr, redacted_command(ssh_command)


def split_lines(text: str) -> list[str]:
    return text.splitlines()


def collect_health(target: SshTarget, *, execute: bool) -> tuple[dict[str, object], list[dict[str, object]]]:
    commands = {
        "hostname": "hostname",
        "uptime": "uptime",
        "redis_ping": build_redis_raw_command(["PING"]),
    }
    box: dict[str, object] = {}
    raw: list[dict[str, object]] = []
    for name, remote in commands.items():
        code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
        raw.append({"name": name, "command": command, "returncode": code, "stdout": stdout, "stderr": stderr})
        if execute and code == 0:
            box[name] = stdout.strip()
    return redacted_json_value(box), raw


def collect_devices(target: SshTarget, *, execute: bool, limit: int) -> tuple[list[object], list[dict[str, object]]]:
    remote = "keys=$(redis-cli --raw --scan --pattern 'host:mac:*' | head -n " + shlex.quote(str(limit)) + "); for key in $keys; do echo __FIREWALLA_KEY__$key; redis-cli --raw HGETALL \"$key\"; done"
    code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
    raw = [{"name": "devices", "command": command, "returncode": code, "stdout": stdout, "stderr": stderr}]
    if not execute or code != 0:
        return [], raw

    devices: list[object] = []
    current_key: str | None = None
    current_lines: list[str] = []
    for line in split_lines(stdout):
        if line.startswith("__FIREWALLA_KEY__"):
            if current_key:
                devices.append({"redis_key": current_key, "fields": pair_lines_to_dict(current_lines)})
            current_key = line.removeprefix("__FIREWALLA_KEY__")
            current_lines = []
        else:
            current_lines.append(line)
    if current_key:
        devices.append({"redis_key": current_key, "fields": pair_lines_to_dict(current_lines)})
    return redacted_json_value(devices), raw


def collect_alarms(target: SshTarget, *, execute: bool, limit: int) -> tuple[list[object], list[dict[str, object]]]:
    remote = "ids=$(redis-cli --raw ZREVRANGE alarm_active 0 " + shlex.quote(str(limit - 1)) + "); for aid in $ids; do echo __FIREWALLA_ALARM__$aid; redis-cli --raw HGETALL \"_alarm:$aid\"; echo __FIREWALLA_DETAIL__$aid; redis-cli --raw HGETALL \"_alarmDetail:$aid\"; done"
    code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
    raw = [{"name": "alarms", "command": command, "returncode": code, "stdout": stdout, "stderr": stderr}]
    if not execute or code != 0:
        return [], raw

    alarms: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    mode: str | None = None
    lines: list[str] = []
    for line in split_lines(stdout):
        if line.startswith("__FIREWALLA_ALARM__"):
            if current is not None and mode:
                current[mode] = pair_lines_to_dict(lines)
                alarms.append(current)
            current = {"id": line.removeprefix("__FIREWALLA_ALARM__")}
            mode = "alarm"
            lines = []
        elif line.startswith("__FIREWALLA_DETAIL__"):
            if current is not None and mode:
                current[mode] = pair_lines_to_dict(lines)
            mode = "detail"
            lines = []
        else:
            lines.append(line)
    if current is not None and mode:
        current[mode] = pair_lines_to_dict(lines)
        alarms.append(current)
    return redacted_json_value(alarms), raw


def collect_flows(target: SshTarget, *, execute: bool, limit: int) -> tuple[list[object], dict[str, object], list[dict[str, object]]]:
    remote = build_redis_raw_command(["ZREVRANGE", "flow:conn:system", "0", str(limit - 1), "WITHSCORES"])
    code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
    raw = [{"name": "flows", "command": command, "returncode": code, "stdout": stdout, "stderr": stderr}]
    if not execute or code != 0:
        return [], {"sample_count": 0}, raw
    flows = zrange_with_scores_to_pairs(split_lines(stdout))
    summary = {"sample_count": len(flows), "source_key": "flow:conn:system"}
    return redacted_json_value(flows), summary, raw


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_snapshot(target: SshTarget, *, execute: bool, limit: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    box, raw_health = collect_health(target, execute=execute)
    devices, raw_devices = collect_devices(target, execute=execute, limit=limit)
    alarms, raw_alarms = collect_alarms(target, execute=execute, limit=limit)
    flows, flows_summary, raw_flows = collect_flows(target, execute=execute, limit=limit)
    snapshot = {
        "box": box,
        "devices": devices,
        "alarms": alarms,
        "flows": flows,
        "flows_summary": flows_summary,
        "collection": {
            "source": "ssh_redis",
            "redacted": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "limit": limit,
        },
    }
    return snapshot, raw_health + raw_devices + raw_alarms + raw_flows


def cmd_health(args: argparse.Namespace) -> int:
    target = env_target(args)
    remote = " && ".join(
        [
            "hostname",
            "uptime",
            build_redis_command(["PING"]),
        ]
    )
    return run_remote(target, remote, execute=args.execute)


def cmd_devices(args: argparse.Namespace) -> int:
    target = env_target(args)
    remote = build_redis_command(["SCAN", "0", "MATCH", "host:mac:*", "COUNT", str(args.count)])
    return run_remote(target, remote, execute=args.execute)


def cmd_alarms(args: argparse.Namespace) -> int:
    target = env_target(args)
    remote = build_redis_command(["ZREVRANGE", "alarm_active", "0", str(args.limit - 1)])
    return run_remote(target, remote, execute=args.execute)


def cmd_flows(args: argparse.Namespace) -> int:
    target = env_target(args)
    key = "flow:conn:system" if args.system else f"flow:conn:{args.direction}:{args.mac}"
    remote = build_redis_command(["ZREVRANGE", key, "0", str(args.limit - 1), "WITHSCORES"])
    return run_remote(target, remote, execute=args.execute)


def cmd_snapshot(args: argparse.Namespace) -> int:
    target = env_target(args)
    snapshot, _raw = build_snapshot(target, execute=args.execute, limit=args.limit)
    if not args.execute:
        dry_run = {"dry_run": True, "message": "snapshot requires --execute to collect data", "snapshot": snapshot}
        print(json.dumps(dry_run, indent=2, sort_keys=True))
        return 0
    if args.output:
        write_json(Path(args.output), snapshot)
    else:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


def cmd_dump_format(args: argparse.Namespace) -> int:
    target = env_target(args)
    snapshot, raw = build_snapshot(target, execute=args.execute, limit=args.limit)
    if not args.execute:
        print(json.dumps({"dry_run": True, "message": "dump-format requires --execute to collect local data"}, indent=2))
        return 0
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_dir = Path(args.output_dir)
    redacted_path = dump_dir / f"firewalla_format_redacted_{timestamp}.json"
    raw_path = dump_dir / f"firewalla_format_raw_{timestamp}.json"
    write_json(redacted_path, snapshot)
    write_json(raw_path, raw)
    print(json.dumps({"redacted": str(redacted_path), "raw_local": str(raw_path)}, indent=2, sort_keys=True))
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help=f"local JSON config path; default: {LOCAL_CONFIG}")
    parser.add_argument("--ssh-alias", help="SSH config Host alias; defaults to FIREWALLA_SSH_ALIAS")
    parser.add_argument("--host", help="Firewalla local host or IP; defaults to FIREWALLA_HOST")
    parser.add_argument("--user", help="SSH user; defaults to FIREWALLA_SSH_USER or pi")
    parser.add_argument("--key", help="SSH private key path; defaults to FIREWALLA_SSH_KEY")
    parser.add_argument("--port", type=int, help="SSH port; defaults to SSH config or OpenSSH default")
    parser.add_argument("--execute", action="store_true", help="run the SSH command; default is dry-run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="firewalla-skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="dry-run or collect basic read-only box health")
    add_common_args(health)
    health.set_defaults(func=cmd_health)

    devices = subparsers.add_parser("devices", help="scan read-only Redis host keys")
    add_common_args(devices)
    devices.add_argument("--count", type=int, default=100, help="Redis SCAN count hint")
    devices.set_defaults(func=cmd_devices)

    alarms = subparsers.add_parser("alarms", help="list active alarm ids from read-only Redis")
    add_common_args(alarms)
    alarms.add_argument("--limit", type=int, default=20, help="maximum alarm ids")
    alarms.set_defaults(func=cmd_alarms)

    flows = subparsers.add_parser("flows", help="list recent flow records from read-only Redis")
    add_common_args(flows)
    flows.add_argument("--system", action="store_true", help="read system flow index instead of a MAC-specific key")
    flows.add_argument("--mac", help="device MAC for MAC-specific flow query")
    flows.add_argument("--direction", choices=["in", "out"], default="out")
    flows.add_argument("--limit", type=int, default=20, help="maximum flow records")
    flows.set_defaults(func=cmd_flows)

    snapshot = subparsers.add_parser("snapshot", help="emit a redacted AI-readable JSON snapshot")
    add_common_args(snapshot)
    snapshot.add_argument("--limit", type=int, default=5, help="bounded sample size per surface")
    snapshot.add_argument("--output", help="write redacted JSON snapshot to this path")
    snapshot.set_defaults(func=cmd_snapshot)

    dump_format = subparsers.add_parser("dump-format", help="write local raw and redacted bounded format dumps")
    add_common_args(dump_format)
    dump_format.add_argument("--limit", type=int, default=5, help="bounded sample size per surface")
    dump_format.add_argument("--output-dir", default=DEFAULT_DUMP_DIR, help="git-ignored local dump directory")
    dump_format.set_defaults(func=cmd_dump_format)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "flows" and not args.system and not args.mac:
        parser.error("flows requires --system or --mac")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
