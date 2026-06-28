import json
from datetime import UTC, datetime

import pytest

from firewalla_skill.cli import (
    SshTarget,
    attribute_alarms_to_devices,
    build_redis_command,
    build_redis_raw_command,
    build_active_devices_payload,
    build_ssh_command,
    cluster_alarms_payload,
    device_display_id,
    device_summary_fields,
    extract_alarm_source_values,
    filter_alarms_since,
    main,
    load_local_config,
    pair_lines_to_dict,
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


def test_build_ssh_command_keeps_real_destination_and_key():
    command = build_ssh_command(
        SshTarget(host="192.0.2.1", user="pi", key="/secret/key"),
        "redis-cli SCAN 0",
    )
    assert command == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        "/secret/key",
        "pi@192.0.2.1",
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
    assert command[-2] == "firewall"


def test_pair_lines_to_dict_parses_json_values():
    assert pair_lines_to_dict(["name", "example", "empty", "", "payload", '{"x": 1}']) == {
        "name": "example",
        "empty": "",
        "payload": {"x": 1},
    }


def test_zrange_with_scores_to_pairs_parses_scores_and_json_values():
    assert zrange_with_scores_to_pairs(['{"dest":"example.test"}', "1700000000"]) == [
        {"value": {"dest": "example.test"}, "score": 1700000000.0}
    ]


def test_devices_dry_run_outputs_real_command(capsys):
    code = main(["devices", "--host", "192.0.2.1", "--key", "/secret/key"])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert "pi@192.0.2.1" in output["command"]
    assert "/secret/key" in output["command"]


def test_local_config_can_provide_ssh_alias(tmp_path, capsys):
    config = tmp_path / "firewalla.json"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")
    code = main(["health", "--config", str(config)])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["command"][-2] == "firewalla"


def test_load_local_config_missing_file_returns_empty_dict(tmp_path):
    assert load_local_config(str(tmp_path / "missing.json")) == {}


def test_summarize_snapshot_counts_p0_surfaces():
    snapshot = {
        "box": {"redis_ping": "PONG", "uptime": "up 1 day"},
        "devices": [{"fields": {"mac": "<mac>"}}],
        "alarms": [{"alarm": {"type": "ALARM_GAME", "state": "active"}}],
        "flows": [{"value": {"dp": 443, "pr": "tcp", "fd": "in"}}],
        "collection": {"local_raw": True},
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
        "collection": {"local_raw": True},
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
            {"fields": {"lastActiveTimestamp": 200000 - 60, "detect": {"type": "phone"}, "mac": "aa:bb:cc:dd:ee:ff"}},
            {"fields": {"lastActiveTimestamp": 200000 - 2 * 24 * 3600, "detect": {"type": "desktop"}}},
            {"fields": {"lastActiveTimestamp": 200000 - 40 * 24 * 3600}},
        ],
        "collection": {"local_raw": True},
    }
    summary = summarize_devices_payload(payload, now=datetime.fromtimestamp(200000, UTC))
    assert summary["activity_buckets"] == {"active_1_to_3d": 1, "active_24h": 1, "inactive_over_30d": 1}
    assert summary["detect_types"] == {"<missing>": 1, "desktop": 1, "phone": 1}


def test_attribute_alarms_to_devices_uses_source_values():
    devices = {"devices": [{"fields": {"mac": "aa:bb:cc:dd:ee:ff", "lastActiveTimestamp": 1}}], "collection": {"local_raw": True}}
    alarms = {
        "alarms": [
            {"alarm": {"type": "ALARM_GAME", "p.device.mac": "aa:bb:cc:dd:ee:ff"}},
            {"alarm": {"type": "ALARM_INTEL", "message": "no matching source device"}},
        ],
        "collection": {"local_raw": True},
    }
    attribution = attribute_alarms_to_devices(alarms, devices)
    assert attribution["attributed_alarm_count"] == 1
    assert attribution["unattributed_alarm_count"] == 1
    assert attribution["top_devices"][0]["categories"] == {"routine_noise": 1}
    assert "p.device.*" in attribution["limitations"][0]


