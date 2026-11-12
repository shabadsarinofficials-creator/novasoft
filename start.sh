#!/usr/bin/env bash
# BizSuite production entrypoint for Render (and local prod-like runs).
# One process serves API + frontend. No separate web server required.
set -euo pipefail

cd "$(dirname "$0")"

echo "[BizSuite] Applying database migrations..."
python -c "
from alembic.config import Config
from alembic import command
cfg = Config('alembic.ini')
command.upgrade(cfg, 'head')
print('[BizSuite] Migrations OK')
" || {
  echo "[BizSuite] Alembic failed — attempting SQLAlchemy create_all fallback..."
  python -c "
from backend.database import engine, Base
from backend import models  # noqa: F401 — register models
Base.metadata.create_all(bind=engine)
print('[BizSuite] create_all OK')
"
}

echo "[BizSuite] Starting built-in server (uvicorn) on 0.0.0.0:${PORT:-8000}"
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
