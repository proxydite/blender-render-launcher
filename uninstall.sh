#!/usr/bin/env bash
#
# Uninstaller for Blender Render Launcher.
#
set -euo pipefail

echo "Removing Blender Render Launcher…"

rm -f "$HOME/.local/bin/blender-render-launcher.py"
rm -f "$HOME/.local/share/applications/blender-render-launcher.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/blender-render-launcher.svg"
rm -rf "$HOME/.config/blender-render-launcher"

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Done. You may want to unpin it from your dock if it's still there."
