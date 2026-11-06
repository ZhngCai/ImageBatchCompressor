#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或更高版本")
PY

if "$PYTHON" -m pip --version >/dev/null 2>&1; then
  "$PYTHON" -m pip install -e . pyinstaller
elif command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYTHON" -e . pyinstaller
else
  "$PYTHON" -m ensurepip --upgrade
  "$PYTHON" -m pip install -e . pyinstaller
fi

"$PYTHON" -m PyInstaller --clean --noconfirm packaging/image-compress.spec

echo "构建完成：dist/image-compress/image-compress"
echo "运行：dist/image-compress/image-compress --help"