def test_alarm_source_values_exclude_firewalla_interface_fields():
    alarm = {"alarm": {"p.device.mac": "aa:bb:cc:dd:ee:ff", "p.intf.subnet": "192.0.2.1/24", "p.flows": [{"device": "aa:bb:cc:dd:ee:ff"}]}}
    values = extract_alarm_source_values(alarm)
    assert "aa:bb:cc:dd:ee:ff" in values
    assert "192.0.2.1/24" not in values


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


def test_filter_alarms_since_uses_payload_timestamp_not_source_score():
    alarms = [
        {"id": "old", "score": 9999999999, "alarm": {"timestamp": 100000}},
        {"id": "new", "score": 1, "alarm": {"alarmTimestamp": 2000}},
        {"id": "missing", "score": 9999999999, "alarm": {}},
    ]

    alarms[1]["alarm"]["alarmTimestamp"] = 150000
    filtered = filter_alarms_since(alarms, since_days=1, now=datetime.fromtimestamp(200000, UTC))

    assert [alarm["id"] for alarm in filtered] == ["new"]


def test_build_active_devices_payload_joins_alarm_context_and_indicators():
    devices = {
        "devices": [
            {
                "fields": {
                    "name": "CurrentBox",
                    "bname": "OldBox",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ipv4Addr": "192.0.2.42",
                    "lastActiveTimestamp": 200000 - 60,
                    "detect": {"type": "desktop", "os": "Windows"},
                }
            },
            {"fields": {"name": "OldDevice", "lastActiveTimestamp": 200000 - 10 * 24 * 3600}},
            {"fields": {"name": "MissingActivity"}},
        ],
        "collection": {"local_raw": True},
    }
    alarms = {
        "alarms": [
            {"alarm": {"type": "ALARM_INTEL", "p.device.mac": "aa:bb:cc:dd:ee:ff", "timestamp": 199999}},
            {"alarm": {"type": "ALARM_GAME", "p.device.mac": "aa:bb:cc:dd:ee:ff", "timestamp": 199998}},
        ],
        "collection": {"since_days": 7},
    }

    payload = build_active_devices_payload(devices, alarms, since_days=7, now=datetime.fromtimestamp(200000, UTC))

    assert payload["summary"]["active_device_count"] == 1
    assert payload["summary"]["excluded_counts"] == {"missing_last_active": 1, "outside_window": 1}
    active = payload["active_devices"][0]
    assert active["device_id"] == "CurrentBox"
    assert active["alarm_context"]["alarm_count"] == 2
    assert active["alarm_context"]["categories"] == {"review_network_security": 1, "routine_noise": 1}
    assert "identity_conflict" in active["investigation_indicators"]
    assert "network_security_alarm" in active["investigation_indicators"]


def test_build_active_devices_payload_keeps_duplicate_display_names_distinct():
    devices = {
        "devices": [
            {"redis_key": "host:mac:aa:bb:cc:dd:ee:01", "fields": {"name": "Watch", "mac": "aa:bb:cc:dd:ee:01", "lastActiveTimestamp": 200000}},
            {"redis_key": "host:mac:aa:bb:cc:dd:ee:02", "fields": {"name": "Watch", "mac": "aa:bb:cc:dd:ee:02", "lastActiveTimestamp": 200000}},
        ],
        "collection": {"local_raw": True},
    }
    alarms = {
        "alarms": [{"alarm": {"type": "ALARM_LARGE_UPLOAD", "p.device.mac": "aa:bb:cc:dd:ee:02"}}],
        "collection": {"local_raw": True},
    }

    payload = build_active_devices_payload(devices, alarms, since_days=7, now=datetime.fromtimestamp(200000, UTC))
    by_key = {device["device_key"]: device for device in payload["active_devices"]}

    assert by_key["host:mac:aa:bb:cc:dd:ee:01"]["alarm_context"]["alarm_count"] == 0
    assert by_key["host:mac:aa:bb:cc:dd:ee:02"]["alarm_context"]["alarm_count"] == 1
