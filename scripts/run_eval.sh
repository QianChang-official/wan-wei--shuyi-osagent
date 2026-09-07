#!/usr/bin/env bash
# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

# Production MemoryArena-Lite runner — v0.6
set -e
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
echo "=== Running Production MemoryArena-Lite (v0.6) ==="
PYTHON="${WANWEI_PYTHON:-$PROJ/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
PYTHONPATH="$PROJ/backend" "$PYTHON" -m app.memory_arena.runner "$@"
