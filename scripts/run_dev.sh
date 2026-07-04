#!/usr/bin/env bash
set -e
cd backend
python -m app.init_db
uvicorn app.main:app --host 127.0.0.1 --port 8765
