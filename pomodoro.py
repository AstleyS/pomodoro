#!/usr/bin/env python3
"""Pomodoro timer with tray countdown, automatic next-step start, and CSV session log."""
import csv
import math
import shutil
import struct
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QStandardPaths, Qt, QTimer, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QPushButton, QSpinBox, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

SERVER = "pomodoro-timer-instance"
COLORS = {"Focus": "#e5484d", "Short break": "#30a46c", "Long break": "#3e63dd"}
STYLE = """
QWidget{background:#1c1c1f;color:#ededed;font-size:13px}
QPushButton{background:#2a2a2e;border:0;padding:6px 10px;border-radius:5px}
QPushButton:hover{background:#3a3a40}
QComboBox,QSpinBox,QTableWidget{background:#2a2a2e;border:1px solid #3a3a40;border-radius:4px;padding:3px}
"""


# ---------- session log (CSV: when, activity, minutes) ----------
def log_path():
    d = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    d.mkdir(parents=True, exist_ok=True)
    return d / "log.csv"


def read_log():
    p = log_path()
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return [r for r in csv.reader(f) if len(r) == 3]


def append_log(label, minutes):
    with log_path().open("a", newline="") as f:
        csv.writer(f).writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), label, f"{minutes:.1f}"])


def hm(minutes):
    return f"{int(minutes // 60)}h {int(minutes % 60):02d}m"


