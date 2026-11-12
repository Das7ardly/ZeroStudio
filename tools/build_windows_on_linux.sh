#!/usr/bin/env bash
# Build ZeroStudio for Windows on Linux (Ubuntu 24.04): frozen app + NSIS installer + portable exe.
#   tools/build_windows_on_linux.sh            (uses ./.winbuild as work dir)
# Inputs it downloads if missing (GitHub must be reachable, or drop the files into .winbuild/dl/ first):
#   python-build-standalone cpython-3.12 x86_64-pc-windows-msvc install_only tarball  -> dl/python.tar.gz
# zerostudio/vendor/7za.exe (7-Zip x64 console, from 7z*-extra.7z) is part of the source tree.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$ROOT/.winbuild}"
PY_URL="${PY_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.12.15%2B20261009-x86_64-pc-windows-msvc-install_only.tar.gz}"
VERSION="$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$ROOT/zerostudio/__init__.py').read()).group(1))")"
export WINEPREFIX="$WORK/prefix" WINEDEBUG=-all
WINE=/usr/lib/wine/wine64
mkdir -p "$WORK/dl"

echo "== 1. packages"
if ! command -v makensis >/dev/null || [ ! -x "$WINE" ] || ! command -v x86_64-w64-mingw32-gcc >/dev/null; then
  sudo apt-get install -y --no-install-recommends wine64 nsis gcc-mingw-w64-x86-64 xvfb
fi

echo "== 2. Windows Python"
[ -f "$WORK/dl/python.tar.gz" ] || curl -fL -o "$WORK/dl/python.tar.gz" "$PY_URL"
[ -x "$WORK/python/python.exe" ] || (cd "$WORK" && tar xzf dl/python.tar.gz && chmod +x python/python.exe)
[ -d "$WINEPREFIX/drive_c/windows/system32" ] || "$WINE" wineboot -i 2>&1 | cat

echo "== 3. ICU stub (Qt 6.7+ links Windows' icuuc.dll which Wine lacks; build-time only, never shipped)"
SYMS="UCNV_FROM_U_CALLBACK_SUBSTITUTE UCNV_TO_U_CALLBACK_SUBSTITUTE ucnv_cbFromUWriteUChars ucnv_cbToUWriteUChars ucnv_close ucnv_countAvailable ucnv_fromUCountPending ucnv_fromUnicode ucnv_getAvailableName ucnv_getFromUCallBack ucnv_getMaxCharSize ucnv_getName ucnv_getStandardName ucnv_getToUCallBack ucnv_open ucnv_reset ucnv_setFromUCallBack ucnv_setToUCallBack ucnv_toUCountPending ucnv_toUnicode"
mkdir -p "$WORK/stubs"
: > "$WORK/stubs/icuuc.c"
for s in $SYMS; do echo "__declspec(dllexport) long long $s(void){return 0;}" >> "$WORK/stubs/icuuc.c"; done
x86_64-w64-mingw32-gcc -shared -O2 -o "$WORK/stubs/icuuc.dll" "$WORK/stubs/icuuc.c"
cp "$WORK/stubs/icuuc.dll" "$WINEPREFIX/drive_c/windows/system32/"

echo "== 4. wheels"
pip download -q --dest "$WORK/wheels" --platform win_amd64 --python-version 3.12 --implementation cp \
  --only-binary=:all: PySide6-Essentials pyinstaller pefile pywin32-ctypes altgraph pyinstaller-hooks-contrib \
  packaging setuptools
"$WINE" "$WORK/python/python.exe" -m pip install -q --no-index --find-links "$WORK/wheels" \
  pyside6-essentials pyinstaller pefile pywin32-ctypes 2>&1 | cat
"$WINE" "$WORK/python/python.exe" -c "from PySide6 import QtWidgets; print('PySide6 OK')" 2>&1 | cat

echo "== 5. PyInstaller"
cd "$ROOT"
rm -rf build dist
"$WINE" "$WORK/python/python.exe" -m PyInstaller packaging/zerostudio.spec --noconfirm 2>&1 | cat > "$WORK/pyinstaller.log"
tail -1 "$WORK/pyinstaller.log"
test -f dist/ZeroStudio/_internal/PySide6/plugins/platforms/qwindows.dll
if find dist -iname 'icu*.dll' | grep -q .; then echo "ICU stub leaked into dist"; exit 1; fi

echo "== 6. smoke test (offscreen self-test screenshots)"
rm -rf "$WORK/shots" && mkdir -p "$WORK/shots"
ZEROSTUDIO_DATA_DIR="Z:${WORK//\//\\}\\testdata" ZEROSTUDIO_SELFTEST="Z:${WORK//\//\\}\\shots" \
  QT_QPA_PLATFORM=offscreen timeout 120 "$WINE" dist/ZeroStudio/ZeroStudio.exe 2>&1 | cat > /dev/null || true
n=$(ls "$WORK/shots" | wc -l); echo "screenshots: $n"; [ "$n" -ge 5 ]

echo "== 7. installer + portable"
mkdir -p release
(cd packaging && makensis -V2 -DVERSION="$VERSION" installer.nsi && makensis -V2 -DVERSION="$VERSION" portable.nsi)
ls -la release
