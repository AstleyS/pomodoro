"""Main timer window and Pomodoro session workflow."""
import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pomodoro_app.media import MprisServer
from pomodoro_app.session_log import append_log, hm, log_path, read_log
from pomodoro_app.tray import COLORS, Ring, make_icon

STYLE = """
QWidget{background:#1c1c1f;color:#ededed;font-size:13px}
QPushButton{background:#2a2a2e;border:0;padding:6px 10px;border-radius:5px}
QPushButton:hover{background:#3a3a40}
QComboBox,QSpinBox,QTableWidget{background:#2a2a2e;border:1px solid #3a3a40;border-radius:4px;padding:3px}
"""


class Pomodoro(QMainWindow):
    """Own timer state, session scheduling, and the primary application window."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(110, 110)
        self.resize(320, 470)
        self.durations = {"Focus": 25, "Short break": 5, "Long break": 15}
        self.mode, self.remaining = "Focus", 25 * 60
        self.running, self.end, self.done = False, 0.0, 0
        self.phase_started = False
        self.completed, self.logged_current = False, False
        self.idx, self.plan = 0, []
        self.compact, self.full_size, self._quitting = False, self.size(), False

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        def row():
            widget = QWidget()
            horizontal = QHBoxLayout(widget)
            horizontal.setContentsMargins(0, 0, 0, 0)
            return widget, horizontal

        self.tabs = QLabel()
        self.tabs.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.tabs)

        self.ring = Ring(self)
        layout.addWidget(self.ring, 1)

        self.controls, controls_layout = row()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle)
        controls_layout.addWidget(self.start_btn)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        controls_layout.addWidget(self.reset_btn)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self.skip)
        controls_layout.addWidget(self.skip_btn)
        layout.addWidget(self.controls)

        self.logrow, log_layout = row()
        self.label = QComboBox()
        self.label.setEditable(True)
        self.label.setInsertPolicy(QComboBox.NoInsert)
        self.label.addItems(sorted({entry[1] for entry in read_log()}))
        self.label.setCurrentIndex(-1)
        self.label.lineEdit().setPlaceholderText("Activity, e.g. French learning")
        self.log_on = QCheckBox("Log")
        self.log_on.setChecked(True)
        history_button = QPushButton("History")
        history_button.clicked.connect(self.show_log)
        log_layout.addWidget(self.label, 1)
        log_layout.addWidget(self.log_on)
        log_layout.addWidget(history_button)
        layout.addWidget(self.logrow)

        self.setrow, settings_layout = row()
        self.spins = {}
        for mode in COLORS:
            spin = QSpinBox()
            spin.setRange(0 if mode != "Focus" else 1, 180)
            spin.setValue(self.durations[mode])
            spin.valueChanged.connect(self.apply_settings)
            settings_layout.addWidget(QLabel(mode.split()[0]))
            settings_layout.addWidget(spin)
            self.spins[mode] = spin
        layout.addWidget(self.setrow)

        self.planrow, plan_layout = row()
        self.sess = QSpinBox()
        self.sess.setRange(1, 12)
        self.sess.setValue(4)
        self.sess.valueChanged.connect(self.apply_plan)
        plan_layout.addWidget(QLabel("Sessions"))
        plan_layout.addWidget(self.sess)
        self.auto = QCheckBox("Auto-start next")
        self.auto.setChecked(True)
        plan_layout.addWidget(self.auto)
        layout.addWidget(self.planrow)
        self.extras = [self.tabs, self.controls, self.logrow, self.setrow, self.planrow]

        self.plan = self.build_plan()
        self.tray = None
        self.tray_value = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_icon(COLORS[self.mode], self.remaining), self)
            self.menu = QMenu()
            self.menu.addAction("Show / hide", self.toggle_visible)
            self.menu.addAction("Start / pause", self.toggle)
            self.menu.addAction("Reset", self.reset)
            self.menu.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(
                lambda reason: self.toggle_visible()
                if reason == QSystemTrayIcon.Trigger else None
            )
            self.tray.show()

        self.mpris = MprisServer(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.refresh()

    def total(self):
        """Return the current phase duration in seconds."""
        return self.durations[self.mode] * 60

    def build_plan(self):
        """Build the focus and configured break phases for the current plan."""
        count = self.sess.value()
        plan = []
        for index in range(count):
            plan.append("Focus")
            if index < count - 1 and self.durations["Short break"] > 0:
                plan.append("Short break")
            elif index == count - 1 and count >= 4 and self.durations["Long break"] > 0:
                plan.append("Long break")
        return plan

    def apply_plan(self):
        """Rebuild the plan after a session-count change."""
        self.plan = self.build_plan()
        if self.completed:
            self.completed = False
            self.done = 0
            self.go(0)
            return
        self.idx = min(self.idx, len(self.plan) - 1)
        if not self.running and self.plan[self.idx] != self.mode:
            self.go(self.idx)
        self.refresh()

    def log_elapsed(self):
        """Log at most one row for the elapsed portion of the current focus."""
        elapsed = self.total() - self.remaining
        if (
            not self.logged_current
            and self.mode == "Focus"
            and elapsed >= 60
            and self.log_on.isChecked()
        ):
            label = self.label.currentText().strip() or "Unlabelled"
            append_log(label, elapsed / 60)
            self.logged_current = True
            if self.label.findText(label) < 0:
                self.label.addItem(label)

    def go(self, index):
        """Move to a plan phase, logging any focus time spent so far."""
        self.log_elapsed()
        self.running = False
        self.idx = index
        self.mode = self.plan[index]
        self.remaining = self.total()
        self.phase_started = False
        self.completed = False
        self.logged_current = False
        if self.tray:
            self.tray_value = None
        self.refresh()

    def advance(self, completed):
        """Advance phases or hold on the final completed state."""
        if self.completed:
            return
        next_index = self.idx + 1
        wrapped = next_index >= len(self.plan)
        if completed:
            if self.tray:
                message = (
                    "All sessions complete. Nice work!" if wrapped
                    else f"{self.mode} finished. Next: {self.plan[next_index]}"
                )
                self.tray.showMessage(
                    "Pomodoro", message, QSystemTrayIcon.Information, 8000
                )
            self.completion_ping()
        if wrapped:
            self.log_elapsed()
            self.running = False
            self.completed = True
            self.remaining = 0
            self.refresh()
            return
        self.go(next_index)
        if completed and self.auto.isChecked():
            self.toggle()

    def apply_settings(self):
        """Apply duration changes and skip a break changed to zero."""
        untouched = self.remaining == self.total() and not self.running
        skip_current_break = (
            self.mode in ("Short break", "Long break")
            and self.spins[self.mode].value() == 0
        )
        was_running = self.running
        for mode, spin in self.spins.items():
            self.durations[mode] = spin.value()
        if untouched:
            self.remaining = self.total()
        self.apply_plan()
        if skip_current_break and was_running:
            self.go(self.idx)
            self.toggle()

    def toggle(self):
        """Start or pause the current phase, or launch a new completed plan."""
        if self.completed:
            self.start_new_plan()
            return
        if not self.running:
            self.end = time.monotonic() + self.remaining
            if not self.phase_started:
                QApplication.beep()
                self.phase_started = True
        self.running = not self.running
        self.refresh()

    def completion_ping(self):
        """Play the double-ping completion cue."""
        QApplication.beep()
        QTimer.singleShot(180, QApplication.beep)

    def reset(self):
        """Restart the current phase."""
        if self.completed:
            return
        self.go(self.idx)

    def skip(self):
        """Skip to the next phase unless the plan is complete."""
        if self.completed:
            return
        self.advance(completed=False)

    def start_new_plan(self):
        """Reset progress and start a new plan from its first focus phase."""
        self.completed = False
        self.done = 0
        self.go(0)
        self.toggle()

    def tick(self):
        """Update the countdown and advance when a phase reaches zero."""
        if not self.running:
            return
        self.remaining = max(0, math.ceil(self.end - time.monotonic()))
        if self.remaining == 0:
            if self.mode == "Focus":
                self.done += 1
            self.advance(completed=True)
            return
        self.refresh()

    def refresh(self):
        """Synchronize the window, tray, ring, and media metadata with state."""
        minutes, seconds = divmod(self.remaining, 60)
        title = f"{minutes:02d}:{seconds:02d} · {self.mode}"
        self.setWindowTitle(title)
        if self.tray:
            self.tray.setToolTip(title)
            shown = math.ceil(self.remaining / 60) if self.remaining >= 60 else self.remaining
            tray_value = (self.mode, shown)
            if tray_value != self.tray_value:
                self.tray.setIcon(make_icon(COLORS[self.mode], self.remaining))
                self.tray_value = tray_value
        count = self.sess.value()
        dots = "●" * min(self.done, count) + "○" * max(0, count - self.done)
        if self.completed:
            self.tabs.setText(f"{dots}   Session {count} out of {count}. Complete")
            self.tabs.setStyleSheet(
                "color: #8ce5a6; background: #163526; font-weight: bold; padding: 4px;"
            )
        else:
            session = self.plan[:self.idx].count("Focus") + int(self.mode == "Focus")
            self.tabs.setText(f"{dots}   Session {min(session, count)} out of {count}")
            self.tabs.setStyleSheet("")
        self.start_btn.setText(
            "New plan" if self.completed else ("Pause" if self.running else "Start")
        )
        self.reset_btn.setEnabled(not self.completed)
        self.skip_btn.setEnabled(not self.completed)
        self.ring.update()
        self.mpris.update()

    def show_from_media(self):
        """Raise and activate the window after a tray, MPRIS, or IPC request."""
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_compact(self):
        """Toggle the compact layout while remembering the full window size."""
        self.compact = not self.compact
        if self.compact:
            self.full_size = self.size()
            for widget in self.extras:
                widget.hide()
            self.resize(170, 170)
        else:
            for widget in self.extras:
                widget.show()
            self.resize(self.full_size)

    def resizeEvent(self, event):
        """Switch layouts when the user resizes across the compact threshold."""
        if hasattr(self, "extras"):
            small = self.width() < 250 or self.height() < 360
            if small and not self.compact:
                self.full_size = event.oldSize()
                self.compact = True
                for widget in self.extras:
                    widget.hide()
            elif not small and self.compact:
                self.compact = False
                self.full_size = self.size()
                for widget in self.extras:
                    widget.show()
        super().resizeEvent(event)

    def toggle_visible(self):
        """Hide to the tray or restore the existing window."""
        if self.isVisible():
            self.hide()
        else:
            self.show_from_media()

    def show_log(self):
        """Display aggregate activity totals and the session history table."""
        rows = read_log()
        totals = {}
        for _, label, minutes in rows:
            totals[label] = totals.get(label, 0) + float(minutes)
        dialog = QDialog(self)
        dialog.setWindowTitle("Session history")
        dialog.resize(520, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "\n".join(f"{label}: {hm(total)}" for label, total in sorted(totals.items()))
            or "No sessions yet."
        ))
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["When", "Activity", "Minutes"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for row_index, row in enumerate(reversed(rows)):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        layout.addWidget(table)
        layout.addWidget(QLabel(f"File: {log_path()}"))
        dialog.exec()

    def quit_app(self):
        """Log remaining focus time and exit the application."""
        self.log_elapsed()
        self._quitting = True
        self.mpris.close()
        QApplication.quit()

    def closeEvent(self, event):
        """Hide to the tray unless the user explicitly chose Quit."""
        if self.tray and not self._quitting:
            event.ignore()
            self.hide()
        else:
            self.quit_app()
            event.accept()
