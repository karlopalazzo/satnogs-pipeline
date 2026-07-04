# SatNOGS Pipeline

SatNOGS pipeline for scheduling and decoding METEOR observations from a Raspberry Pi ground station.

## What This Project Does

- Plans METEOR observations for the next 24 hours through SatNOGS Network API.
- Avoids duplicate scheduling by checking already planned future observations.
- Collects IQ dumps from SatNOGS client container and decodes them with SatDump.
- Runs daily in cron mode (scheduler + decode batch from previous UTC day).
- Keeps tests in GitHub Actions for Python scheduling logic.

## Architecture

- **GitHub Actions**: run tests and validate Python code.
- **Raspberry Pi cron**: daily automation entry point.
- **Scheduler (`scripts/run_schedule.sh`)**: plans next 24h observations.
- **SatNOGS client container**: executes RF observations and stores IQ dumps.
- **Decoder (`scripts/decode_meteor.py`)**: copies IQ to host and decodes with SatDump.
- **Local output archive**: stores decoded products and per-run markers.

## Repository Structure

- `config/targets.yaml` - station metadata and METEOR targets.
- `src/satnogs_pipeline/` - scheduler/business logic.
- `scripts/run_schedule.sh` - wrapper for scheduler runs.
- `scripts/decode_meteor.py` - daily/batch decode utility.
- `scripts/post_observation.sh` - post-observation logging hook (container side).
- `.github/workflows/ci.yml` - tests in CI.

## Prerequisites

- Raspberry Pi with SatNOGS client running.
- Python virtual environment in this repository (`.venv`).
- SatDump installed on host.
- `SATNOGS_API_TOKEN` in `.env` for live scheduling.

## Setup

```bash
cd /home/palac/satnogs-pipeline
cp .env.example .env
# edit .env and set SATNOGS_API_TOKEN

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Scheduler Usage

Dry-run:

```bash
./scripts/run_schedule.sh --dry-run
```

Live run:

```bash
./scripts/run_schedule.sh
```

## Decode Usage

Decode all IQ dumps from previous UTC day:

```bash
.venv/bin/python scripts/decode_meteor.py
```

Decode a specific UTC day:

```bash
.venv/bin/python scripts/decode_meteor.py --date 2026-07-02
```

Decode a single specific IQ file:

```bash
.venv/bin/python scripts/decode_meteor.py --iq-file iq_cs16_2026-07-02T20-16-53.raw
```

Preview planned work without decoding:

```bash
.venv/bin/python scripts/decode_meteor.py --date 2026-07-02 --dry-run
```

Force re-decode even if marker exists:

```bash
.venv/bin/python scripts/decode_meteor.py --date 2026-07-02 --force
```

## Daily Cron Automation

Example crontab entries:

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Plan next 24h observations
10 0 * * * cd "/home/palac/satnogs-pipeline" && mkdir -p logs && ./scripts/run_schedule.sh >> "/home/palac/satnogs-pipeline/logs/cron_schedule.log" 2>&1

# Decode previous UTC day
40 0 * * * cd "/home/palac/satnogs-pipeline" && mkdir -p logs && ./.venv/bin/python scripts/decode_meteor.py --date "$(date -u -d 'yesterday' +\%F)" >> "/home/palac/satnogs-pipeline/logs/cron_decode.log" 2>&1
```

## Data Paths

- **Container IQ input**: `/tmp/.satnogs/data/iq_cs16_*.raw`
- **Host copied IQ**: `/home/palac/satnogs-decode/raw/`
- **Decoded output**: `/home/palac/satnogs-decode/output/<satellite>/<YYYY-MM-DD>/<timestamp>/`
- **Decode marker**: `decode.ok` inside each decoded output directory

## Logs

- Scheduler cron log: `logs/cron_schedule.log`
- Decode cron log: `logs/cron_decode.log`
- Hook log (container bind mount): `/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free/hooks/logs/post_observation.log`

## Validation

Run tests locally:

```bash
PYTHONPATH=src .venv/bin/pytest -q
```

## Notes

- Decode uses SatDump `meteor_m2-x_lrpt` pipeline with `--samplerate=160000` and `--baseband_format=cs16`.
- Daily decode is idempotent due to `decode.ok` marker files.
- UTC date is used for batch selection to avoid timezone boundary issues.