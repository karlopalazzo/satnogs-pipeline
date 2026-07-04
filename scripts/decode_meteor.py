#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
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
NORAD_TO_LABEL = {
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


def detect_satellite_label(*, timestamp_utc: datetime, station_id: int) -> str:
    target_day = timestamp_utc.date()
    try:
        best_match: tuple[float, int] | None = None
        for norad in NORAD_TO_LABEL:
            response = requests.get(
                "https://network.satnogs.org/api/observations/",
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
        if best_match is not None:
            return NORAD_TO_LABEL[best_match[1]]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return "METEOR-M2-x"


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

        print(f"Target day (UTC): {target_day.isoformat()}")
        print(f"Found IQ files: {len(iq_files)}")

        for iq_name in iq_files:
            timestamp = _extract_timestamp(iq_name)
            ts_utc = _timestamp_to_datetime_utc(timestamp)
            satellite_label = detect_satellite_label(timestamp_utc=ts_utc, station_id=args.station_id)
            out_dir = output_dir_for_iq_name(iq_name, satellite_label=satellite_label)

            print(f"\nIQ file: {iq_name}")
            print(f"Satellite: {satellite_label}")
            print(f"Output directory: {out_dir}")

            if is_already_decoded(out_dir) and not args.force:
                print("Skip: decode.ok exists.")
                skipped += 1
                continue

            if args.dry_run:
                continue

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

        print(
            f"\nSummary: decoded={decoded}, skipped={skipped}, failures={failures}, "
            f"total={len(iq_files)}"
        )
        return 1 if failures else 0
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())