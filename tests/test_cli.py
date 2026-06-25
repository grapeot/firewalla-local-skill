import json
from datetime import UTC, datetime

import pytest

from firewalla_skill.cli import (
    SshTarget,
    attribute_alarms_to_devices,
    build_redis_command,
    build_redis_raw_command,
    build_ssh_command,
    cluster_alarms_payload,
    device_matches_token,
    device_display_id,
    device_summary_fields,
    extract_alarm_source_tokens,
    field_tokens,
    filter_alarms_since,
    main,
    load_local_config,
    pair_lines_to_dict,
    redact_sensitive_text,
    redacted_command,
    resolve_device_payload,
    stable_token,
    summarize_devices_payload,
    summarize_snapshot,
    zrange_with_scores_to_pairs,
)


def test_build_redis_command_allows_read_only_commands():
    assert build_redis_command(["SCAN", "0", "MATCH", "host:mac:*", "COUNT", "100"]) == (
        "redis-cli SCAN 0 MATCH 'host:mac:*' COUNT 100"
    )


def test_build_redis_command_rejects_mutation():
    with pytest.raises(ValueError):
        build_redis_command(["SET", "x", "y"])


def test_build_redis_raw_command_preserves_read_only_allowlist():
    assert build_redis_raw_command(["PING"]) == "redis-cli --raw PING"
    with pytest.raises(ValueError):
        build_redis_raw_command(["DEL", "x"])


def test_redacted_command_masks_host_and_key():
    command = build_ssh_command(
        SshTarget(host="192.0.2.1", user="pi", key="/secret/key"),
        "redis-cli SCAN 0",
    )
    assert redacted_command(command) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        "<ssh-key>",
        "pi@<firewalla-host>",
        "redis-cli SCAN 0",
    ]


def test_ssh_alias_uses_config_destination_without_user_or_port():
    command = build_ssh_command(SshTarget(alias="firewall"), "hostname")
    assert command == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "firewall",
        "hostname",
    ]
    assert redacted_command(command) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "<ssh-alias>",
        "hostname",
    ]


def test_redact_sensitive_text_masks_local_network_identifiers():
    text = "device aa:bb:cc:dd:ee:ff at 192.0.2.42 and 52.1.2.3 calling example.test via fe80::1/64"
    assert "aa:bb:cc:dd:ee:ff" not in redact_sensitive_text(text)
    assert stable_token("mac", "aa:bb:cc:dd:ee:ff") in redact_sensitive_text(text)


def test_redact_sensitive_text_does_not_mask_uptime_clock():
    text = "17:05:24 up 5 days"
    assert redact_sensitive_text(text) == text


def test_pair_lines_to_dict_parses_json_values():
    assert pair_lines_to_dict(["name", "example", "empty", "", "payload", '{"x": 1}']) == {
        "name": "example",
        "empty": "",
        "payload": {"x": 1},
    }


def test_redacted_json_value_preserves_schema_keys():
    from firewalla_skill.cli import redacted_json_value

    redacted = redacted_json_value({"p.device.ip": "192.0.2.42", "p.intf.subnet": "192.0.2.1/24"})
    assert "p.device.ip" in redacted
    assert "p.intf.subnet" in redacted
    assert redacted["p.device.ip"] == stable_token("ip", "192.0.2.42")
    assert redacted_json_value({"device": "aa:bb:cc:dd:ee:ff"})["device"] == stable_token("mac", "aa:bb:cc:dd:ee:ff")


def test_zrange_with_scores_to_pairs_parses_scores_and_json_values():
    assert zrange_with_scores_to_pairs(['{"dest":"example.test"}', "1700000000"]) == [
        {"value": {"dest": "example.test"}, "score": 1700000000.0}
    ]


def test_devices_dry_run_outputs_redacted_command(capsys):
    code = main(["devices", "--host", "192.0.2.1", "--key", "/secret/key"])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert "pi@<firewalla-host>" in output["command"]
    assert "/secret/key" not in output["command"]


def test_local_config_can_provide_ssh_alias(tmp_path, capsys):
    config = tmp_path / "firewalla.json"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")
    code = main(["health", "--config", str(config)])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["command"][-2] == "<ssh-alias>"


def test_load_local_config_missing_file_returns_empty_dict(tmp_path):
    assert load_local_config(str(tmp_path / "missing.json")) == {}


def test_summarize_snapshot_counts_p0_surfaces():
    snapshot = {
        "box": {"redis_ping": "PONG", "uptime": "up 1 day"},
        "devices": [{"fields": {"mac": "<mac>"}}],
        "alarms": [{"alarm": {"type": "ALARM_GAME", "state": "active"}}],
        "flows": [{"value": {"dp": 443, "pr": "tcp", "fd": "in"}}],
        "collection": {"redacted": True},
    }
    summary = summarize_snapshot(snapshot)
    assert summary["counts"] == {"devices": 1, "alarms": 1, "flows": 1}
    assert summary["alarm_types"] == {"ALARM_GAME": 1}
    assert summary["flow_top_ports"] == {"443": 1}


def test_cluster_alarms_payload_classifies_actionability():
    payload = {
        "alarms": [
            {"source": "alarm_active", "alarm": {"type": "ALARM_GAME", "state": "active", "timestamp": 1700000000}},
            {"source": "alarm_active", "alarm": {"type": "ALARM_LARGE_UPLOAD", "state": "active", "timestamp": 1700000100}},
            {"source": "alarm_active", "alarm": {"type": "ALARM_INTEL", "state": "active", "timestamp": 1700000200}},
        ],
        "collection": {"redacted": True},
    }
    clustered = cluster_alarms_payload(payload)
    assert clustered["clusters"]["by_category"] == {
        "review_bandwidth": 1,
        "review_network_security": 1,
        "routine_noise": 1,
    }
    assert clustered["ignore_guidance"]["create_network_rules_for_alert_noise"] is False


