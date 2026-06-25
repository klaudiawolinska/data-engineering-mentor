# ⚡ Data Engineering AI Mentor

A daily practice environment for data engineers at every level. Not a course, not a tutorial — a sparring partner.

You get a realistic challenge sized to your level, work through it with a Socratic AI mentor that pushes your reasoning, then receive an honest assessment that feeds your skill tree and picks your next challenge.

## Core loop (15–30 min/day)

1. **Daily Challenge** — a realistic scenario, sized to your level
2. **Socratic conversation** — the mentor asks, nudges, pushes back; it doesn't hand you answers
3. **Assessment** — honest score, strengths, gaps, next focus
4. **Skill tree** — XP and levels across 26 domains
5. **Streaks & achievements** — adult gamification, no coins or gems
6. **Personalized next challenge** — weighted toward your weaker domains

## Domains

SQL · Python · Spark · Airflow · Kafka · Databricks · Iceberg · Delta Lake · Snowflake · dbt · ETL / ELT · Stream Processing · Data Quality · Data Modeling · Data Governance · System Design · AWS · Terraform / IaC · Linux · Bash · Docker · Kubernetes · Git · CI/CD · Monitoring · Observability

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/). The one-liner:

```bash
cp .env.example .env      # then add your OPENAI_API_KEY
./run.sh                  # uv creates .venv from uv.lock and launches
```

`./run.sh` runs `uv run streamlit run app.py` — uv provisions the environment
from `uv.lock` automatically (no activate/install step). To run it yourself:

```bash
uv run streamlit run app.py
```

No uv? A plain-pip path also works via `requirements.txt` (handy if you'd rather not
install uv):

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && streamlit run app.py
```

Open http://localhost:8501 and enter your name to begin.

### Managing dependencies

`pyproject.toml` + `uv.lock` are the source of truth. Add or remove deps with uv:

```bash
uv add <package>      # updates pyproject.toml and uv.lock
```

`requirements.txt` is **generated** (a pinned export of the lock for pip-based
setups) — **don't hand-edit it**. `./run.sh` regenerates it via
`uv export` whenever the lock changes. To refresh it manually:

```bash
uv export --frozen --no-hashes -o requirements.txt
```

## Architecture

| File | Responsibility |
|------|----------------|
| `app.py` | Streamlit UI — Home, Session, Skills, History views |
| `ai.py` | OpenAI calls — challenge generation, mentor chat, assessment |
| `db.py` | SQLite layer — users, skills, sessions, streaks, achievements |
| `achievements.py` | Achievement definitions + unlock logic |

Stack: Streamlit · Python · SQLite · OpenAI API. Single-process, file-backed, zero infra. Runs locally.

## Design choices

- **Lazy OpenAI client** — app imports and runs without a key; you only hit the wall when generating.
- **Sessions persist mid-conversation** — close the tab, resume from Home.
- **Domain selection is weighted** — lower-level domains surface more often, with a 3-session anti-repeat window.
- **One model (`gpt-4o`)** everywhere for simplicity; swap in `ai.py` if you want cheaper assessment.

## Backups

Daily snapshots of your DB live in `data/backups/` (last 7 days kept).
Restore by copying one back over the live DB:

```bash
cp data/backups/mentor-2026-06-23.db data/mentor.db
```
