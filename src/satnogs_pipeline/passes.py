"""Predict satellite passes above a ground station."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from skyfield.api import EarthSatellite, load, wgs84
from skyfield.timelib import Time


@dataclass(frozen=True)
class PassWindow:
    start: datetime
    end: datetime
    max_elevation_deg: float


def predict_passes(
    *,
    tle_name: str,
    tle_line1: str,
    tle_line2: str,
    latitude: float,
    longitude: float,
    elevation_m: float,
    start: datetime,
    end: datetime,
    min_elevation_deg: float,
) -> list[PassWindow]:
    """Return pass windows whose peak elevation meets the configured threshold."""
    ts = load.timescale()
    satellite = EarthSatellite(tle_line1, tle_line2, tle_name, ts)
    station = wgs84.latlon(latitude, longitude, elevation_m=elevation_m)

    t0 = ts.from_datetime(start.astimezone(timezone.utc))
    t1 = ts.from_datetime(end.astimezone(timezone.utc))

    passes: list[PassWindow] = []
    t_events, events = satellite.find_events(station, t0, t1, altitude_degrees=min_elevation_deg)

    event_names = ("rise", "culminate", "set")
    current_rise: Time | None = None
    current_max_el = 0.0

    for t_event, event_id in zip(t_events, events):
        event = event_names[event_id]
        if event == "rise":
            current_rise = t_event
            current_max_el = 0.0
        elif event == "culminate" and current_rise is not None:
            topocentric = (satellite - station).at(t_event)
            alt, _, _ = topocentric.altaz()
            current_max_el = max(current_max_el, float(alt.degrees))
        elif event == "set" and current_rise is not None:
            passes.append(
                PassWindow(
                    start=current_rise.utc_datetime().replace(tzinfo=timezone.utc),
                    end=t_event.utc_datetime().replace(tzinfo=timezone.utc),
                    max_elevation_deg=current_max_el,
                )
            )
            current_rise = None
            current_max_el = 0.0

    return passes


def default_planning_window(*, lookahead_hours: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    return now, now + timedelta(hours=lookahead_hours)
