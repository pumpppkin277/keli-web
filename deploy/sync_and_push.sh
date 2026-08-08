#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/keli-pages-sync/repo"

cd "$REPO_DIR"
git pull --ff-only origin main
KELI_API_BASE="http://127.0.0.1" python3 scripts/sync_data.py
git add data

if git diff --cached --quiet; then
  exit 0
fi

git config user.name "keli-data-bot"
git config user.email "keli-data-bot@users.noreply.github.com"
git commit -m "Update public hotel data"
git push origin main