def test_summarize_devices_payload_buckets_activity():
    payload = {
        "devices": [
            {"fields": {"lastActiveTimestamp": 200000 - 60, "detect": {"type": "phone"}, "mac": stable_token("mac", "a")}},
            {"fields": {"lastActiveTimestamp": 200000 - 2 * 24 * 3600, "detect": {"type": "desktop"}}},
            {"fields": {"lastActiveTimestamp": 200000 - 40 * 24 * 3600}},
        ],
        "collection": {"redacted": True},
    }
    summary = summarize_devices_payload(payload, now=datetime.fromtimestamp(200000, UTC))
    assert summary["activity_buckets"] == {"active_1_to_3d": 1, "active_24h": 1, "inactive_over_30d": 1}
    assert summary["detect_types"] == {"<missing>": 1, "desktop": 1, "phone": 1}


def test_attribute_alarms_to_devices_uses_stable_tokens():
    mac_token = stable_token("mac", "aa:bb:cc:dd:ee:ff")
    devices = {"devices": [{"fields": {"mac": mac_token, "lastActiveTimestamp": 1}}], "collection": {"redacted": True}}
    alarms = {
        "alarms": [
            {"alarm": {"type": "ALARM_GAME", "p.device.mac": mac_token}},
            {"alarm": {"type": "ALARM_INTEL", "message": "no matching token"}},
        ],
        "collection": {"redacted": True},
    }
    attribution = attribute_alarms_to_devices(alarms, devices)
    assert attribution["attributed_alarm_count"] == 1
    assert attribution["unattributed_alarm_count"] == 1
    assert attribution["top_devices"][0]["categories"] == {"routine_noise": 1}
    assert "p.device.*" in attribution["limitations"][0]


def test_alarm_source_tokens_exclude_firewalla_interface_fields():
    device_token = stable_token("mac", "aa:bb:cc:dd:ee:ff")
    gateway_token = stable_token("ip", "192.0.2.1")
    alarm = {"alarm": {"p.device.mac": device_token, "p.intf.subnet": f"{gateway_token}/24", "p.flows": [{"device": device_token}]}}
    tokens = extract_alarm_source_tokens(alarm)
    assert device_token in tokens
    assert gateway_token not in tokens


def test_device_display_prefers_current_name_over_stale_alias():
    device = {
        "fields": {
            "bname": "Old Laptop Alias",
            "bonjourName": "Old Laptop Alias",
            "name": "CurrentBox",
            "dhcpName": "currentbox",
            "localDomain": "currentbox",
            "mac": "aa:bb:cc:dd:ee:ff",
        }
    }
    assert device_display_id(device, "fallback") == "CurrentBox"
    summary = device_summary_fields(device)
    assert summary["name"] == "CurrentBox"
    assert "Old Laptop Alias" in summary["aliases"]
    assert summary["identity_conflict"]["current_name_candidates"] == ["currentbox"]


def test_field_tokens_supports_private_lookup():
    assert stable_token("bname", "Example Device") in field_tokens("bname", "Example Device")
    assert stable_token("mac", "aa:bb:cc:dd:ee:ff") in field_tokens("mac", "aa:bb:cc:dd:ee:ff")


def test_resolve_device_payload_redacts_by_default():
    output = resolve_device_payload(
        stable_token("bname", "Example Device"),
        [
            {
                "redis_key": "host:mac:aa:bb:cc:dd:ee:ff",
                "matched_fields": ["bname"],
                "fields": {"bname": "Example Device", "ipv4Addr": "192.0.2.1"},
            }
        ],
    )
    fields = output["matches"][0]["fields"]
    assert output["collection"]["redacted"] is True
    assert fields["bname"] == stable_token("bname", "Example Device")
    assert fields["ipv4Addr"] == stable_token("ip", "192.0.2.1")
    assert "aa:bb:cc:dd:ee:ff" not in output["matches"][0]["redis_key"]


def test_resolve_device_payload_can_include_private_fields():
    output = resolve_device_payload(
        stable_token("bname", "Example Device"),
        [{"redis_key": "host:mac:aa:bb:cc:dd:ee:ff", "matched_fields": ["bname"], "fields": {"bname": "Example Device"}}],
        include_private=True,
    )
    assert output["collection"]["private_fields_included"] is True
    assert output["matches"][0]["fields"]["bname"] == "Example Device"


def test_device_matches_token_returns_matching_fields():
    token = stable_token("bname", "Example Device")
    assert device_matches_token({"bname": "Example Device", "name": "Other"}, token) == ["bname"]


def test_filter_alarms_since_uses_payload_timestamp_not_source_score():
    alarms = [
        {"id": "old", "score": 9999999999, "alarm": {"timestamp": 100000}},
        {"id": "new", "score": 1, "alarm": {"alarmTimestamp": 2000}},
        {"id": "missing", "score": 9999999999, "alarm": {}},
    ]

    alarms[1]["alarm"]["alarmTimestamp"] = 150000
    filtered = filter_alarms_since(alarms, since_days=1, now=datetime.fromtimestamp(200000, UTC))

    assert [alarm["id"] for alarm in filtered] == ["new"]
