#!/bin/sh
# Build a standalone mocktcl executable into dist/ (used by CI; also works locally).
# Usage: [PYTHON=.venv/bin/python] packaging/build.sh [OUTPUT_NAME]
set -eu
cd "$(dirname "$0")/.."
name="${1:-mocktcl}"
"${PYTHON:-python}" -m PyInstaller --onefile --clean --noconfirm \
    --name "$name" \
    --collect-data mocktcl \
    --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller \
    --log-level WARN \
    packaging/entry.py
echo "built dist/$name"
