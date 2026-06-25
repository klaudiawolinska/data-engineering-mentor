#!/usr/bin/env bash
set -euo pipefail

# Always run from the script's own directory
cd "$(dirname "$0")"

# Warn (don't block) if no API key is configured
if [ ! -f ".env" ]; then
  echo "⚠  No .env found — copy .env.example to .env and add your OPENAI_API_KEY."
  echo "   The app will start, but challenge generation will fail until you do."
fi

# Keep uv.lock current with pyproject.toml, then regenerate the pip /
# Streamlit-Cloud fallback (requirements.txt) — but only when the lock actually
# changed, so launches stay churn-free. requirements.txt is generated; don't edit it.
uv lock --quiet
if [ uv.lock -nt requirements.txt ]; then
  uv export --frozen --no-hashes --quiet -o requirements.txt
  echo "→ refreshed requirements.txt from uv.lock"
fi

# uv creates/updates .venv from uv.lock automatically, then launches.
# (exec so Ctrl-C stops Streamlit cleanly.)
echo "→ Starting Streamlit at http://localhost:8501"
exec uv run streamlit run app.py
