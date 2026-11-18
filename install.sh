#!/usr/bin/env bash
# Installs the AULA H510 app for the current user and the udev rule that lets
# the logged-in user talk to the mouse (the rule step asks for sudo).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f /etc/udev/rules.d/70-aula-h510.rules ]; then
  echo "Installing udev rule (needs sudo)..."
  sudo install -m 644 "$DIR/70-aula-h510.rules" /etc/udev/rules.d/70-aula-h510.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw
fi

mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
cp "$DIR/assets/aula-h510.png" ~/.local/share/icons/hicolor/256x256/apps/aula-h510.png
cat > ~/.local/share/applications/aula-h510.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=AULA H510
GenericName=Gaming mouse settings
Comment=Configure DPI, buttons, macros and lighting of the AULA H510 mouse
Exec=python3 "$DIR/aula_h510_app.py"
Icon=aula-h510
Categories=Settings;HardwareSettings;Qt;
Keywords=mouse;dpi;aula;h510;macro;
DESKTOP
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
echo "Done. Open \"AULA H510\" from the application menu."
