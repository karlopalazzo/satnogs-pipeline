#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

CONTAINER_NAME = "satnogs_satnogs-client"
CONTAINER_IQ_DIR = "/tmp/.satnogs/data"
HOST_WORK_DIR = Path("/home/palac/satnogs-decode")
HOST_RAW_DIR = HOST_WORK_DIR / "raw"
HOST_OUTPUT_DIR = HOST_WORK_DIR / "output"
SATDUMP_WORKDIR = Path("/usr/share/satdump")
SATDUMP_SAMPLERATE = "160000"
SATDUMP_BASEBAND_FORMAT = "cs16"
PIPELINE_ID = "meteor_m2-x_lrpt"
SATDUMP_TIMEOUT_SEC = 240
DEFAULT_STATION_ID = 4924
DECODE_MARKER = "decode.ok"
UPLOAD_MARKER = "upload.ok"
NETWORK_API_BASE = "https://network.satnogs.org/api"
NORAD_TO_LABEL = {
    40069: "METEOR-M-2",
    57166: "METEOR-M2-3",
    59051: "METEOR-M2-4",
}

IQ_NAME_RE = re.compile(r"^iq_cs16_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.raw$")


def _run(cmd: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def list_iq_files_in_container(*, day: date | None = None) -> list[str]:
    pattern = "iq_cs16_*.raw"
    if day is not None:
        pattern = f"iq_cs16_{day.isoformat()}T*.raw"
    cmd = [
        "sudo",
        "docker",
        "exec",
        CONTAINER_NAME,
        "sh",
        "-lc",
        # POSIX ls sorted by mtime descending; ignore missing matches.
        f"ls -1t {CONTAINER_IQ_DIR}/{pattern} 2>/dev/null || true",
    ]
    result = _run(cmd, capture_output=True)
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [Path(item).name for item in files]


def choose_iq_filenames(
    explicit_name: str | None,
    *,
    day: date,
) -> list[str]:
    if explicit_name:
        if not IQ_NAME_RE.match(explicit_name):
            raise ValueError(f"Invalid IQ filename format: {explicit_name}")
        return [explicit_name]

    files = list_iq_files_in_container(day=day)
    if not files:
        raise RuntimeError(f"No iq_cs16_*.raw files found in container for {day.isoformat()}.")
    # Decode oldest -> newest for easier chronological tracing.
    return sorted(files)


def copy_iq_to_host(iq_name: str) -> Path:
    HOST_RAW_DIR.mkdir(parents=True, exist_ok=True)
    source_in_container = f"{CONTAINER_IQ_DIR}/{iq_name}"
    destination_on_host = HOST_RAW_DIR / iq_name

    cmd = [
        "sudo",
        "docker",
        "exec",
        CONTAINER_NAME,
        "sh",
        "-lc",
        f"cat {source_in_container}",
    ]
    with destination_on_host.open("wb") as out_file:
        subprocess.run(cmd, check=True, stdout=out_file)

    return destination_on_host


def _extract_timestamp(iq_name: str) -> str:
    match = IQ_NAME_RE.match(iq_name)
    if not match:
        raise ValueError(f"Cannot extract timestamp from IQ filename: {iq_name}")
    return match.group(1)


def _timestamp_to_datetime_utc(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)


def _find_matching_observation(
    *,
    timestamp_utc: datetime,
    station_id: int,
    session: requests.Session,
) -> tuple[int | None, int | None]:
    target_day = timestamp_utc.date()
    try:
        best_match: tuple[float, int] | None = None
        best_obs_id: int | None = None
        for norad in NORAD_TO_LABEL:
            response = session.get(
                f"{NETWORK_API_BASE}/observations/",
                params={
                    "ground_station": station_id,
                    "norad_cat_id": norad,
                    "limit": 100,
                },
                timeout=20,
            )
            response.raise_for_status()
            for item in response.json():
                obs_start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
                if obs_start.date() != target_day:
                    continue
                delta_sec = abs((obs_start - timestamp_utc).total_seconds())
                # file timestamp can differ by ~1s from observation start
                if delta_sec > 180:
                    continue
                if best_match is None or delta_sec < best_match[0]:
                    best_match = (delta_sec, norad)
                    best_obs_id = int(item["id"])
        if best_match is not None and best_obs_id is not None:
            return best_match[1], best_obs_id
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None, None


def detect_satellite_label(norad_id: int | None) -> str:
    if norad_id is None:
        return "METEOR-M2-x"
    return NORAD_TO_LABEL.get(norad_id, "METEOR-M2-x")


def output_dir_for_iq_name(iq_name: str, *, satellite_label: str) -> Path:
    timestamp = _extract_timestamp(iq_name)
    day = timestamp.split("T", 1)[0]
    out_dir = HOST_OUTPUT_DIR / satellite_label / day / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run_satdump(input_raw: Path, output_dir: Path) -> None:
    cmd = [
        "satdump",
        "pipeline",
        PIPELINE_ID,
        f"--samplerate={SATDUMP_SAMPLERATE}",
        f"--baseband_format={SATDUMP_BASEBAND_FORMAT}",
        "baseband",
        str(input_raw),
        str(output_dir),
    ]
    subprocess.run(cmd, check=True, cwd=SATDUMP_WORKDIR, timeout=SATDUMP_TIMEOUT_SEC)


def decode_marker_path(output_dir: Path) -> Path:
    return output_dir / DECODE_MARKER


def is_already_decoded(output_dir: Path) -> bool:
    return decode_marker_path(output_dir).exists()


def write_decode_marker(output_dir: Path, *, iq_name: str, host_raw: Path) -> None:
    marker = decode_marker_path(output_dir)
    marker.write_text(
        "\n".join(
            [
                f"decoded_at={datetime.now(UTC).isoformat().replace('+00:00', 'Z')}",
                f"iq_name={iq_name}",
                f"host_raw={host_raw}",
                f"pipeline={PIPELINE_ID}",
                f"samplerate={SATDUMP_SAMPLERATE}",
                f"baseband_format={SATDUMP_BASEBAND_FORMAT}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def upload_marker_path(output_dir: Path) -> Path:
    return output_dir / UPLOAD_MARKER


def is_already_uploaded(output_dir: Path) -> bool:
    return upload_marker_path(output_dir).exists()


def write_upload_marker(output_dir: Path, *, observation_id: int, image_path: Path) -> None:
    marker = upload_marker_path(output_dir)
    marker.write_text(
        "\n".join(
            [
                f"uploaded_at={datetime.now(UTC).isoformat().replace('+00:00', 'Z')}",
                f"observation_id={observation_id}",
                f"image={image_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def choose_upload_image(output_dir: Path) -> Path | None:
    preferred = output_dir / "MSU-MR" / "msu_mr_AVHRR_3a21_False_Color_(uncalibrated).png"
    if preferred.exists() and preferred.stat().st_size > 0:
        return preferred
    fallback = sorted((output_dir / "MSU-MR").glob("*.png"))
    for candidate in fallback:
        if candidate.stat().st_size > 0:
            return candidate
    return None


def upload_demoddata(
    *,
    observation_id: int,
    image_path: Path,
    api_token: str,
    session: requests.Session,
) -> bool:
    url = f"{NETWORK_API_BASE}/observations/{observation_id}/"
    headers = {"Authorization": f"Token {api_token}"}
    with image_path.open("rb") as image_file:
        response = session.put(
            url,
            headers=headers,
            files={"demoddata": image_file},
            timeout=30,
        )
    if response.status_code == 403 and "has already been uploaded" in response.text:
        return True
    response.raise_for_status()
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy METEOR IQ dump(s) from SatNOGS container and decode with SatDump. "
            "Default mode decodes all dumps from previous UTC day."
        ),
    )
    parser.add_argument(
        "--iq-file",
        help=(
            "Specific iq_cs16_*.raw filename from container. "
            "If omitted, all dumps for --date are processed."
        ),
    )
    parser.add_argument(
        "--date",
        help=(
            "UTC date in YYYY-MM-DD. Used in batch mode. "
            "If omitted, previous UTC day is used."
        ),
    )
    parser.add_argument(
        "--station-id",
        type=int,
        default=DEFAULT_STATION_ID,
        help=f"SatNOGS station ID used for satellite label lookup (default: {DEFAULT_STATION_ID}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-decode even if decode.ok already exists.",
    )
    parser.add_argument(
        "--upload-data",
        action="store_true",
        help="Upload decoded color image as demoddata to SatNOGS observation Data tab.",
    )
    parser.add_argument(
        "--api-token",
        help="SatNOGS API token for upload. If omitted, SATNOGS_API_TOKEN env var is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected files and output paths without copying/decoding.",
    )
    return parser.parse_args(argv)


def parse_target_day(date_arg: str | None) -> date:
    if date_arg:
        try:
            return date.fromisoformat(date_arg)
        except ValueError as exc:
            raise ValueError(f"Invalid --date value: {date_arg}. Use YYYY-MM-DD.") from exc
    return (datetime.now(UTC) - timedelta(days=1)).date()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target_day = parse_target_day(args.date)
        iq_files = choose_iq_filenames(args.iq_file, day=target_day)
        failures = 0
        decoded = 0
        skipped = 0
        uploaded = 0
        upload_skipped = 0

        api_token = args.api_token or os.environ.get("SATNOGS_API_TOKEN")
        if args.upload_data and not api_token:
            raise ValueError("--upload-data requires SATNOGS_API_TOKEN env var or --api-token.")

        print(f"Target day (UTC): {target_day.isoformat()}")
        print(f"Found IQ files: {len(iq_files)}")

        session = requests.Session()
        for iq_name in iq_files:
            timestamp = _extract_timestamp(iq_name)
            ts_utc = _timestamp_to_datetime_utc(timestamp)
            norad_id, observation_id = _find_matching_observation(
                timestamp_utc=ts_utc,
                station_id=args.station_id,
                session=session,
            )
            satellite_label = detect_satellite_label(norad_id)
            out_dir = output_dir_for_iq_name(iq_name, satellite_label=satellite_label)

            print(f"\nIQ file: {iq_name}")
            print(f"Satellite: {satellite_label}")
            if observation_id:
                print(f"Observation ID: {observation_id}")
            print(f"Output directory: {out_dir}")

            decode_done = is_already_decoded(out_dir) and not args.force
            if decode_done:
                print("Skip decode: decode.ok exists.")
                skipped += 1
            elif not args.dry_run:
                try:
                    host_raw = copy_iq_to_host(iq_name)
                    print(f"Copied to host: {host_raw}")
                    run_satdump(host_raw, out_dir)
                    write_decode_marker(out_dir, iq_name=iq_name, host_raw=host_raw)
                    print(f"Decode finished. Images in: {out_dir / 'MSU-MR'}")
                    decoded += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    print(f"Decode failed for {iq_name}: {exc}", file=sys.stderr)
                    failures += 1
                    continue

            if args.upload_data:
                if not observation_id:
                    print("Skip upload: no matching observation ID found.")
                    upload_skipped += 1
                    continue
                if is_already_uploaded(out_dir):
                    print("Skip upload: upload.ok exists.")
                    upload_skipped += 1
                    continue
                image_path = choose_upload_image(out_dir)
                if image_path is None:
                    print("Skip upload: no decoded PNG found.")
                    upload_skipped += 1
                    continue
                if args.dry_run:
                    print(f"Dry-run upload: would send {image_path.name} to observation {observation_id}.")
                    continue
                try:
                    upload_demoddata(
                        observation_id=observation_id,
                        image_path=image_path,
                        api_token=api_token,
                        session=session,
                    )
                    write_upload_marker(out_dir, observation_id=observation_id, image_path=image_path)
                    print(f"Upload finished: {image_path.name} -> observation {observation_id} Data tab.")
                    uploaded += 1
                except requests.RequestException as exc:
                    print(f"Upload failed for {iq_name}: {exc}", file=sys.stderr)
                    failures += 1

        print(
            f"\nSummary: decoded={decoded}, decode_skipped={skipped}, "
            f"uploaded={uploaded}, upload_skipped={upload_skipped}, failures={failures}, "
            f"total={len(iq_files)}"
        )
        return 1 if failures else 0
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())