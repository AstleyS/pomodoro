#!/usr/bin/env bash
# Installs Pomodoro for the current user: no sudo, shows up in your app menu.
# Prereqs (Debian/Ubuntu): sudo apt install python3-venv libxcb-cursor0
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/.local/share/pomodoro-app"

mkdir -p "$APP" "$HOME/.local/share/applications"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet -r "$HERE/requirements.txt"
cp "$HERE/pomodoro.py" "$APP/pomodoro.py"
mkdir -p "$APP/pomodoro_app"
cp "$HERE"/pomodoro_app/*.py "$APP/pomodoro_app/"

cat > "$APP/icon.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="34" r="24" fill="#e5484d"/><path d="M32 10c-2 4-6 6-10 6 4 0 8 2 10 6 2-4 6-6 10-6-4 0-8-2-10-6z" fill="#30a46c"/></svg>
EOF

cat > "$HOME/.local/share/applications/pomodoro.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Pomodoro
Comment=Pomodoro timer with tray icon and session log
Exec=$APP/venv/bin/python $APP/pomodoro.py
Icon=$APP/icon.svg
Terminal=false
Categories=Utility;
EOF

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Done. Search for 'Pomodoro' in your app menu."
