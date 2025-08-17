#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SPX-0DTE-Backtester"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
# If you have requirements.txt, prefer: pip install -r requirements.txt
pip install pyinstaller PyQt6 pandas numpy

pyinstaller --noconfirm --clean --windowed --name "$APP_NAME" --collect-all PyQt6 --collect-all pandas main.py

echo "App at dist/$APP_NAME/$APP_NAME.app"

# Optional: create a DMG (requires 'create-dmg' or hdiutil)
# hdiutil create -volname "$APP_NAME" -srcfolder "dist/$APP_NAME" -ov -format UDZO "$APP_NAME.dmg"

# Codesign (optional, replace with your Developer ID)
# codesign --deep --force --options runtime --sign "Developer ID Application: YOUR NAME (TEAMID)" "dist/$APP_NAME/$APP_NAME.app"
