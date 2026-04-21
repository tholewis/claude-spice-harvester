#!/bin/bash
# ╔══════════════════════════════════════════════════════╗
# ║  Claude Spice Harvester — Build Script               ║
# ║  Packages claude_spice_harvester.py into a .app      ║
# ╚══════════════════════════════════════════════════════╝
set -e

echo ""
echo "🏜  CLAUDE SPICE HARVESTER — Build Script"
echo "────────────────────────────────"

# 1. Install dependencies
echo "► Installing Python dependencies..."
python3 -m pip install --user rumps pyinstaller

# 2. Create a spec-style build (single .app bundle)
echo "► Building ClaudeSpiceHarvester.app..."
python3 -m pyinstaller \
  --windowed \
  --onefile \
  --name "ClaudeSpiceHarvester" \
  --osx-bundle-identifier "com.yourname.claudespiceharvester" \
  claude_spice_harvester.py

# 3. Move to current directory for easy access
if [ -d "dist/ClaudeSpiceHarvester.app" ]; then
  cp -r "dist/ClaudeSpiceHarvester.app" "./ClaudeSpiceHarvester.app"
  echo ""
  echo "✅  Done! ClaudeSpiceHarvester.app is ready."
  echo "    Drag it to your Applications folder, then double-click to run."
  echo ""
  echo "    First launch: macOS may warn it's from an unidentified developer."
  echo "    Fix: Right-click ClaudeSpiceHarvester.app → Open → Open (one time only)"
  echo ""
else
  echo "❌  Build failed — check PyInstaller output above."
  exit 1
fi
