from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import responses

from satnogs_pipeline.api_client import SatnogsNetworkClient, fetch_tle
from satnogs_pipeline.config import load_config
from satnogs_pipeline.scheduler import plan_observations
from satnogs_pipeline.passes import PassWindow


@responses.activate
def test_fetch_tle_parses_satnogs_db_response() -> None:
    responses.add(
        responses.GET,
        "https://db.satnogs.org/api/tle/",
        json=[
            {
                "tle0": "METEOR M2-3",
                "tle1": "1 57166U 23057A   25155.12345678  .00000012  00000-0  12345-4 0  9993",
                "tle2": "2 57166  98.7123  45.6789 0012345 123.4567 236.7890 14.12345678901234",
            }
        ],
        match=[responses.matchers.query_param_matcher({"norad_cat_id": "57166", "limit": "1"})],
    )

    name, line1, line2 = fetch_tle(57166)
    assert name == "METEOR M2-3"
    assert line1.startswith("1 57166U")
    assert line2.startswith("2 57166")


@responses.activate
def test_plan_observations_skips_existing_future_pass(monkeypatch) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config" / "targets.yaml")

    start = datetime(2026, 6, 13, 19, 17, 10, tzinfo=timezone.utc)
    end = start + timedelta(minutes=8)

    def fake_predict_passes(**kwargs):
        return [
            PassWindow(
                start=start,
                end=end,
                max_elevation_deg=88.0,
            )
        ]

    monkeypatch.setattr(
        "satnogs_pipeline.scheduler.fetch_tle",
        lambda norad_cat_id: ("METEOR", "line1", "line2"),
    )
    monkeypatch.setattr(
        "satnogs_pipeline.scheduler.predict_passes",
        fake_predict_passes,
    )

    responses.add(
        responses.GET,
        "https://network.satnogs.org/api/observations/",
        json=[
            {
                "id": 14297703,
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": end.isoformat().replace("+00:00", "Z"),
                "norad_cat_id": 57166,
                "transmitter": "Qc2PqaS7n9WYtne3U9EmKJ",
                "status": "future",
            }
        ],
        match=[
            responses.matchers.query_param_matcher(
                {
                    "ground_station": "4924",
                    "status": "future",
                    "limit": "100",
                    "norad_cat_id": "57166",
                }
            )
        ],
    )
    responses.add(
        responses.GET,
        "https://network.satnogs.org/api/observations/",
        json=[],
        match=[
            responses.matchers.query_param_matcher(
                {
                    "ground_station": "4924",
                    "status": "future",
                    "limit": "100",
                    "norad_cat_id": "40069",
                }
            )
        ],
    )
    responses.add(
        responses.GET,
        "https://network.satnogs.org/api/observations/",
        json=[],
        match=[
            responses.matchers.query_param_matcher(
                {
                    "ground_station": "4924",
                    "status": "future",
                    "limit": "100",
                    "norad_cat_id": "59051",
                }
            )
        ],
    )

    client = SatnogsNetworkClient(token="test-token")
    plan = plan_observations(
        config,
        client=client,
        now=datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc),
    )

    skipped = [
        item
        for item in plan
        if item.target.norad_cat_id == 57166 and item.action == "skip"
    ]

    assert len(skipped) == 1
    assert skipped[0].existing_observation_id == 14297703
    assert skipped[0].reason == "already scheduled"
