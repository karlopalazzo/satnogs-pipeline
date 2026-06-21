from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from satnogs_pipeline.config import load_config


def test_load_config_reads_station_and_targets() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "targets.yaml"
    config = load_config(config_path)

    assert config.station_id == 4924
    assert config.min_elevation_deg == 25
    assert len(config.targets) == 2
    assert config.targets[0].transmitter_uuid == "Qc2PqaS7n9WYtne3U9EmKJ"


def test_load_config_rejects_empty_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "targets.yaml"
    config_path.write_text(
        "station_id: 1\nlatitude: 0\nlongitude: 0\nelevation_m: 0\n"
        "lookahead_hours: 24\nmin_elevation_deg: 10\ntargets: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="At least one target"):
        load_config(config_path)
