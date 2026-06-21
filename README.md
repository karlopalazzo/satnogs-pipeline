# SatNOGS Pipeline

SatNOGS pipeline for scheduling METEOR M2-3/M2-4 observations from my Raspberry Pi ground station.

## Architecture

- GitHub Actions: run tests and validate code
- Raspberry Pi cron: schedules observations through SatNOGS Network API
- SatNOGS client: executes RF observations
- Local archive: future post-observation decoding and storage

## Current scope

- Loads targets from YAML
- Predicts satellite passes using TLE + Skyfield
- Skips already scheduled observations
- Supports dry-run and live scheduling
- Includes pytest coverage and CI

## Usage

```bash
cp .env.example .env
# set SATNOGS_API_TOKEN

./scripts/run_schedule.sh --dry-run
./scripts/run_schedule.sh