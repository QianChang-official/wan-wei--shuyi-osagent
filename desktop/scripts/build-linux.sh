#!/bin/sh
# staging 打包脚本:从 git HEAD 导出干净树,应用 release-clean.patch
# (剔除手机客户端部分——只影响打包树,GitHub 仓库保持完整),在该树上构建
# 前端与桌面安装包。
#
# 设计动机:仓库是研发/竞赛/审计的完整事实源,不因交付瘦身;RPM/DEB 是
# 面向最终用户的安装产物,只装该装的。两者的差异全部收敛在本脚本 +
# release-clean.patch,不进入版本历史。
#
# 用法: bash scripts/build-linux.sh [deb|rpm|all]
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-deb}"
STAGE="$ROOT/release-stage"

cd "$ROOT"

case "$TARGET" in
  deb|rpm|all) ;;
  *) echo "Usage: $0 {deb|rpm|all}"; exit 1 ;;
esac

# 0. 前置:已跟踪文件不得有未提交改动(staging 从 HEAD 导出,未提交改动
#    会静默丢失)。未跟踪文件(?? )不进 git archive,不拦截。
REPO="$(git rev-parse --show-toplevel)"
if git status --porcelain 2>/dev/null | grep -qv '^??'; then
  echo "ERROR: 已跟踪文件有未提交改动;staging 从 HEAD 导出,请先提交。" >&2
  git status --porcelain | grep -v '^??' | head -5 >&2
  exit 1
fi

# 1. 导出干净树 + 应用打包清理补丁
echo "[stage] exporting clean tree from HEAD ..."
rm -rf "$STAGE"
mkdir -p "$STAGE"
git -C "$REPO" archive --output="$STAGE/source.tar" HEAD
tar -xf "$STAGE/source.tar" -C "$STAGE"
rm "$STAGE/source.tar"

if [ -f "$STAGE/desktop/packaging/release-clean.patch" ]; then
  echo "[stage] applying release-clean.patch (mobile removal, package only) ..."
  git -C "$REPO" --work-tree="$STAGE" apply "$STAGE/desktop/packaging/release-clean.patch"
else
  echo "ERROR: packaging/release-clean.patch missing" >&2
  exit 1
fi

# 2. 在 staging 树构建前端(产物不含手机伴侣视图)
echo "[stage] building Vue console ..."
FE_DIR="$STAGE/frontend/console-vue"
( cd "$FE_DIR" && npm ci --silent )
( cd "$FE_DIR" && npm run build )

# 3. 在 staging 树打桌面包(extraResources 的 ../backend 与
#    ../frontend/console-vue/dist 均解析到 staging 内的已清理树)
echo "[stage] building desktop packages (target: $TARGET) ..."
DESK="$STAGE/desktop"
( cd "$DESK" && npm ci --silent )
case "$TARGET" in
  deb)  ( cd "$DESK" && npx --no-install electron-builder --linux deb ) ;;
  rpm)  ( cd "$DESK" && npx --no-install electron-builder --linux rpm ) ;;
  all)  ( cd "$DESK" && npx --no-install electron-builder --linux deb rpm ) ;;
esac

# 4. 产物回收到仓库 release/(staging 可整体删除)
mkdir -p "$ROOT/release"
case "$TARGET" in
  deb) cp "$DESK"/release/*.deb "$ROOT/release/" ;;
  rpm) cp "$DESK"/release/*.rpm "$ROOT/release/" ;;
  all) cp "$DESK"/release/*.rpm "$DESK"/release/*.deb "$ROOT/release/" ;;
esac
echo "Done. Artifacts: $ROOT/release/"
for f in "$ROOT/release/"*.rpm "$ROOT/release/"*.deb; do
  if [ -e "$f" ]; then
    ls -la "$f"
  fi
done

# 5. 保留 staging 供排查;重新打包时步骤 0 会整体重建
