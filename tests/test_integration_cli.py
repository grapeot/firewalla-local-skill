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
