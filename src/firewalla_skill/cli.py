from __future__ import annotations

import argparse
import hashlib
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
PRIVACY_CHOICES = ("private", "redacted")
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
ALARM_DEVICE_KEYS = {
    "device",
    "p.device.id",
    "p.device.ip",
    "p.device.mac",
    "p.device.name",
    "p.device.macvendor",
}

MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_COMPRESSED_PATTERN = re.compile(r"\b[0-9a-fA-F]{0,4}::[0-9a-fA-F:]+(?:/\d{1,3})?\b")
IPV6_FULL_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,}[0-9a-fA-F]{1,4}(?:/\d{1,3})?\b")
DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")
TOKEN_PATTERN = re.compile(r"<[^:>]+:[0-9a-f]{10}>")


def stable_token(kind: str, value: object) -> str:
    digest = hashlib.sha256(str(value).strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"<{kind}:{digest}>"


def field_tokens(field: str, value: object) -> set[str]:
    text = str(value)
    tokens = {stable_token(field.lower(), text)}
    if MAC_PATTERN.search(text):
        tokens.add(stable_token("mac", text))
    if IPV4_PATTERN.search(text):
        tokens.add(stable_token("ip", text))
    if IPV6_COMPRESSED_PATTERN.search(text) or IPV6_FULL_PATTERN.search(text):
        tokens.add(stable_token("ipv6", text))
    if DOMAIN_PATTERN.search(text):
        tokens.add(stable_token("domain", text))
    return tokens


def device_matches_token(fields: dict[str, object], token: str) -> list[str]:
    return [field for field, value in fields.items() if token in field_tokens(field, value)]


def resolve_device_payload(token: str, matches: list[dict[str, object]], include_private: bool = False) -> dict[str, object]:
    output_matches: list[dict[str, object]] = []
    for match in matches:
        fields = match.get("fields") if isinstance(match.get("fields"), dict) else {}
        output_matches.append(
            {
                "redis_key": match.get("redis_key") if include_private else redact_sensitive_text(str(match.get("redis_key", ""))),
                "matched_fields": match.get("matched_fields", []),
                "fields": fields if include_private else redacted_json_value(fields),
            }
        )
    return {
        "token": token,
        "match_count": len(matches),
        "matches": output_matches,
        "collection": {
            "source": "ssh_redis",
            "read_only": True,
            "redacted": not include_private,
            "private_fields_included": include_private,
        },
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
    text = MAC_PATTERN.sub(lambda match: stable_token("mac", match.group(0)), text)
    text = IPV4_PATTERN.sub(lambda match: stable_token("ip", match.group(0)), text)
    text = IPV6_COMPRESSED_PATTERN.sub(lambda match: stable_token("ipv6", match.group(0)), text)
    text = IPV6_FULL_PATTERN.sub(lambda match: stable_token("ipv6", match.group(0)), text)
    text = DOMAIN_PATTERN.sub(lambda match: stable_token("domain", match.group(0)), text)
    return text


def sensitive_key_kind(key_hint: str | None) -> str | None:
    if not key_hint:
        return None
    lowered = key_hint.lower()
    leaf = lowered.rsplit(".", 1)[-1]
    if leaf in {"mac", "intf_mac"}:
        return "mac"
    if leaf in {"ip", "ipv4", "ipv4addr"}:
        return "ip"
    if lowered in SENSITIVE_STRING_KEYS:
        return lowered
    if leaf in SENSITIVE_STRING_KEYS:
        return leaf
    return None


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
        kind = sensitive_key_kind(key_hint)
        if kind and MAC_PATTERN.search(value):
            return stable_token("mac", value)
        if kind and IPV4_PATTERN.search(value):
            return stable_token("ip", value)
        if kind and kind not in {"mac", "ip"}:
            return stable_token(kind, value)
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redacted_json_value(item, key_hint=key_hint) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            redacted[str(key)] = redacted_json_value(item, key_hint=str(key))
        return redacted
    return value


def apply_privacy(value: object, privacy: str) -> object:
    if privacy == "redacted":
        return redacted_json_value(value)
    if privacy == "private":
        return value
    raise ValueError(f"unknown privacy mode: {privacy}")


def privacy_metadata(privacy: str) -> dict[str, object]:
    return {"privacy": privacy, "redacted": privacy == "redacted", "private": privacy == "private"}


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


def alarm_payload_timestamp(alarm: dict[str, object]) -> float | None:
    payload = alarm.get("alarm")
    if not isinstance(payload, dict):
        return None
    value = payload.get("timestamp") or payload.get("alarmTimestamp")
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def filter_alarms_since(alarms: list[dict[str, object]], since_days: int | None, now: datetime | None = None) -> list[dict[str, object]]:
    if since_days is None:
        return alarms
    cutoff = (now or datetime.now(UTC)).timestamp() - since_days * 24 * 60 * 60
    filtered: list[dict[str, object]] = []
    for alarm in alarms:
        timestamp = alarm_payload_timestamp(alarm)
        if timestamp is not None and timestamp >= cutoff:
            filtered.append(alarm)
    return filtered


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


def collect_health(target: SshTarget, *, execute: bool, privacy: str = "private") -> tuple[dict[str, object], list[dict[str, object]]]:
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
    return apply_privacy(box, privacy), raw


def collect_devices(target: SshTarget, *, execute: bool, limit: int | None, privacy: str = "private") -> tuple[list[object], list[dict[str, object]]]:
    key_command = "redis-cli --raw --scan --pattern 'host:mac:*'"
    if limit is not None:
        key_command += " | head -n " + shlex.quote(str(limit))
    remote = "keys=$(" + key_command + "); for key in $keys; do echo __FIREWALLA_KEY__$key; redis-cli --raw HGETALL \"$key\"; done"
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
    return apply_privacy(devices, privacy), raw


def collect_alarms(
    target: SshTarget,
    *,
    execute: bool,
    limit: int | None,
    since_days: int | None = None,
    include_archive: bool = False,
    candidate_limit: int | None = 2000,
    privacy: str = "private",
) -> tuple[list[object], list[dict[str, object]]]:
    sources = ["alarm_active"]
    if include_archive:
        sources.append("alarm_archive")
    if since_days is not None:
        # ZSET scores are not reliable timestamps across active/archive sets.
        # Fetch candidates first, then filter by _alarm:<aid> payload timestamp.
        score_selector = "ZREVRANGE \"$source\" 0 -1"
    else:
        end = -1 if limit is None else limit - 1
        score_selector = "ZREVRANGE \"$source\" 0 " + shlex.quote(str(end))

    limit_filter = ""
    if limit is not None and since_days is None:
        limit_filter = " | head -n " + shlex.quote(str(limit))
    elif candidate_limit is not None and since_days is not None:
        limit_filter = " | head -n " + shlex.quote(str(candidate_limit))

    source_list = " ".join(shlex.quote(source) for source in sources)
    remote = (
        "for source in "
        + source_list
        + "; do ids=$(redis-cli --raw "
        + score_selector
        + limit_filter
        + "); for aid in $ids; do echo __FIREWALLA_ALARM__$source:$aid; redis-cli --raw HGETALL \"_alarm:$aid\"; echo __FIREWALLA_DETAIL__$aid; redis-cli --raw HGETALL \"_alarmDetail:$aid\"; done; done"
    )
    code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
    raw = [{"name": "alarms", "command": command, "returncode": code, "stdout": stdout, "stderr": stderr}]
    if not execute or code != 0:
        return [], raw

    alarms: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    mode: str | None = None
    lines: list[str] = []
    seen: set[str] = set()
    for line in split_lines(stdout):
        if line.startswith("__FIREWALLA_ALARM__"):
            if current is not None and mode:
                current[mode] = pair_lines_to_dict(lines)
                if str(current.get("id")) not in seen:
                    seen.add(str(current.get("id")))
                    alarms.append(current)
            source_and_id = line.removeprefix("__FIREWALLA_ALARM__")
            source, _, aid = source_and_id.partition(":")
            current = {"id": aid, "source": source}
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
        if str(current.get("id")) not in seen:
            alarms.append(current)
    alarms = filter_alarms_since(alarms, since_days)
    if limit is not None and since_days is not None:
        alarms = alarms[:limit]
    return apply_privacy(alarms, privacy), raw


def collect_flows(target: SshTarget, *, execute: bool, limit: int, privacy: str = "private") -> tuple[list[object], dict[str, object], list[dict[str, object]]]:
    remote = build_redis_raw_command(["ZREVRANGE", "flow:conn:system", "0", str(limit - 1), "WITHSCORES"])
    code, stdout, stderr, command = capture_remote(target, remote, execute=execute)
    raw = [{"name": "flows", "command": command, "returncode": code, "stdout": stdout, "stderr": stderr}]
    if not execute or code != 0:
        return [], {"sample_count": 0}, raw
    flows = zrange_with_scores_to_pairs(split_lines(stdout))
    summary = {"sample_count": len(flows), "source_key": "flow:conn:system"}
    return apply_privacy(flows, privacy), summary, raw


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bucket_counts(values: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value) if value not in (None, "") else "<missing>"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def extract_tokens(value: object) -> set[str]:
    return set(TOKEN_PATTERN.findall(json.dumps(value, sort_keys=True)))


def value_identity_tokens(field: str, value: object) -> set[str]:
    tokens = extract_tokens(value)
    if isinstance(value, str):
        tokens.update(field_tokens(field, value))
        if value.strip():
            tokens.add(value.strip().lower())
    return tokens


def device_identity_tokens(device: dict[str, object]) -> set[str]:
    fields = device.get("fields") if isinstance(device.get("fields"), dict) else {}
    tokens = extract_tokens(device)
    for field, value in fields.items():
        tokens.update(value_identity_tokens(str(field), value))
    return tokens


def device_display_id(device: dict[str, object], fallback: str) -> str:
    fields = device.get("fields") if isinstance(device.get("fields"), dict) else {}
    for key in ("name", "dhcpName", "localDomain", "sambaName", "ssdpName", "bname", "bonjourName", "pname", "ipv4", "ipv4Addr", "mac"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return value
    tokens = sorted(extract_tokens(device))
    return tokens[0] if tokens else fallback


def device_summary_fields(device: dict[str, object]) -> dict[str, object]:
    fields = device.get("fields") if isinstance(device.get("fields"), dict) else {}
    detect = fields.get("detect") if isinstance(fields.get("detect"), dict) else {}
    summary: dict[str, object] = {}
    for key in ("name", "dhcpName", "localDomain", "sambaName", "ssdpName", "bname", "bonjourName", "pname", "ipv4", "ipv4Addr", "mac", "macVendor", "lastActiveTimestamp"):
        if key in fields:
            summary[key] = fields[key]
    for key in ("brand", "model", "os", "type"):
        if key in detect:
            summary[f"detect.{key}"] = detect[key]
    aliases: list[str] = []
    for key in ("bname", "bonjourName", "pname"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip() and value != summary.get("name") and value != summary.get("dhcpName") and value != summary.get("localDomain"):
            aliases.append(value)
    if aliases:
        summary["aliases"] = sorted(set(aliases))
    current_names = [str(fields.get(key)).strip().lower() for key in ("name", "dhcpName", "localDomain", "sambaName") if isinstance(fields.get(key), str) and str(fields.get(key)).strip()]
    stale_aliases = [alias for alias in aliases if alias.strip().lower() not in current_names]
    if stale_aliases and current_names:
        summary["identity_conflict"] = {
            "current_name_candidates": sorted(set(current_names)),
            "alias_candidates": sorted(set(stale_aliases)),
        }
    return summary


def extract_alarm_source_tokens(alarm: dict[str, object]) -> set[str]:
    payload = alarm.get("alarm") if isinstance(alarm.get("alarm"), dict) else {}
    tokens: set[str] = set()
    for key, value in payload.items():
        if str(key).lower() in ALARM_DEVICE_KEYS:
            tokens.update(value_identity_tokens(str(key), value))
    flows = payload.get("p.flows")
    if isinstance(flows, list):
        for flow in flows:
            if isinstance(flow, dict) and "device" in flow:
                tokens.update(value_identity_tokens("device", flow["device"]))
    return tokens


def numeric_timestamp(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def summarize_devices_payload(payload: dict[str, object], now: datetime | None = None) -> dict[str, object]:
    devices = payload.get("devices") if isinstance(payload.get("devices"), list) else []
    now_ts = (now or datetime.now(UTC)).timestamp()
    activity: list[str] = []
    detect_types: list[object] = []
    last_from: list[object] = []
    tokenized_devices = 0

    for device in devices:
        fields = device.get("fields") if isinstance(device, dict) and isinstance(device.get("fields"), dict) else {}
        last_active = numeric_timestamp(fields.get("lastActiveTimestamp"))
        if last_active is None:
            activity.append("missing_last_active")
        elif now_ts - last_active <= 24 * 60 * 60:
            activity.append("active_24h")
        elif now_ts - last_active <= 3 * 24 * 60 * 60:
            activity.append("active_1_to_3d")
        elif now_ts - last_active <= 30 * 24 * 60 * 60:
            activity.append("inactive_3_to_30d")
        else:
            activity.append("inactive_over_30d")

        detect = fields.get("detect")
        if isinstance(detect, dict):
            detect_types.append(detect.get("type"))
        else:
            detect_types.append(None)
        last_from.append(fields.get("lastFrom"))
        if isinstance(device, dict) and device_identity_tokens(device):
            tokenized_devices += 1

    return {
        "total_devices": len(devices),
        "activity_buckets": bucket_counts(activity),
        "detect_types": bucket_counts(detect_types),
        "last_from": bucket_counts(last_from),
        "identity_indexed_devices": tokenized_devices,
        "collection": payload.get("collection", {}),
    }


def device_last_active(device: dict[str, object]) -> float | None:
    fields = device.get("fields") if isinstance(device.get("fields"), dict) else {}
    return numeric_timestamp(fields.get("lastActiveTimestamp"))


def alarm_context_by_device(alarms_payload: dict[str, object], devices_payload: dict[str, object]) -> dict[str, dict[str, object]]:
    alarms = alarms_payload.get("alarms") if isinstance(alarms_payload.get("alarms"), list) else []
    devices = devices_payload.get("devices") if isinstance(devices_payload.get("devices"), list) else []

    device_index: list[dict[str, object]] = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        device_index.append(
            {
                "id": device_display_id(device, f"<device-index:{index}>"),
                "tokens": device_identity_tokens(device),
            }
        )

    context: dict[str, dict[str, object]] = {}
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_tokens = extract_alarm_source_tokens(alarm)
        alarm_payload = alarm.get("alarm") if isinstance(alarm.get("alarm"), dict) else {}
        alarm_type = str(alarm_payload.get("type") or "<missing>")
        category = ALARM_CATEGORY.get(alarm_type, "unknown_review")
        timestamp = alarm_payload.get("timestamp") or alarm_payload.get("alarmTimestamp")
        matches = [entry for entry in device_index if alarm_tokens & entry["tokens"]]
        if not matches:
            continue
        device_id = str(matches[0]["id"])
        item = context.setdefault(device_id, {"alarm_count": 0, "categories": {}, "types": {}, "latest_alarm_timestamp": None})
        item["alarm_count"] = int(item["alarm_count"]) + 1
        item["categories"][category] = item["categories"].get(category, 0) + 1
        item["types"][alarm_type] = item["types"].get(alarm_type, 0) + 1
        alarm_ts = numeric_timestamp(timestamp)
        latest_ts = numeric_timestamp(item.get("latest_alarm_timestamp"))
        if alarm_ts is not None and (latest_ts is None or alarm_ts > latest_ts):
            item["latest_alarm_timestamp"] = alarm_ts
    return context


def active_device_indicators(summary: dict[str, object], alarm_context: dict[str, object]) -> list[str]:
    indicators: list[str] = []
    if "identity_conflict" in summary:
        indicators.append("identity_conflict")
    if not any(summary.get(key) for key in ("name", "dhcpName", "localDomain", "sambaName", "ssdpName", "bname", "bonjourName", "pname")):
        indicators.append("missing_readable_name")
    if not any(summary.get(key) for key in ("detect.brand", "detect.model", "detect.os", "detect.type")):
        indicators.append("missing_detect_metadata")
    if "macVendor" not in summary:
        indicators.append("missing_mac_vendor")

    categories = alarm_context.get("categories") if isinstance(alarm_context.get("categories"), dict) else {}
    if categories.get("review_network_security"):
        indicators.append("network_security_alarm")
    if categories.get("review_bandwidth"):
        indicators.append("bandwidth_alarm")
    if categories.get("unknown_review"):
        indicators.append("unknown_alarm_type")
    return indicators


def build_active_devices_payload(
    devices_payload: dict[str, object],
    alarms_payload: dict[str, object] | None = None,
    *,
    since_days: int = 7,
    now: datetime | None = None,
) -> dict[str, object]:
    devices = devices_payload.get("devices") if isinstance(devices_payload.get("devices"), list) else []
    now_ts = (now or datetime.now(UTC)).timestamp()
    cutoff = now_ts - since_days * 24 * 60 * 60
    alarm_context = alarm_context_by_device(alarms_payload, devices_payload) if alarms_payload else {}

    active: list[dict[str, object]] = []
    excluded_counts: list[str] = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        last_active = device_last_active(device)
        if last_active is None:
            excluded_counts.append("missing_last_active")
            continue
        if last_active < cutoff:
            excluded_counts.append("outside_window")
            continue

        device_id = device_display_id(device, f"<device-index:{index}>")
        summary = device_summary_fields(device)
        context = alarm_context.get(str(device_id), {"alarm_count": 0, "categories": {}, "types": {}, "latest_alarm_timestamp": None})
        active.append(
            {
                "device_id": device_id,
                "last_active_timestamp": last_active,
                "last_active_age_days": round((now_ts - last_active) / (24 * 60 * 60), 3),
                "device_summary": summary,
                "alarm_context": context,
                "investigation_indicators": active_device_indicators(summary, context),
            }
        )

    active.sort(
        key=lambda item: (
            -int(item["alarm_context"].get("alarm_count", 0)) if isinstance(item.get("alarm_context"), dict) else 0,
            float(item.get("last_active_timestamp") or 0) * -1,
            str(item.get("device_id")),
        )
    )
    return {
        "active_devices": active,
        "summary": {
            "total_devices": len(devices),
            "active_device_count": len(active),
            "excluded_counts": bucket_counts(excluded_counts),
            "indicator_counts": bucket_counts(indicator for device in active for indicator in device.get("investigation_indicators", [])),
            "devices_with_alarms": sum(1 for device in active if int(device.get("alarm_context", {}).get("alarm_count", 0)) > 0),
        },
        "collection": {
            "source": "local_artifact_join",
            "since_days": since_days,
            "generated_at": datetime.now(UTC).isoformat(),
            "devices": devices_payload.get("collection", {}),
            "alarms": alarms_payload.get("collection", {}) if alarms_payload else None,
        },
        "limitations": [
            "Active status uses Firewalla host lastActiveTimestamp and the requested local time window.",
            "Alarm context uses the same source-only attribution rules as the attribute command.",
            "Investigation indicators are triage hints, not proof that a device is malicious.",
        ],
    }


def attribute_alarms_to_devices(alarms_payload: dict[str, object], devices_payload: dict[str, object]) -> dict[str, object]:
    alarms = alarms_payload.get("alarms") if isinstance(alarms_payload.get("alarms"), list) else []
    devices = devices_payload.get("devices") if isinstance(devices_payload.get("devices"), list) else []

    device_index: list[dict[str, object]] = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        tokens = device_identity_tokens(device)
        primary = device_display_id(device, f"<device-index:{index}>")
        device_index.append({"id": primary, "tokens": tokens, "summary": device_summary_fields(device)})

    attributed: dict[str, dict[str, object]] = {}
    unattributed = 0
    category_counts: list[str] = []
    type_counts: list[str] = []

    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_tokens = extract_alarm_source_tokens(alarm)
        alarm_payload = alarm.get("alarm") if isinstance(alarm.get("alarm"), dict) else {}
        alarm_type = str(alarm_payload.get("type") or "<missing>")
        category = ALARM_CATEGORY.get(alarm_type, "unknown_review")
        type_counts.append(alarm_type)
        category_counts.append(category)

        matches = [entry for entry in device_index if alarm_tokens & entry["tokens"]]
        if not matches:
            unattributed += 1
            continue
        # Attribute each alarm to the first matching anonymized device to avoid double counting.
        device_id = str(matches[0]["id"])
        item = attributed.setdefault(
            device_id,
            {"device_id": device_id, "device_summary": matches[0].get("summary", {}), "alarm_count": 0, "categories": {}, "types": {}},
        )
        item["alarm_count"] = int(item["alarm_count"]) + 1
        item["categories"][category] = item["categories"].get(category, 0) + 1
        item["types"][alarm_type] = item["types"].get(alarm_type, 0) + 1

    devices_ranked = sorted(attributed.values(), key=lambda item: (-int(item["alarm_count"]), str(item["device_id"])))
    return {
        "total_alarms": len(alarms),
        "total_devices": len(devices),
        "attributed_alarm_count": sum(int(item["alarm_count"]) for item in devices_ranked),
        "unattributed_alarm_count": unattributed,
        "category_counts": bucket_counts(category_counts),
        "type_counts": bucket_counts(type_counts),
        "top_devices": devices_ranked[:20],
        "limitations": [
            "Attribution uses identity values from source-like alarm fields such as device, p.device.*, and p.flows[].device.",
            "Infrastructure fields such as p.intf.* are intentionally excluded to avoid attributing alarms to the Firewalla gateway itself.",
            "If Firewalla alarm payloads omit source device tokens, those alarms remain unattributed.",
        ],
        "collection": {
            "alarms": alarms_payload.get("collection", {}),
            "devices": devices_payload.get("collection", {}),
        },
    }


def summarize_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    devices = snapshot.get("devices") if isinstance(snapshot.get("devices"), list) else []
    alarms = snapshot.get("alarms") if isinstance(snapshot.get("alarms"), list) else []
    flows = snapshot.get("flows") if isinstance(snapshot.get("flows"), list) else []
    box = snapshot.get("box") if isinstance(snapshot.get("box"), dict) else {}

    alarm_types: list[object] = []
    alarm_states: list[object] = []
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        payload = alarm.get("alarm") if isinstance(alarm.get("alarm"), dict) else {}
        alarm_types.append(payload.get("type"))
        alarm_states.append(payload.get("state"))

    flow_ports: list[object] = []
    flow_protocols: list[object] = []
    flow_directions: list[object] = []
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        value = flow.get("value") if isinstance(flow.get("value"), dict) else {}
        flow_ports.append(value.get("dp"))
        flow_protocols.append(value.get("pr"))
        flow_directions.append(value.get("fd"))

    notable_items: list[str] = []
    if box.get("redis_ping") != "PONG":
        notable_items.append("Redis health probe did not return PONG.")
    if alarms:
        notable_items.append(f"There are {len(alarms)} sampled active alarms.")
    if flows:
        notable_items.append(f"There are {len(flows)} sampled recent system flows.")
    if not devices:
        notable_items.append("No device records were included in this bounded snapshot.")

    next_questions = [
        "Which sampled alarms are actionable versus expected household activity?",
        "Which devices should be joined to alarm and flow records first?",
        "Should future flow summaries aggregate by device, destination, port, or protocol?",
    ]

    summary = {
        "headline": f"Snapshot contains {len(devices)} devices, {len(alarms)} alarms, and {len(flows)} sampled flows.",
        "counts": {
            "devices": len(devices),
            "alarms": len(alarms),
            "flows": len(flows),
        },
        "box": {
            "redis_ping": box.get("redis_ping"),
            "has_uptime": bool(box.get("uptime")),
        },
        "alarm_types": bucket_counts(alarm_types),
        "alarm_states": bucket_counts(alarm_states),
        "flow_top_ports": bucket_counts(flow_ports),
        "flow_protocols": bucket_counts(flow_protocols),
        "flow_directions": bucket_counts(flow_directions),
        "notable_items": notable_items,
        "next_questions": next_questions,
        "collection": snapshot.get("collection", {}),
    }
    return summary


ALARM_CATEGORY = {
    "ALARM_GAME": "routine_noise",
    "ALARM_VIDEO": "routine_noise",
    "ALARM_LARGE_UPLOAD": "review_bandwidth",
    "ALARM_LARGE_UPLOAD_2": "review_bandwidth",
    "ALARM_ABNORMAL_BANDWIDTH_USAGE": "review_bandwidth",
    "ALARM_INTEL": "review_network_security",
    "ALARM_UPNP": "review_network_security",
    "ALARM_BRO_NOTICE": "review_network_security",
    "ALARM_DUAL_WAN": "review_network_security",
}

CATEGORY_RECOMMENDATIONS = {
    "routine_noise": {
        "default_action": "consider_mute_or_reduce_notifications",
        "write_needed": False,
        "rationale": "These alarms usually describe expected application categories. Treat them as visibility signals before treating them as traffic that should be blocked.",
    },
    "review_bandwidth": {
        "default_action": "review_device_and_time_window",
        "write_needed": False,
        "rationale": "Large upload or abnormal bandwidth alarms can be expected backups, media sync, or real anomalies. Review before muting or blocking.",
    },
    "review_network_security": {
        "default_action": "review_before_ignore",
        "write_needed": False,
        "rationale": "Low-volume network/security alarms can have higher value than routine app-category alarms. Do not bulk-ignore them without checking context.",
    },
    "unknown_review": {
        "default_action": "review_unknown_type",
        "write_needed": False,
        "rationale": "Unknown alarm types need classification before an ignore policy is safe.",
    },
}


def local_hour_from_timestamp(value: object) -> str | None:
    try:
        ts = float(str(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:00")


def cluster_alarms_payload(payload: dict[str, object]) -> dict[str, object]:
    alarms = payload.get("alarms") if isinstance(payload.get("alarms"), list) else []
    type_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    hour_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    type_to_category: dict[str, str] = {}

    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_payload = alarm.get("alarm") if isinstance(alarm.get("alarm"), dict) else {}
        alarm_type = str(alarm_payload.get("type") or "<missing>")
        state = str(alarm_payload.get("state") or "<missing>")
        source = str(alarm.get("source") or "<missing>")
        category = ALARM_CATEGORY.get(alarm_type, "unknown_review")
        hour = local_hour_from_timestamp(alarm_payload.get("timestamp") or alarm_payload.get("alarmTimestamp"))

        type_counts[alarm_type] = type_counts.get(alarm_type, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        type_to_category[alarm_type] = category
        if hour:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

    total = len(alarms)
    type_counts = dict(sorted(type_counts.items(), key=lambda item: (-item[1], item[0])))
    category_counts = dict(sorted(category_counts.items(), key=lambda item: (-item[1], item[0])))
    top_hours = dict(sorted(hour_counts.items(), key=lambda item: (-item[1], item[0]))[:10])

    recommendations = []
    for category, count in category_counts.items():
        rec = CATEGORY_RECOMMENDATIONS[category].copy()
        rec["category"] = category
        rec["count"] = count
        rec["share"] = round(count / total, 4) if total else 0
        recommendations.append(rec)

    ignore_guidance = {
        "create_network_rules_for_alert_noise": False,
        "preferred_path": "Use Firewalla app alarm/notification tuning or a future official/local API path for alert state. Do not write Redis directly.",
        "why": "Network rules change traffic behavior. Most game/video alarms are notification noise, not evidence that traffic should be blocked.",
    }

    return {
        "total_alarms": total,
        "clusters": {
            "by_category": category_counts,
            "by_type": type_counts,
            "by_state": dict(sorted(state_counts.items(), key=lambda item: (-item[1], item[0]))),
            "by_source": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
            "top_hours": top_hours,
        },
        "type_to_category": dict(sorted(type_to_category.items())),
        "recommendations": recommendations,
        "ignore_guidance": ignore_guidance,
        "limitations": [
            "This cluster uses the input alarm artifact privacy mode and does not mutate Firewalla.",
            "Recommendations are read-only and should be reviewed before any Firewalla configuration change.",
        ],
        "collection": payload.get("collection", {}),
    }


def build_snapshot(target: SshTarget, *, execute: bool, limit: int, privacy: str = "private") -> tuple[dict[str, object], list[dict[str, object]]]:
    box, raw_health = collect_health(target, execute=execute, privacy=privacy)
    devices, raw_devices = collect_devices(target, execute=execute, limit=limit, privacy=privacy)
    alarms, raw_alarms = collect_alarms(target, execute=execute, limit=limit, privacy=privacy)
    flows, flows_summary, raw_flows = collect_flows(target, execute=execute, limit=limit, privacy=privacy)
    snapshot = {
        "box": box,
        "devices": devices,
        "alarms": alarms,
        "flows": flows,
        "flows_summary": flows_summary,
        "collection": {
            "source": "ssh_redis",
            **privacy_metadata(privacy),
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
    if args.json:
        devices, _raw = collect_devices(target, execute=args.execute, limit=None if args.all else args.count, privacy=args.privacy)
        if not args.execute:
            print(json.dumps({"dry_run": True, "message": "devices --json requires --execute to collect data"}, indent=2))
            return 0
        payload = {"devices": devices, "collection": {"source": "ssh_redis", **privacy_metadata(args.privacy), "all": args.all, "limit": None if args.all else args.count}}
        if args.output:
            write_json(Path(args.output), payload)
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    remote = build_redis_command(["SCAN", "0", "MATCH", "host:mac:*", "COUNT", str(args.count)])
    return run_remote(target, remote, execute=args.execute)


def cmd_alarms(args: argparse.Namespace) -> int:
    target = env_target(args)
    if args.json:
        alarms, _raw = collect_alarms(
            target,
            execute=args.execute,
            limit=None if args.all else args.limit,
            since_days=args.since_days,
            include_archive=args.include_archive,
            candidate_limit=args.candidate_limit,
            privacy=args.privacy,
        )
        if not args.execute:
            print(json.dumps({"dry_run": True, "message": "alarms --json requires --execute to collect data"}, indent=2))
            return 0
        payload = {
            "alarms": alarms,
            "collection": {
                "source": "ssh_redis",
                **privacy_metadata(args.privacy),
                "all": args.all,
                "limit": None if args.all else args.limit,
                "since_days": args.since_days,
                "include_archive": args.include_archive,
                "candidate_limit": args.candidate_limit,
            },
        }
        if args.output:
            write_json(Path(args.output), payload)
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    remote = build_redis_command(["ZREVRANGE", "alarm_active", "0", str(args.limit - 1)])
    return run_remote(target, remote, execute=args.execute)


def cmd_flows(args: argparse.Namespace) -> int:
    target = env_target(args)
    key = "flow:conn:system" if args.system else f"flow:conn:{args.direction}:{args.mac}"
    remote = build_redis_command(["ZREVRANGE", key, "0", str(args.limit - 1), "WITHSCORES"])
    return run_remote(target, remote, execute=args.execute)


def cmd_snapshot(args: argparse.Namespace) -> int:
    target = env_target(args)
    snapshot, _raw = build_snapshot(target, execute=args.execute, limit=args.limit, privacy=args.privacy)
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
    snapshot, raw = build_snapshot(target, execute=args.execute, limit=args.limit, privacy="redacted")
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


def cmd_summary(args: argparse.Namespace) -> int:
    if args.input:
        loaded = load_json(args.input)
        if not isinstance(loaded, dict):
            raise SystemExit("summary input must be a JSON object")
        summary = summarize_snapshot(loaded)
    else:
        target = env_target(args)
        if not args.execute:
            print(json.dumps({"dry_run": True, "message": "summary needs --input or --execute"}, indent=2))
            return 0
        snapshot, _raw = build_snapshot(target, execute=True, limit=args.limit, privacy=args.privacy)
        summary = summarize_snapshot(snapshot)

    if args.output:
        write_json(Path(args.output), summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    loaded = load_json(args.alarms)
    if not isinstance(loaded, dict):
        raise SystemExit("cluster --alarms input must be a JSON object")
    cluster = cluster_alarms_payload(loaded)
    if args.output:
        write_json(Path(args.output), cluster)
    else:
        print(json.dumps(cluster, indent=2, sort_keys=True))
    return 0


def cmd_device_summary(args: argparse.Namespace) -> int:
    loaded = load_json(args.devices)
    if not isinstance(loaded, dict):
        raise SystemExit("device-summary --devices input must be a JSON object")
    summary = summarize_devices_payload(loaded)
    if args.output:
        write_json(Path(args.output), summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_attribute(args: argparse.Namespace) -> int:
    alarms = load_json(args.alarms)
    devices = load_json(args.devices)
    if not isinstance(alarms, dict) or not isinstance(devices, dict):
        raise SystemExit("attribute inputs must be JSON objects")
    attribution = attribute_alarms_to_devices(alarms, devices)
    if args.output:
        write_json(Path(args.output), attribution)
    else:
        print(json.dumps(attribution, indent=2, sort_keys=True))
    return 0


def cmd_active_devices(args: argparse.Namespace) -> int:
    devices = load_json(args.devices)
    alarms = load_json(args.alarms) if args.alarms else None
    if not isinstance(devices, dict):
        raise SystemExit("active-devices --devices input must be a JSON object")
    if alarms is not None and not isinstance(alarms, dict):
        raise SystemExit("active-devices --alarms input must be a JSON object")
    payload = build_active_devices_payload(devices, alarms, since_days=args.since_days)
    if args.output:
        write_json(Path(args.output), payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_resolve_device(args: argparse.Namespace) -> int:
    target = env_target(args)
    remote = "keys=$(redis-cli --raw --scan --pattern 'host:mac:*'); for key in $keys; do echo __FIREWALLA_KEY__$key; redis-cli --raw HGETALL \"$key\"; done"
    if not args.execute:
        command = build_ssh_command(target, remote)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "command": redacted_command(command),
                    "redacted": not args.include_private,
                    "private_fields_included": args.include_private,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    code, stdout, stderr, command = capture_remote(target, remote, execute=True)
    if code != 0:
        if stderr:
            print(redact_sensitive_text(stderr), file=sys.stderr)
        return code

    matches: list[dict[str, object]] = []
    current_key: str | None = None
    current_lines: list[str] = []
    for line in split_lines(stdout):
        if line.startswith("__FIREWALLA_KEY__"):
            if current_key:
                fields = pair_lines_to_dict(current_lines)
                matched_fields = device_matches_token(fields, args.token)
                if matched_fields:
                    matches.append({"redis_key": current_key, "fields": fields, "matched_fields": matched_fields})
            current_key = line.removeprefix("__FIREWALLA_KEY__")
            current_lines = []
        else:
            current_lines.append(line)
    if current_key:
        fields = pair_lines_to_dict(current_lines)
        matched_fields = device_matches_token(fields, args.token)
        if matched_fields:
            matches.append({"redis_key": current_key, "fields": fields, "matched_fields": matched_fields})

    output = resolve_device_payload(args.token, matches, include_private=args.include_private)
    if args.output:
        write_json(Path(args.output), output)
    else:
        print(json.dumps(output, indent=2, sort_keys=True))
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
    devices.add_argument("--all", action="store_true", help="collect all device records when used with --json")
    devices.add_argument("--json", action="store_true", help="emit parsed JSON instead of raw Redis output")
    devices.add_argument("--privacy", choices=PRIVACY_CHOICES, default="private", help="JSON privacy mode; default keeps local data private but readable")
    devices.add_argument("--output", help="write JSON output to this path")
    devices.set_defaults(func=cmd_devices)

    alarms = subparsers.add_parser("alarms", help="list active alarm ids from read-only Redis")
    add_common_args(alarms)
    alarms.add_argument("--limit", type=int, default=20, help="maximum alarm ids")
    alarms.add_argument("--all", action="store_true", help="collect all matching alarm records when used with --json")
    alarms.add_argument("--since-days", type=int, help="collect alarms newer than this many days when used with --json")
    alarms.add_argument("--candidate-limit", type=int, default=2000, help="candidate IDs to inspect before payload timestamp filtering")
    alarms.add_argument("--include-archive", action="store_true", help="include alarm_archive in addition to alarm_active")
    alarms.add_argument("--json", action="store_true", help="emit parsed JSON instead of raw Redis output")
    alarms.add_argument("--privacy", choices=PRIVACY_CHOICES, default="private", help="JSON privacy mode; default keeps local data private but readable")
    alarms.add_argument("--output", help="write JSON output to this path")
    alarms.set_defaults(func=cmd_alarms)

    flows = subparsers.add_parser("flows", help="list recent flow records from read-only Redis")
    add_common_args(flows)
    flows.add_argument("--system", action="store_true", help="read system flow index instead of a MAC-specific key")
    flows.add_argument("--mac", help="device MAC for MAC-specific flow query")
    flows.add_argument("--direction", choices=["in", "out"], default="out")
    flows.add_argument("--limit", type=int, default=20, help="maximum flow records")
    flows.set_defaults(func=cmd_flows)

    snapshot = subparsers.add_parser("snapshot", help="emit an AI-readable JSON snapshot")
    add_common_args(snapshot)
    snapshot.add_argument("--limit", type=int, default=5, help="bounded sample size per surface")
    snapshot.add_argument("--privacy", choices=PRIVACY_CHOICES, default="private", help="JSON privacy mode; default keeps local data private but readable")
    snapshot.add_argument("--output", help="write JSON snapshot to this path")
    snapshot.set_defaults(func=cmd_snapshot)

    dump_format = subparsers.add_parser("dump-format", help="write local raw and redacted bounded format dumps")
    add_common_args(dump_format)
    dump_format.add_argument("--limit", type=int, default=5, help="bounded sample size per surface")
    dump_format.add_argument("--output-dir", default=DEFAULT_DUMP_DIR, help="git-ignored local dump directory")
    dump_format.set_defaults(func=cmd_dump_format)

    summary = subparsers.add_parser("summary", help="summarize a snapshot for AI analysis")
    add_common_args(summary)
    summary.add_argument("--input", help="read an existing snapshot JSON")
    summary.add_argument("--limit", type=int, default=5, help="bounded live sample size when using --execute")
    summary.add_argument("--privacy", choices=PRIVACY_CHOICES, default="private", help="live JSON privacy mode when using --execute")
    summary.add_argument("--output", help="write summary JSON to this path")
    summary.set_defaults(func=cmd_summary)

    cluster = subparsers.add_parser("cluster", help="cluster alarm artifacts and suggest read-only ignore strategy")
    cluster.add_argument("--alarms", required=True, help="alarms JSON from firewalla-skill alarms --json")
    cluster.add_argument("--devices", help="optional devices JSON; reserved for future joins")
    cluster.add_argument("--output", help="write cluster JSON to this path")
    cluster.set_defaults(func=cmd_cluster)

    device_summary = subparsers.add_parser("device-summary", help="summarize device inventory into current vs historical buckets")
    device_summary.add_argument("--devices", required=True, help="devices JSON from firewalla-skill devices --json")
    device_summary.add_argument("--output", help="write device summary JSON to this path")
    device_summary.set_defaults(func=cmd_device_summary)

    attribute = subparsers.add_parser("attribute", help="attribute alarms to source devices using Firewalla source fields")
    attribute.add_argument("--alarms", required=True, help="alarms JSON from firewalla-skill alarms --json")
    attribute.add_argument("--devices", required=True, help="devices JSON from firewalla-skill devices --json")
    attribute.add_argument("--output", help="write attribution JSON to this path")
    attribute.set_defaults(func=cmd_attribute)

    active_devices = subparsers.add_parser("active-devices", help="join device inventory and alarms into active-device investigation context")
    active_devices.add_argument("--devices", required=True, help="devices JSON from firewalla-skill devices --json")
    active_devices.add_argument("--alarms", help="optional alarms JSON from firewalla-skill alarms --json")
    active_devices.add_argument("--since-days", type=int, default=7, help="active-device window based on lastActiveTimestamp")
    active_devices.add_argument("--output", help="write active-device investigation JSON to this path")
    active_devices.set_defaults(func=cmd_active_devices)

    resolve_device = subparsers.add_parser("resolve-device", help="resolve an anonymous token to matching Firewalla device records")
    add_common_args(resolve_device)
    resolve_device.add_argument("--token", required=True, help="stable anonymous token, for example <bname:...>")
    resolve_device.add_argument("--include-private", action="store_true", help="include real local device fields instead of redacted tokens")
    resolve_device.add_argument("--output", help="write JSON output to this path")
    resolve_device.set_defaults(func=cmd_resolve_device)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "flows" and not args.system and not args.mac:
        parser.error("flows requires --system or --mac")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
