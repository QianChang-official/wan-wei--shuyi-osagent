#!/bin/sh
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

# Explicit administrator action only. pip/venv run as the service user, never root.
set -eu
fail() { printf 'wanwei-shuyi: %s\n' "$*" >&2; exit 1; }
MODE= INDEX= WHEELHOUSE=
for arg in "$@"; do
    case "$arg" in
        --online) [ -z "$MODE" ] || fail 'Choose exactly one installation mode'; MODE=online ;;
        --wheelhouse=*) [ -z "$MODE" ] || fail 'Choose exactly one installation mode'; MODE=offline; WHEELHOUSE=${arg#*=} ;;
        --index-url=*) [ -z "$INDEX" ] || fail 'Only one index is allowed'; INDEX=${arg#*=}; [ -n "$INDEX" ] || fail 'Empty index' ;;
        *) fail 'Usage: install-deps.sh --online [--index-url=https://approved.example/simple] OR --wheelhouse=/absolute/path' ;;
    esac
done
[ -n "$MODE" ] || fail 'Choose --online or --wheelhouse=/absolute/path explicitly'
if [ "$MODE" = offline ]; then
    [ -z "$INDEX" ] || fail '--index-url requires --online'
    case "$WHEELHOUSE" in /*) ;; *) fail 'Wheelhouse must be an absolute path' ;; esac
    [ -d "$WHEELHOUSE" ] || fail 'Wheelhouse does not exist'
else
    INDEX=${INDEX:-https://pypi.org/simple}
fi
[ "$(id -u)" = 0 ] || fail 'An administrator must run this script after installing the RPM'
APP=/opt/apps/wanwei-shuyi
VENV=$APP/venv
REQS=$APP/backend/requirements.txt
STATE=/var/lib/wanwei-shuyi
command -v runuser >/dev/null 2>&1 || fail 'Install the system runuser utility first'
# No inherited pip config, extra indexes, user site, proxy, or PYTHONPATH.
as_service() {
    runuser -u wanwei-shuyi -- env -i HOME="$STATE" PATH=/usr/bin:/bin \
        PIP_CONFIG_FILE=/dev/null PYTHONNOUSERSITE=1 "$@"
}
as_service python3 - "$REQS" "$INDEX" <<'PY'
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
if sys.version_info < (3, 10):
    sys.exit('Python >= 3.10 is required; install it from your OS vendor')
import venv, ensurepip  # No network bootstrap if the OS lacks these modules.
if sys.argv[2]:
    url = urlsplit(sys.argv[2])
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(c.isspace() for c in sys.argv[2])):
        sys.exit('The approved index must be one credential-free HTTPS URL')
# Direct URLs, nested requirements and pip options could bypass offline/index policy.
for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and not re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+', line):
        sys.exit('requirements.txt must contain only exact package pins')
PY
umask 077
[ ! -L "$VENV" ] || fail 'Refusing a symlink venv'
if [ ! -e "$VENV" ]; then
    install -d -m 0700 -o wanwei-shuyi -g wanwei-shuyi "$VENV"
    as_service python3 -m venv "$VENV"
fi
[ -x "$VENV/bin/python" ] || fail 'Incomplete venv retained; inspect/repair it explicitly'
as_service "$VENV/bin/python" -c 'import sys; assert sys.version_info >= (3, 10), "Python >= 3.10 required"'
as_service "$VENV/bin/python" -m pip --version
if [ "$MODE" = offline ]; then
    set -- --no-index "--find-links=$WHEELHOUSE"
else
    set -- "--index-url=$INDEX"
fi
as_service "$VENV/bin/python" -m pip install --disable-pip-version-check \
    --no-input --no-cache-dir --only-binary=:all: "$@" -r "$REQS"
as_service "$VENV/bin/python" -m pip check
printf '%s\n' 'Dependencies installed. Service was NOT started; enable/start it explicitly after reviewing configuration.'
