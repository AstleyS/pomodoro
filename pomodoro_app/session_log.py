"""Read and write the user's local focus-session history."""
import csv
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def log_path():
    """Return the platform-specific path used for the session CSV."""
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "log.csv"


def read_log():
    """Return valid session rows from the local CSV file."""
    path = log_path()
    if not path.exists():
        return []
    with path.open(newline="") as file:
        return [row for row in csv.reader(file) if len(row) == 3]


def append_log(label, minutes):
    """Append one labeled focus-duration row to the local CSV file."""
    with log_path().open("a", newline="") as file:
        csv.writer(file).writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"), label, f"{minutes:.1f}"
        ])


def hm(minutes):
    """Format a minute total as hours and minutes."""
    return f"{int(minutes // 60)}h {int(minutes % 60):02d}m"
