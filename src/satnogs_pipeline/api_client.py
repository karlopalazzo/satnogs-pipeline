"""Thin wrapper around the SatNOGS Network REST API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlencode

import requests


NETWORK_API = "https://network.satnogs.org/api"
DB_API = "https://db.satnogs.org/api"


@dataclass(frozen=True)
class ScheduledObservation:
    id: int
    start: datetime
    end: datetime
    norad_cat_id: int
    transmitter_uuid: str
    status: str


class SatnogsNetworkClient:
    def __init__(self, token: str | None = None, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("Accept", "application/json")
        if token:
            self._session.headers["Authorization"] = f"Token {token}"

    def list_future_observations(
        self,
        *,
        station_id: int,
        norad_cat_id: int | None = None,
    ) -> list[ScheduledObservation]:
        params: dict[str, Any] = {
            "ground_station": station_id,
            "status": "future",
            "limit": 100,
        }
        if norad_cat_id is not None:
            params["norad_cat_id"] = norad_cat_id

        payload = self._get(f"{NETWORK_API}/observations/", params=params)
        items = payload if isinstance(payload, list) else payload.get("results", [])
        return [self._parse_observation(item) for item in items]

    def schedule_observation(
        self,
        *,
        station_id: int,
        transmitter_uuid: str,
        start: datetime,
        end: datetime,
    ) -> ScheduledObservation:
        body = {
            "ground_station": station_id,
            "transmitter": transmitter_uuid,
            "start": _format_utc(start),
            "end": _format_utc(end),
        }
        payload = self._post(f"{NETWORK_API}/observations/", json=body)
        return self._parse_observation(payload)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _post(self, url: str, json: dict[str, Any]) -> Any:
        response = self._session.post(url, json=json, timeout=30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_observation(item: dict[str, Any]) -> ScheduledObservation:
        return ScheduledObservation(
            id=int(item["id"]),
            start=_parse_utc(item["start"]),
            end=_parse_utc(item["end"]),
            norad_cat_id=int(item["norad_cat_id"]),
            transmitter_uuid=str(item["transmitter"]),
            status=str(item.get("status", "")),
        )


def fetch_tle(norad_cat_id: int, session: requests.Session | None = None) -> tuple[str, str, str]:
    """Download the latest TLE for a NORAD catalog ID."""
    session = session or requests.Session()
    try:
        return _fetch_tle_from_satnogs_db(norad_cat_id, session)
    except (requests.RequestException, RuntimeError):
        return _fetch_tle_from_celestrak(norad_cat_id, session)


def _fetch_tle_from_satnogs_db(
    norad_cat_id: int,
    session: requests.Session,
) -> tuple[str, str, str]:
    response = session.get(
        f"{DB_API}/tle/",
        params={"norad_cat_id": norad_cat_id, "limit": 1},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        raise RuntimeError(f"No TLE returned for NORAD {norad_cat_id}")
    entry = payload[0]
    return str(entry["tle0"]), str(entry["tle1"]), str(entry["tle2"])


def _fetch_tle_from_celestrak(
    norad_cat_id: int,
    session: requests.Session,
) -> tuple[str, str, str]:
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_cat_id}&FORMAT=TLE"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise RuntimeError(f"No TLE returned for NORAD {norad_cat_id}")
    return lines[0], lines[1], lines[2]


def _parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
