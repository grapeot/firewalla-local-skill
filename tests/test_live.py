import json
import os
from pathlib import Path

import pytest

from firewalla_skill.cli import main


pytestmark = pytest.mark.live


def live_enabled() -> bool:
    return os.environ.get("FIREWALLA_LIVE_TESTS") == "1"


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_health_read_only(capsys):
    assert main(["health", "--execute"]) == 0
    output = capsys.readouterr().out
    assert "PONG" in output


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_snapshot_read_only_redacted(tmp_path):
    output = tmp_path / "snapshot.json"
    assert main(["snapshot", "--execute", "--limit", "2", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["collection"]["redacted"] is True
    assert set(payload) == {"box", "devices", "alarms", "flows", "flows_summary", "collection"}


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_dump_format_writes_gitignored_outputs(tmp_path):
    assert main(["dump-format", "--execute", "--limit", "2", "--output-dir", str(tmp_path)]) == 0
    files = list(Path(tmp_path).glob("firewalla_format_*.json"))
    assert len(files) == 2


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_summary_read_only_redacted(tmp_path):
    output = tmp_path / "summary.json"
    assert main(["summary", "--execute", "--limit", "2", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "headline" in payload
    assert set(payload["counts"]) == {"devices", "alarms", "flows"}


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_all_devices_and_recent_alarms_json(tmp_path):
    devices = tmp_path / "devices.json"
    alarms = tmp_path / "alarms.json"
    assert main(["devices", "--execute", "--all", "--json", "--output", str(devices)]) == 0
    assert main(["alarms", "--execute", "--since-days", "3", "--include-archive", "--all", "--json", "--output", str(alarms)]) == 0
    devices_payload = json.loads(devices.read_text(encoding="utf-8"))
    alarms_payload = json.loads(alarms.read_text(encoding="utf-8"))
    assert isinstance(devices_payload["devices"], list)
    assert isinstance(alarms_payload["alarms"], list)
    assert devices_payload["collection"]["all"] is True
    assert alarms_payload["collection"]["since_days"] == 3


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_device_summary_and_attribution(tmp_path):
    devices = tmp_path / "devices.json"
    alarms = tmp_path / "alarms.json"
    device_summary = tmp_path / "device_summary.json"
    attribution = tmp_path / "attribution.json"
    assert main(["devices", "--execute", "--all", "--json", "--output", str(devices)]) == 0
    assert main(["alarms", "--execute", "--since-days", "3", "--include-archive", "--all", "--json", "--output", str(alarms)]) == 0
    assert main(["device-summary", "--devices", str(devices), "--output", str(device_summary)]) == 0
    assert main(["attribute", "--alarms", str(alarms), "--devices", str(devices), "--output", str(attribution)]) == 0
    assert json.loads(device_summary.read_text(encoding="utf-8"))["total_devices"] >= 0
    payload = json.loads(attribution.read_text(encoding="utf-8"))
    assert set(payload) >= {"total_alarms", "attributed_alarm_count", "unattributed_alarm_count", "top_devices"}


@pytest.mark.skipif(not live_enabled(), reason="set FIREWALLA_LIVE_TESTS=1 for live Firewalla tests")
def test_live_resolve_device_dry_run_only():
    assert main(["resolve-device", "--token", "<bname:aaaaaaaaaa>"]) == 0
