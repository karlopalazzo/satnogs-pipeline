#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

CONTAINER_NAME = "satnogs_satnogs-client"
CONTAINER_IQ_DIR = "/tmp/.satnogs/data"
HOST_WORK_DIR = Path("/home/palac/satnogs-decode")
HOST_RAW_DIR = HOST_WORK_DIR / "raw"
HOST_OUTPUT_DIR = HOST_WORK_DIR / "output"
SATDUMP_WORKDIR = Path("/usr/share/satdump")
SATDUMP_SAMPLERATE = "160000"
SATDUMP_BASEBAND_FORMAT = "cs16"
PIPELINE_ID = "meteor_m2-x_lrpt"

IQ_NAME_RE = re.compile(r"^iq_cs16_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.raw$")


def _run(cmd: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def list_iq_files_in_container() -> list[str]:
    cmd = [
        "sudo",
        "docker",
        "exec",
        CONTAINER_NAME,
        "sh",
        "-lc",
        # POSIX ls sorted by mtime descending; ignore missing matches.
        f"ls -1t {CONTAINER_IQ_DIR}/iq_cs16_*.raw 2>/dev/null || true",
    ]
    result = _run(cmd, capture_output=True)
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [Path(item).name for item in files]


def choose_iq_filename(explicit_name: str | None) -> str:
    if explicit_name:
        if not IQ_NAME_RE.match(explicit_name):
            raise ValueError(f"Invalid IQ filename format: {explicit_name}")
        return explicit_name

    files = list_iq_files_in_container()
    if not files:
        raise RuntimeError("No iq_cs16_*.raw files found in container.")
    return files[0]


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


def output_dir_for_iq_name(iq_name: str) -> Path:
    match = IQ_NAME_RE.match(iq_name)
    if not match:
        raise ValueError(f"Cannot extract timestamp from IQ filename: {iq_name}")
    timestamp = match.group(1)
    out_dir = HOST_OUTPUT_DIR / timestamp
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
    subprocess.run(cmd, check=True, cwd=SATDUMP_WORKDIR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy METEOR IQ dump from SatNOGS container and decode with SatDump.",
    )
    parser.add_argument(
        "--iq-file",
        help="Specific iq_cs16_*.raw filename from container. If omitted, newest file is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected file and output path without copying/decoding.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        iq_name = choose_iq_filename(args.iq_file)
        out_dir = output_dir_for_iq_name(iq_name)

        print(f"Selected IQ file: {iq_name}")
        print(f"Output directory: {out_dir}")

        if args.dry_run:
            return 0

        host_raw = copy_iq_to_host(iq_name)
        print(f"Copied to host: {host_raw}")

        run_satdump(host_raw, out_dir)
        print(f"Decode finished. Images in: {out_dir / 'MSU-MR'}")
        return 0
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())