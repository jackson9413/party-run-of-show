# Party Run-of-Show

**Local-first party sequencing workbench.** Paste the occasion (birthday / game night / dinner party / holiday / reunion / kids party / couples night / work offsite), get a minute-by-minute run-of-show calibrated to group size, ages, energy curve, conflict-avoidance, and a 0–100 night-readiness score.

This is the missing **sequencing** layer between *what to play* (game-night-picker) and *what to talk about* (dinner-party-deck). It doesn't pick the games or the prompts — it **stages the night** so the energy arc works.

## Features

- **8 occasion templates** — birthday / game_night / dinner_party / holiday / reunion / kids_party / couples_night / work_offsite
- **6 block kinds** — welcome / opener / main / intermission / closer / wind_down
- **Energy arc enforcement** — every run-of-show follows a 5-stage arc: warm → ignite → sustain → release → wind-down (no two adjacent blocks share the same energy level)
- **30 hand-curated block library** — each block has duration, energy level, materials, group-size sweet spot, age range, noise tolerance, conflict-avoidance profile
- **Auto timing fit** — paste your window (e.g. "7pm–10pm, 3 hours") and blocks are auto-packed and trimmed
- **0–100 readiness score** across 5 axes (Occasion Fit / Energy Arc / Timing Fit / Group Fit / Conflict Safety)
- **Auto-generated insights & flags** — e.g. "Block 4 is too quiet right after Block 3's high-energy peak", "Mismatch: kid-coded block in adults-only occasion"
- **Markdown + JSON export**
- **SQLite session log** with 1–5 star ratings + notes

## Quick Start

```bash
cd party-run-of-show
pip install -r requirements.txt
python app.py
# open http://localhost:5003
```

## Stack

- Python 3 / Flask
- SQLite (sessions + ratings)
- Vanilla JS frontend (no build step)
- Hand-rolled SVG score ring
- No external APIs, no LLM

## Tests

```bash
python -m pytest tests/ -v
```

## API

- `GET /` — UI
- `POST /api/generate` — generate run-of-show
- `POST /api/rate` — save session rating
- `GET /api/sessions` — session history
- `GET /api/export/<id>.md` — export markdown
- `GET /api/export/<id>.json` — export JSON
