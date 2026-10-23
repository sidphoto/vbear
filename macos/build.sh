#!/bin/bash
# Builds dist/VBear.app and dist/VBear-<version>-arm64.dmg (Apple Silicon).
#
# The app bundles a standalone CPython (python-build-standalone), pinned by
# version and SHA-256, so users need no Python of their own. The result is
# ad-hoc signed only (no Apple Developer ID): macOS asks the user to allow it
# once, see the README.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
DIST="$ROOT/dist"
CACHE="$BUILD/cache"

PY_VERSION="3.13.16"
PY_RELEASE="20261003"
PY_ARCHIVE="cpython-${PY_VERSION}+${PY_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_SHA256="9e01f63bbb08576cd9c8bc2d0564d098cb30c8453a0cd4bcf6aef458f6d2a147"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${PY_ARCHIVE/+/%2B}"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/vbear/__init__.py")"
[ -n "$VERSION" ] || { echo "version not found in vbear/__init__.py" >&2; exit 1; }
[ "$(uname -m)" = "arm64" ] || { echo "build on Apple Silicon (arm64)" >&2; exit 1; }

APP="$BUILD/VBear.app"
RES="$APP/Contents/Resources"
echo "==> VBear $VERSION"

# 1. Python runtime, verified before use.
mkdir -p "$CACHE"
if [ ! -f "$CACHE/$PY_ARCHIVE" ]; then
  echo "==> downloading $PY_ARCHIVE"
  curl -fsSL --retry 3 -o "$CACHE/$PY_ARCHIVE.part" "$PY_URL"
  mv "$CACHE/$PY_ARCHIVE.part" "$CACHE/$PY_ARCHIVE"
fi
echo "$PY_SHA256  $CACHE/$PY_ARCHIVE" | shasum -a 256 -c - >/dev/null \
  || { echo "SHA-256 mismatch for $PY_ARCHIVE" >&2; rm -f "$CACHE/$PY_ARCHIVE"; exit 1; }

# 2. Bundle layout.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES/app"
tar -xzf "$CACHE/$PY_ARCHIVE" -C "$RES"          # -> Resources/python
PYLIB="$RES/python/lib/python3.13"
# Not needed by VBear: tests, GUI toolkits, IDLE, pip bootstrap, headers.
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/tkinter" "$PYLIB/turtledemo" "$PYLIB/ensurepip" \
       "$PYLIB"/lib-dynload/_tkinter* "$RES/python/include" "$RES/python/share" \
       "$RES/python/lib"/libtcl* "$RES/python/lib"/libtk* "$RES/python/lib"/tcl* "$RES/python/lib"/tk* \
       "$PYLIB"/site-packages/pip* "$RES/python/bin/pip"* "$RES/python/bin/idle"* "$RES/python/bin/pydoc"* \
       "$RES/python/lib"/itcl* "$RES/python/lib"/thread* "$RES/python/lib"/tdbc* "$RES/python/lib/pkgconfig"
find "$RES/python" -name "__pycache__" -type d -prune -exec rm -rf {} +

rsync -a --exclude "__pycache__" "$ROOT/vbear" "$ROOT/web" "$RES/app/"
cp "$ROOT/LICENSE" "$RES/app/LICENSE"
# Byte-compile once now: the signed bundle must not be written to at run time.
# unchecked-hash .pyc files stay valid whatever the files' timestamps become
# after copying, so Python never needs to rewrite them.
# -s/-p record bundle-relative source paths, not the build machine's.
"$RES/python/bin/python3" -B -m compileall -q --invalidation-mode unchecked-hash \
  -s "$APP" -p "/Applications/VBear.app" "$RES/app/vbear" "$PYLIB" >/dev/null
if grep -rlF "$ROOT" "$APP" >/dev/null 2>&1; then
  echo "build path leaked into the bundle:" >&2; grep -rlF "$ROOT" "$APP" | head >&2; exit 1
fi

# 3. Swift shell, icons, Info.plist.
swiftc -O -target arm64-apple-macos13.0 -framework Cocoa -framework WebKit \
  -o "$APP/Contents/MacOS/VBear" "$ROOT/macos/VBear/main.swift"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET"
swift "$ROOT/macos/make_icon.swift" "$ICONSET" "$ROOT/macos/AppIcon.pixels.json"
iconutil -c icns -o "$RES/AppIcon.icns" "$ICONSET"
cp "$RES/AppIcon.icns" "$BUILD/AppIcon.icns"     # the reference for the check below
# macOS 26 and later pick the icon for the light or dark appearance from Assets.car, which actool compiles from an
# Icon Composer .icon (macos/AppIcon.icon: the plate colours and one bear layer per appearance; the system draws the
# plate, its edge and the finish). The layers are made here from the two pixel files, so no pictures are kept in the
# repository. Older systems keep reading AppIcon.icns (CFBundleIconFile), the light one made above.
# Only Assets.car is taken from actool's output: it writes an AppIcon.icns of its own, which must not replace ours.
if xcrun --find actool >/dev/null 2>&1; then
  ICONDOC="$BUILD/AppIcon.icon"
  ACTOOL_OUT="$BUILD/actool"
  rm -rf "$ICONDOC" "$ACTOOL_OUT"
  mkdir -p "$ICONDOC/Assets" "$ACTOOL_OUT"
  cp "$ROOT/macos/AppIcon.icon/icon.json" "$ICONDOC/icon.json"
  swift "$ROOT/macos/make_icon.swift" "$ICONSET" "$ROOT/macos/AppIcon.pixels.json" --layer "$ICONDOC/Assets/light.png"
  swift "$ROOT/macos/make_icon.swift" "$ICONSET" "$ROOT/macos/AppIcon-dark.pixels.json" --layer "$ICONDOC/Assets/dark.png"
  xcrun actool "$ICONDOC" --compile "$ACTOOL_OUT" --platform macosx --minimum-deployment-target 13.0 \
    --app-icon AppIcon --output-partial-info-plist "$ACTOOL_OUT/partial.plist" >"$ACTOOL_OUT/actool.log"
  [ -f "$ACTOOL_OUT/Assets.car" ] || { echo "actool did not produce Assets.car (see $ACTOOL_OUT/actool.log)" >&2; exit 1; }
  cp "$ACTOOL_OUT/Assets.car" "$RES/Assets.car"
  cmp -s "$RES/AppIcon.icns" "$BUILD/AppIcon.icns" || { echo "AppIcon.icns is not the one iconutil made" >&2; exit 1; }
else
  echo "==> actool not found (Xcode is not installed): no Assets.car, so no dark Dock icon; AppIcon.icns is made as usual"
fi
sed "s/@VERSION@/$VERSION/g" "$ROOT/macos/Info.plist.in" > "$APP/Contents/Info.plist"

# 4. Ad-hoc signature (required to run on Apple Silicon), then verify.
codesign --force --deep --sign - --timestamp=none "$APP"
codesign --verify --deep --strict "$APP"

# 5. Disk image with an Applications shortcut.
mkdir -p "$DIST"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" "$DIST/VBear.app"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/VBear.app"
ln -s /Applications "$STAGE/Applications"
DMG="$DIST/VBear-$VERSION-arm64.dmg"
rm -f "$DMG"
hdiutil create -quiet -volname "VBear $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
ditto "$APP" "$DIST/VBear.app"
shasum -a 256 "$DMG" | tee "$DMG.sha256"
du -sh "$APP" "$DMG"
