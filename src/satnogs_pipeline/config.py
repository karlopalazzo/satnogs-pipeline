"""Load and validate pipeline configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Target:
    name: str
    norad_cat_id: int
    transmitter_uuid: str
    transmitter_label: str


@dataclass(frozen=True)
class PipelineConfig:
    station_id: int
    latitude: float
    longitude: float
    elevation_m: float
    lookahead_hours: int
    min_elevation_deg: float
    targets: tuple[Target, ...]


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_config(path: Path) -> PipelineConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    targets: list[Target] = []
    for index, item in enumerate(_require(raw, "targets")):
        if not isinstance(item, dict):
            raise ValueError(f"targets[{index}] must be a mapping")
        targets.append(
            Target(
                name=str(_require(item, "name")),
                norad_cat_id=int(_require(item, "norad_cat_id")),
                transmitter_uuid=str(_require(item, "transmitter_uuid")),
                transmitter_label=str(item.get("transmitter_label", "")),
            )
        )

    if not targets:
        raise ValueError("At least one target is required")

    return PipelineConfig(
        station_id=int(_require(raw, "station_id")),
        latitude=float(_require(raw, "latitude")),
        longitude=float(_require(raw, "longitude")),
        elevation_m=float(_require(raw, "elevation_m")),
        lookahead_hours=int(_require(raw, "lookahead_hours")),
        min_elevation_deg=float(_require(raw, "min_elevation_deg")),
        targets=tuple(targets),
    )
