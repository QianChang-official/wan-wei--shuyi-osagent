#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/secrets/wanwei_api_key.txt}"
ENV_FILE="${2:-$ROOT/.env}"
if [ -e "$TARGET" ] && [ "${WANWEI_FORCE_SECRET_ROTATION:-0}" != "1" ]; then
  echo "Secret already exists: $TARGET. Set WANWEI_FORCE_SECRET_ROTATION=1 to rotate it." >&2
  exit 1
fi
mkdir -p "$(dirname "$TARGET")"
mkdir -p "$(dirname "$ENV_FILE")"
umask 077
python3 - "$TARGET" "$ENV_FILE" <<'PY'
import base64
import re
import secrets
import sys
from pathlib import Path

target = Path(sys.argv[1])
env_file = Path(sys.argv[2])
api_key = secrets.token_urlsafe(48)

with target.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(api_key + "\n")

lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
existing_key = None
for line in lines:
    if re.match(r"^\s*WANWEI_ENCRYPTION_KEY\s*=", line):
        candidate = line.split("=", 1)[1].strip()
        if candidate:
            existing_key = candidate
encryption_key = existing_key or base64.urlsafe_b64encode(
    secrets.token_bytes(32)
).decode("ascii")
updated = []
replaced = False
for line in lines:
    if re.match(r"^\s*WANWEI_ENCRYPTION_KEY\s*=", line):
        if not replaced:
            updated.append(f"WANWEI_ENCRYPTION_KEY={encryption_key}")
            replaced = True
        continue
    updated.append(line)
if not replaced:
    updated.append(f"WANWEI_ENCRYPTION_KEY={encryption_key}")
with env_file.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(updated) + "\n")
PY
chmod 600 "$TARGET"
chmod 600 "$ENV_FILE"
echo "API secret created at $TARGET; encryption key ensured in $ENV_FILE. The values were not printed."
