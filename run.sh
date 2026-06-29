#!/usr/bin/env bash
# Dev launcher. First run sets up a venv and installs deps.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv + installing deps..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

echo "Starting on http://127.0.0.1:8000  (mode = mock unless .env is filled)"
./.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
