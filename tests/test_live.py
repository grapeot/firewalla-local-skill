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
