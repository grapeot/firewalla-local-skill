import json

import pytest

from firewalla_skill.cli import (
    SshTarget,
    build_redis_command,
    build_redis_raw_command,
    build_ssh_command,
    cluster_alarms_payload,
    main,
    load_local_config,
    pair_lines_to_dict,
    redact_sensitive_text,
    redacted_command,
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
    assert redact_sensitive_text(text) == "device <mac> at <ip> and <ip> calling <domain> via <ipv6>"


def test_redact_sensitive_text_does_not_mask_uptime_clock():
    text = "17:05:24 up 5 days"
    assert redact_sensitive_text(text) == text


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
