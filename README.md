# Pomodoro

A small Linux desktop Pomodoro timer built with Python and Qt. It supports configurable focus and break phases, optional breaks, session logging, a system tray countdown, and MPRIS controls for desktop media panels.

## Features

- Configure focus, short-break, long-break, and session durations. Set either break duration to zero to omit it.
- Automatically start the next phase by default; pause or skip phases manually.
- See completion highlighted at the end of a plan, then start a new plan explicitly.
- Resize the window to switch between full and compact layouts. Double-click the timer ring to toggle compact mode.
- Use the tray countdown and GNOME-compatible MPRIS play/pause, next, previous, and raise-window controls.
- Optionally log focus time by activity to a local CSV file.

## Project Layout

- `pomodoro.py` is the source and installed-app launcher.
- `pomodoro_app/window.py` owns the main window and timer/session workflow.
- `pomodoro_app/tray.py` draws the countdown ring and tray icon.
- `pomodoro_app/media.py` exposes timer controls and metadata through MPRIS.
- `pomodoro_app/instance.py` forwards repeated launches to the existing window.
- `pomodoro_app/session_log.py` reads and writes the local CSV history.
- `pomodoro_app/main.py` configures and starts the Qt application.

## Requirements

- Linux desktop with a graphical session and D-Bus session bus
- Python 3.10 or later
- Debian/Ubuntu system packages: `python3-venv` and `libxcb-cursor0`

The tray icon and media-panel integration depend on desktop-environment support. Docker is not the recommended way to run this GUI app because it needs access to the host display, audio, tray, and session bus.

## Install

From a clone of this repository on Debian or Ubuntu:

```sh
sudo apt install python3-venv libxcb-cursor0
bash install.sh
```

The installer creates a virtual environment under `~/.local/share/pomodoro-app` and adds Pomodoro to the current user's application menu.

## Run from source

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pomodoro.py
```

## Controls

- **Start / Pause** starts or pauses the current phase. Starting the next phase automatically is enabled by default.
- **Reset** restarts the current phase; **Skip** advances to the next phase.
- Drag a window edge to resize. Double-click the timer ring to toggle compact mode.
- Click the tray icon to show or hide the window; right-click it for timer actions.

## Data

Session history is stored in `log.csv` under the platform's application-data directory, as selected by Qt's `QStandardPaths.AppDataLocation`.

## License

No license has been selected yet. Until a license is added, others should not assume they have permission to redistribute or modify this project.
