import json

import pytest

from firewalla_skill.cli import main


@pytest.mark.integration
def test_snapshot_dry_run_has_stable_top_level_schema(capsys, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")

    assert main(["snapshot", "--config", str(config)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert set(payload["snapshot"]) == {"box", "devices", "alarms", "flows", "flows_summary", "collection"}
    assert payload["snapshot"]["collection"]["redacted"] is True


@pytest.mark.integration
def test_dump_format_dry_run_does_not_create_files(capsys, tmp_path):
    config = tmp_path / "config.json"
    output_dir = tmp_path / "dumps"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")

    assert main(["dump-format", "--config", str(config), "--output-dir", str(output_dir)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert not output_dir.exists()


@pytest.mark.integration
def test_summary_from_fixture_outputs_ai_contract(capsys):
    assert main(["summary", "--input", "tests/fixtures/fake_snapshot.json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "headline" in payload
    assert payload["counts"] == {"alarms": 1, "devices": 1, "flows": 0}
    assert payload["alarm_types"] == {"ALARM_INTEL": 1}
    assert payload["collection"]["redacted"] is True


@pytest.mark.integration
def test_devices_all_json_dry_run(capsys, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")
    assert main(["devices", "--config", str(config), "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


@pytest.mark.integration
def test_alarms_since_days_json_dry_run(capsys, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"ssh_alias": "firewalla"}), encoding="utf-8")
    assert main(["alarms", "--config", str(config), "--since-days", "3", "--include-archive", "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True


@pytest.mark.integration
def test_cluster_from_alarm_fixture_outputs_recommendations(capsys, tmp_path):
    alarms = tmp_path / "alarms.json"
    alarms.write_text(
        json.dumps({"alarms": [{"alarm": {"type": "ALARM_GAME", "state": "active"}}], "collection": {"redacted": True}}),
        encoding="utf-8",
    )
    assert main(["cluster", "--alarms", str(alarms)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["clusters"]["by_category"] == {"routine_noise": 1}
    assert payload["recommendations"][0]["write_needed"] is False