def make_icon(color, remaining=0):
    """Create a tray icon showing the remaining whole minutes."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)

    minutes = max(0, math.ceil(remaining / 60))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(25 if minutes < 100 else 19)
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(pm.rect(), Qt.AlignCenter, str(minutes))
    p.end()
    return QIcon(pm)


def chime_path():
    p = log_path().parent / "chime.wav"
    if not p.exists():
        rate, frames = 22050, bytearray()
        for freq in (660, 880, 1100):
            n = int(rate * 0.35)
            for i in range(n):
                v = int(14000 * math.exp(-4.0 * i / n) * math.sin(2 * math.pi * freq * i / rate))
                frames += struct.pack("<h", v)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
    return str(p)


def play_chime():
    wav = chime_path()
    for cmd in ("paplay", "pw-play", "aplay", "play"):
        exe = shutil.which(cmd)
        if exe:
            args = [exe, "-q", wav] if cmd in ("aplay", "play") else [exe, wav]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    QApplication.beep()


class Ring(QWidget):
    """Scales with the window."""

    def __init__(self, owner):
        super().__init__()
        self.o = owner
        self.setMinimumSize(40, 40)

    def paintEvent(self, _):
        o = self.o
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        s = min(W, H)
        w = max(6, s * 0.06)
        r = QRectF((W - s) / 2 + w, (H - s) / 2 + w, s - 2 * w, s - 2 * w)
        p.setPen(QPen(QColor("#34343a"), w))
        p.drawEllipse(r)
        frac = o.remaining / o.total() if o.total() else 0
        if frac > 0:
            pen = QPen(QColor(COLORS[o.mode]), w)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-min(359.9, 360 * frac) * 16))
        m, sec = divmod(o.remaining, 60)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(max(10, int(s * 0.2)))
        p.setFont(f)
        p.setPen(QColor("#ededed"))
        p.drawText(self.rect(), Qt.AlignCenter, f"{m:02d}:{sec:02d}")
        f.setBold(False)
        f.setPixelSize(max(9, int(s * 0.065)))
        p.setFont(f)
        if s > 120 and o.mode == "Focus" and not o.compact:
            name = o.label.currentText().strip()
            p.setPen(QColor("#ededed" if name else "#6b6b73"))
            txt = p.fontMetrics().elidedText(name or "Name this session", Qt.ElideRight, int(s * 0.7))
            p.drawText(QRectF(0, H / 2 - s * 0.28, W, s * 0.1), Qt.AlignCenter, txt)
        if s > 150 and not o.compact:
            p.setPen(QColor(COLORS[o.mode]))
            p.drawText(QRectF(0, H / 2 + s * 0.13, W, s * 0.1), Qt.AlignCenter, o.mode)


class Pomodoro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(80, 80)
        self.resize(380, 520)
        self.durations = {"Focus": 25, "Short break": 5, "Long break": 15}
        self.mode, self.remaining = "Focus", 25 * 60
        self.running, self.end, self.done = False, 0.0, 0
        self.idx, self.plan = 0, []
        self.compact, self._quitting = False, False

        root = QWidget()
        self.setCentralWidget(root)
        root.setMinimumSize(1, 1)  # window may shrink freely; panels hide as it gets small
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)

        def row():
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            return w, h

        # activity name: front and centre, above the clock
        self.label = QComboBox()
        self.label.setEditable(True)
        self.label.setInsertPolicy(QComboBox.NoInsert)
        self.label.setStyleSheet("font-size:16px;padding:6px")
        self.label.addItems(sorted({r[1] for r in read_log()}))
        self.label.setCurrentIndex(-1)
        self.label.lineEdit().setPlaceholderText("What are you working on? e.g. French learning")
        self.label.editTextChanged.connect(lambda _: self.refresh())
        lay.addWidget(self.label)

        # plan progress
        self.tabs = QLabel()
        self.tabs.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.tabs)

        self.ring = Ring(self)
        lay.addWidget(self.ring, 1)

        # controls
        self.controls, cl = row()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle)
        cl.addWidget(self.start_btn)
        for text, fn, tip in (
            ("Reset", self.reset, "Restart the current step"),
            ("Skip", self.skip, "Go to the next step"),
            ("New plan", self.new_plan, "End everything and start over from session 1"),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            cl.addWidget(b)
        lay.addWidget(self.controls)

        # log options
        self.logrow, ll = row()
        self.log_on = QCheckBox("Log sessions")
        self.log_on.setChecked(True)
        hist = QPushButton("History")
        hist.clicked.connect(self.show_log)
        ll.addWidget(self.log_on, 1)
        ll.addWidget(hist)
        lay.addWidget(self.logrow)

        # durations + auto-start
        self.setrow, sl = row()
        self.spins = {}
        for m in COLORS:
            sp = QSpinBox()
            sp.setRange(1 if m == "Focus" else 0, 180)
            if m != "Focus":
                sp.setSpecialValueText("off")
            sp.setValue(self.durations[m])
            sp.valueChanged.connect(self.apply_settings)
            sl.addWidget(QLabel(m.split()[0]))
            sl.addWidget(sp)
            self.spins[m] = sp
        lay.addWidget(self.setrow)
        self.planrow, pl = row()
        self.sess = QSpinBox()
        self.sess.setRange(1, 12)
        self.sess.setValue(4)
        self.sess.valueChanged.connect(self.apply_plan)
        pl.addWidget(QLabel("Sessions"))
        pl.addWidget(self.sess)
        lay.addWidget(self.planrow)
        self.count = QLabel()
        lay.addWidget(self.count)
        self.mid_panels = [self.label, self.tabs, self.controls]
        self.full_panels = [self.logrow, self.setrow, self.planrow, self.count]

        self.plan = self.build_plan()

        # tray icon
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_icon(COLORS[self.mode], self.remaining), self)
            self.menu = QMenu()
            self.menu.addAction("Show / hide", self.toggle_visible)
            self.menu.addAction("Start / pause", self.toggle)
            self.menu.addAction("Reset", self.reset)
            self.menu.addAction("New plan", self.new_plan)
            self.menu.addAction("Test sound", play_chime)
            self.menu.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(
                lambda r: self.toggle_visible() if r == QSystemTrayIcon.Trigger else None)
            self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.refresh()

    # ----- state -----
    def total(self):
        return self.durations[self.mode] * 60

    def build_plan(self):
        """N focus sessions, short breaks between them, a long break at the end."""
        n = self.sess.value()
        plan = []
        for i in range(n):
            plan.append("Focus")
            brk = "Short break" if i < n - 1 else "Long break"
            if self.durations[brk] > 0:
                plan.append(brk)
        return plan

    def focus_no(self):
        """1-based number of the focus session we are in (or just finished)."""
        return max(1, sum(1 for m in self.plan[: self.idx + 1] if m == "Focus"))

    def apply_plan(self):
        k, in_break = min(self.focus_no(), self.sess.value()), self.mode != "Focus"
        self.plan = self.build_plan()
        idx = [i for i, m in enumerate(self.plan) if m == "Focus"][k - 1]
        if in_break:  # the break after focus k, or whatever follows if it was switched off
            idx = idx + 1 if idx + 1 < len(self.plan) else 0
        if not self.running and self.plan[idx] != self.mode:
            self.go(idx)
        self.idx = idx
        self.refresh()

    def log_elapsed(self):
        """Log time actually spent on the current Focus session (>= 1 min)."""
        elapsed = self.total() - self.remaining
        if self.mode == "Focus" and elapsed >= 60 and self.log_on.isChecked():
            label = self.label.currentText().strip() or "Unlabelled"
            append_log(label, elapsed / 60)
            if self.label.findText(label) < 0:
                self.label.addItem(label)

    def go(self, idx):
        """Jump to step idx of the plan (logs any focus time spent so far)."""
        self.log_elapsed()
        self.running = False
        self.idx = idx
        self.mode = self.plan[idx]
        self.remaining = self.total()
        if self.tray:
            self.tray.setIcon(make_icon(COLORS[self.mode]))
        self.refresh()

    def advance(self, completed):
        """Next step of the plan; after the last one, the plan starts over."""
        nxt = self.idx + 1
        wrapped = nxt >= len(self.plan)
        if wrapped:
            nxt = 0
        if completed:
            if self.tray:
                msg = ("All sessions done. Nice work!" if wrapped
                       else f"{self.mode} finished. Next: {self.plan[nxt]}")
                self.tray.showMessage("Pomodoro", msg, QSystemTrayIcon.Information, 8000)
            play_chime()
        self.go(nxt)
        if wrapped:
            self.done = 0
            self.refresh()
        elif completed:
            self.toggle()

    def apply_settings(self):
        untouched = self.remaining == self.total() and not self.running
        for m, sp in self.spins.items():
            self.durations[m] = sp.value()
        if untouched:
            self.remaining = self.total()
        self.apply_plan()

    def toggle(self):
        if not self.running:
            self.end = time.monotonic() + self.remaining
        self.running = not self.running
        self.refresh()

    def reset(self):
        self.go(self.idx)

    def skip(self):
        self.advance(completed=False)

    def new_plan(self):
        """Abandon the rest of the plan (logging focus time so far) and start fresh."""
        self.done = 0
        self.go(0)
        self.label.setFocus()
        self.label.lineEdit().selectAll()

    def tick(self):
        if not self.running:
            return
        self.remaining = max(0, math.ceil(self.end - time.monotonic()))
        if self.remaining == 0:
            if self.mode == "Focus":
                self.done += 1
            self.advance(completed=True)
            return
        self.refresh()

    # ----- UI -----
    def refresh(self):
        m, s = divmod(self.remaining, 60)
        t = f"{m:02d}:{s:02d} · {self.mode}"
        name = self.label.currentText().strip()
        if self.mode == "Focus" and name:
            t += f" · {name}"
        self.setWindowTitle(t)
        if self.tray:
            self.tray.setToolTip(t)
            self.tray.setIcon(make_icon(COLORS[self.mode], self.remaining))
        self.start_btn.setText("Pause" if self.running else "Start")
        n = self.sess.value()
        dots = "●" * min(self.done, n) + "○" * max(0, n - self.done)
        self.tabs.setText(f"{dots}   Session {min(self.focus_no(), n)} of {n}")
        self.count.setText(f"Focus sessions completed: {self.done}")
        self.ring.update()

    def resizeEvent(self, e):
        """Resize = compact mode: big shows everything, medium the essentials, small only the clock."""
        super().resizeEvent(e)
        if not hasattr(self, "full_panels"):
            return
        w, h = self.width(), self.height()
        full, mid = w >= 360 and h >= 470, w >= 300 and h >= 300
        for x in self.full_panels:
            x.setVisible(full)
        for x in self.mid_panels:
            x.setVisible(mid)
        self.compact = not mid
        self.ring.update()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_log(self):
        rows = read_log()
        totals = {}
        for _, label, mins in rows:
            totals[label] = totals.get(label, 0) + float(mins)
        dlg = QDialog(self)
        dlg.setWindowTitle("Session history")
        dlg.resize(520, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("\n".join(f"{k}: {hm(t)}" for k, t in sorted(totals.items())) or "No sessions yet."))
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["When", "Activity", "Minutes"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for i, r in enumerate(reversed(rows)):
            for j, val in enumerate(r):
                table.setItem(i, j, QTableWidgetItem(val))
        v.addWidget(table)
        v.addWidget(QLabel(f"File: {log_path()}"))
        dlg.exec()

    def quit_app(self):
        self.log_elapsed()
        self._quitting = True
        QApplication.quit()

    def closeEvent(self, e):
        if self.tray and not self._quitting:
            e.ignore()
            self.hide()
        else:
            self.quit_app()
            e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("pomodoro")
    app.setDesktopFileName("pomodoro")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)

    # Use a process lock to coordinate startup. This prevents a second launch
    # from removing the local-server socket while the first instance is starting.
    app_data = Path(QStandardPaths.writableLocation(
        QStandardPaths.AppDataLocation
    ))
    app_data.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(app_data / "pomodoro-instance.lock"))

    if not lock.tryLock(0):
        # Another instance owns the lock. Ask it to show its existing window.
        # Retry briefly because it may still be creating its local server.
        for _ in range(20):
            sock = QLocalSocket()
            sock.connectToServer(SERVER)

            if sock.waitForConnected(200):
                sock.write(b"show")
                sock.waitForBytesWritten(500)
                sock.disconnectFromServer()
                return 0

            sock.abort()
            time.sleep(0.1)

        # Do not start a second copy if the lock says one is already running.
        return 1

    # We own the process lock, so no other live instance can be using this
    # server name. Removing it here is safe and clears a stale socket.
    QLocalServer.removeServer(SERVER)

    server = QLocalServer()
    if not server.listen(SERVER):
        print(f"Could not start local server: {server.errorString()}",
              file=sys.stderr)
        lock.unlock()
        return 1

    w = Pomodoro()

    def on_connection():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn:
                conn.waitForReadyRead(100)
                conn.close()
                conn.deleteLater()
                w.bring_to_front()

    server.newConnection.connect(on_connection)

    w.show()

    # Keep both the lock and server alive for the entire application lifetime.
    return app.exec()



if __name__ == "__main__":
    main()
