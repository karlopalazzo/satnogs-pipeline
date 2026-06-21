"""Plan and optionally submit SatNOGS observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from satnogs_pipeline.api_client import SatnogsNetworkClient, ScheduledObservation, fetch_tle
from satnogs_pipeline.config import PipelineConfig, Target
from satnogs_pipeline.passes import PassWindow, default_planning_window, predict_passes


@dataclass(frozen=True)
class PlannedObservation:
    target: Target
    pass_window: PassWindow
    action: str
    reason: str
    existing_observation_id: int | None = None


def plan_observations(
    config: PipelineConfig,
    *,
    client: SatnogsNetworkClient | None = None,
    now: datetime | None = None,
) -> list[PlannedObservation]:
    """Compute which passes should be scheduled and why."""
    window_start, window_end = default_planning_window(
        lookahead_hours=config.lookahead_hours,
        now=now,
    )
    planned: list[PlannedObservation] = []

    for target in config.targets:
        existing: list[ScheduledObservation] = []
        if client is not None:
            existing = client.list_future_observations(
                station_id=config.station_id,
                norad_cat_id=target.norad_cat_id,
            )

        tle_name, line1, line2 = fetch_tle(target.norad_cat_id)
        passes = predict_passes(
            tle_name=tle_name,
            tle_line1=line1,
            tle_line2=line2,
            latitude=config.latitude,
            longitude=config.longitude,
            elevation_m=config.elevation_m,
            start=window_start,
            end=window_end,
            min_elevation_deg=config.min_elevation_deg,
        )

        for pass_window in passes:
            overlap = _find_overlap(existing, pass_window)
            if overlap is not None:
                planned.append(
                    PlannedObservation(
                        target=target,
                        pass_window=pass_window,
                        action="skip",
                        reason="already scheduled",
                        existing_observation_id=overlap.id,
                    )
                )
                continue

            planned.append(
                PlannedObservation(
                    target=target,
                    pass_window=pass_window,
                    action="schedule",
                    reason="pass meets elevation threshold",
                )
            )

    planned.sort(key=lambda item: item.pass_window.start)
    return planned


def apply_plan(
    config: PipelineConfig,
    plan: list[PlannedObservation],
    *,
    client: SatnogsNetworkClient,
    dry_run: bool,
) -> list[PlannedObservation]:
    """Submit schedule requests for planned observations."""
    results: list[PlannedObservation] = []

    for item in plan:
        if item.action != "schedule":
            results.append(item)
            continue

        if dry_run:
            results.append(item)
            continue

        created = client.schedule_observation(
            station_id=config.station_id,
            transmitter_uuid=item.target.transmitter_uuid,
            start=item.pass_window.start,
            end=item.pass_window.end,
        )
        results.append(
            PlannedObservation(
                target=item.target,
                pass_window=item.pass_window,
                action="scheduled",
                reason=f"created observation {created.id}",
                existing_observation_id=created.id,
            )
        )

    return results


def _find_overlap(
    existing: list[ScheduledObservation],
    candidate: PassWindow,
) -> ScheduledObservation | None:
    """Return an existing observation that covers the same pass window."""
    tolerance = timedelta(minutes=2)
    for observation in existing:
        if (
            abs(observation.start - candidate.start) <= tolerance
            or abs(observation.end - candidate.end) <= tolerance
            or (observation.start <= candidate.start and observation.end >= candidate.end)
        ):
            return observation
    return None
