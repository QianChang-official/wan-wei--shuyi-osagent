#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/secrets/wanwei_api_key.txt}"
if [ -e "$TARGET" ] && [ "${WANWEI_FORCE_SECRET_ROTATION:-0}" != "1" ]; then
  echo "Secret already exists: $TARGET. Set WANWEI_FORCE_SECRET_ROTATION=1 to rotate it." >&2
  exit 1
fi
mkdir -p "$(dirname "$TARGET")"
umask 077
python3 -c 'import secrets,sys; open(sys.argv[1], "w", encoding="utf-8", newline="\n").write(secrets.token_urlsafe(48) + "\n")' "$TARGET"
chmod 600 "$TARGET"
echo "Secret created at $TARGET. The value was not printed."
