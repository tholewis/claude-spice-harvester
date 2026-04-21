#!/bin/bash
# ╔══════════════════════════════════════════════════════╗
# ║  Spice Meter — Build Script                         ║
# ║  Packages spice_meter.py into a standalone .app     ║
# ╚══════════════════════════════════════════════════════╝
set -e

echo ""
echo "🏜  SPICE METER — Build Script"
echo "────────────────────────────────"

# 1. Install dependencies
echo "► Installing Python dependencies..."
python3 -m pip install --user rumps pyinstaller

# 2. Create a spec-style build (single .app bundle)
echo "► Building SpiceMeter.app..."
python3 -m pyinstaller \
  --windowed \
  --onefile \
  --name "SpiceMeter" \
  --osx-bundle-identifier "com.yourname.spicemeter" \
  spice_meter.py

# 3. Move to current directory for easy access
if [ -d "dist/SpiceMeter.app" ]; then
  cp -r "dist/SpiceMeter.app" "./SpiceMeter.app"
  echo ""
  echo "✅  Done! SpiceMeter.app is ready."
  echo "    Drag it to your Applications folder, then double-click to run."
  echo ""
  echo "    First launch: macOS may warn it's from an unidentified developer."
  echo "    Fix: Right-click SpiceMeter.app → Open → Open (one time only)"
  echo ""
else
  echo "❌  Build failed — check PyInstaller output above."
  exit 1
fi
