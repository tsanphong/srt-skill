#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -X utf8 scripts/prepare_env.py
exec .venv/bin/python -X utf8 -m app.server
