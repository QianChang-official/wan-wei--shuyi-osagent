#!/bin/bash
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

# Usage: build-rpm.sh [allowlisted-payload.tar.gz]
# No argument: assemble this checkout, including its already-built Vue dist.
set -euo pipefail
[ "$#" -le 1 ] || { printf '%s\n' 'Usage: build-rpm.sh [payload.tar.gz]' >&2; exit 2; }
command -v rpmbuild >/dev/null || { printf '%s\n' 'Install the native system rpmbuild first; no foreign toolchain fallback.' >&2; exit 1; }
command -v python3 >/dev/null
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
TOP=$(mktemp -d "${TMPDIR:-/tmp}/wanwei-rpmbuild.XXXXXXXX")
trap 'printf "Build directory retained: %s\n" "$TOP"' EXIT
mkdir -p "$TOP"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
PAYLOAD="$TOP/SOURCES/wanwei-shuyi-1.0.0.tar.gz"
if [ "$#" = 1 ]; then
    cp -- "$1" "$PAYLOAD"
else
    python3 "$HERE/assemble_payload.py" --repo "$HERE/../.." --output "$PAYLOAD"
fi
python3 "$HERE/assemble_payload.py" --validate "$PAYLOAD"
cp -- "$HERE/wanwei-shuyi.spec" "$TOP/SPECS/wanwei-shuyi.spec"
rpmbuild -bb --define "_topdir $TOP" "$TOP/SPECS/wanwei-shuyi.spec"
printf 'RPM output (not published): %s/RPMS/noarch/\n' "$TOP"
