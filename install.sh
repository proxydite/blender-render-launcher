#!/usr/bin/env bash
#
# Installer for Blender Render Launcher.
# Copies the app into your user folders and registers it with the desktop.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "Installing Blender Render Launcher…"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

install -m 755 "$SCRIPT_DIR/blender-render-launcher.py" "$BIN_DIR/blender-render-launcher.py"
install -m 644 "$SCRIPT_DIR/blender-render-launcher.svg" "$ICON_DIR/blender-render-launcher.svg"

# Generate the .desktop file with the correct absolute path for this machine.
cat > "$APP_DIR/blender-render-launcher.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Blender Render Launcher
Comment=Drag a .blend file and render it in a terminal
Exec=python3 $BIN_DIR/blender-render-launcher.py %f
Icon=blender-render-launcher
Terminal=false
Categories=Graphics;Utility;
MimeType=application/x-blender;
StartupNotify=true
EOF

update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "Done!"
echo "Open your applications menu (Super key), search 'Blender Render Launcher',"
echo "then right-click it and choose 'Add to Favourites' to pin it to your dock."
