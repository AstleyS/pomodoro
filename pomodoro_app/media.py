"""Expose Pomodoro controls and countdown metadata through desktop MPRIS."""
import asyncio
import threading

from PySide6.QtCore import QObject, Signal


class MediaBridge(QObject):
    """Forward D-Bus actions safely from its worker thread to the Qt UI thread."""

    toggle = Signal()
    skip = Signal()
    reset = Signal()
    show = Signal()


class MprisServer:
    """Publish the timer as a media player for desktop notification panels."""

    def __init__(self, owner):
        self.owner = owner
        self.bridge = MediaBridge()
        self.bridge.toggle.connect(owner.toggle)
        self.bridge.skip.connect(owner.skip)
        self.bridge.reset.connect(owner.reset)
        self.bridge.show.connect(owner.show_from_media)
        self.loop = None
        self.player = None
        self.last_state = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        from dbus_next import BusType, PropertyAccess, Variant
        from dbus_next.aio import MessageBus
        from dbus_next.service import ServiceInterface, dbus_property, method

        owner = self.owner
        bridge = self.bridge

        class RootInterface(ServiceInterface):
            def __init__(self):
                super().__init__("org.mpris.MediaPlayer2")

            @dbus_property(access=PropertyAccess.READ)
            def Identity(self) -> "s":
                return "Pomodoro"

            @dbus_property(access=PropertyAccess.READ)
            def DesktopEntry(self) -> "s":
                return "pomodoro"

            @dbus_property(access=PropertyAccess.READ)
            def CanQuit(self) -> "b":
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanRaise(self) -> "b":
                return True

            @dbus_property(access=PropertyAccess.READ)
            def HasTrackList(self) -> "b":
                return False

            @dbus_property(access=PropertyAccess.READ)
            def SupportedUriSchemes(self) -> "as":
                return []

            @dbus_property(access=PropertyAccess.READ)
            def SupportedMimeTypes(self) -> "as":
                return []

            @method()
            def Raise(self):
                bridge.show.emit()

        class PlayerInterface(ServiceInterface):
            def __init__(self):
                super().__init__("org.mpris.MediaPlayer2.Player")
                self._loop_status = "None"
                self._rate = 1.0
                self._shuffle = False
                self._volume = 1.0

            @dbus_property(access=PropertyAccess.READ)
            def PlaybackStatus(self) -> "s":
                return "Playing" if owner.running else "Paused"

            @dbus_property(access=PropertyAccess.READWRITE)
            def LoopStatus(self) -> "s":
                return self._loop_status

            @LoopStatus.setter
            def LoopStatus(self, value: "s"):
                self._loop_status = value

            @dbus_property(access=PropertyAccess.READWRITE)
            def Rate(self) -> "d":
                return self._rate

            @Rate.setter
            def Rate(self, value: "d"):
                self._rate = value

            @dbus_property(access=PropertyAccess.READWRITE)
            def Shuffle(self) -> "b":
                return self._shuffle

            @Shuffle.setter
            def Shuffle(self, value: "b"):
                self._shuffle = value

            @dbus_property(access=PropertyAccess.READ)
            def Metadata(self) -> "a{sv}":
                minutes, seconds = divmod(owner.remaining, 60)
                return {
                    "mpris:trackid": Variant("o", "/org/mpris/MediaPlayer2/track/0"),
                    "mpris:length": Variant("x", owner.total() * 1_000_000),
                    "xesam:title": Variant("s", f"{owner.mode} {minutes:02d}:{seconds:02d}"),
                    "xesam:artist": Variant("as", ["Pomodoro"]),
                }

            @dbus_property(access=PropertyAccess.READWRITE)
            def Volume(self) -> "d":
                return self._volume

            @Volume.setter
            def Volume(self, value: "d"):
                self._volume = value

            @dbus_property(access=PropertyAccess.READ)
            def Position(self) -> "x":
                return (owner.total() - owner.remaining) * 1_000_000

            @dbus_property(access=PropertyAccess.READ)
            def MinimumRate(self) -> "d":
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def MaximumRate(self) -> "d":
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def CanGoNext(self) -> "b":
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanGoPrevious(self) -> "b":
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanPlay(self) -> "b":
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanPause(self) -> "b":
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanSeek(self) -> "b":
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanControl(self) -> "b":
                return True

            @method()
            def Play(self):
                if not owner.running:
                    bridge.toggle.emit()

            @method()
            def Pause(self):
                if owner.running:
                    bridge.toggle.emit()

            @method()
            def PlayPause(self):
                bridge.toggle.emit()

            @method()
            def Stop(self):
                if owner.running:
                    bridge.toggle.emit()

            @method()
            def Next(self):
                bridge.skip.emit()

            @method()
            def Previous(self):
                bridge.reset.emit()

        async def connect():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            bus.export("/org/mpris/MediaPlayer2", RootInterface())
            self.player = PlayerInterface()
            bus.export("/org/mpris/MediaPlayer2", self.player)
            await bus.request_name("org.mpris.MediaPlayer2.pomodoro")

        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(connect())
            self.loop.run_forever()
        except Exception:
            self.player = None

    def update(self):
        """Publish timer status and countdown metadata when they change."""
        if not self.loop or not self.player:
            return
        state = (self.owner.running, self.owner.mode, self.owner.remaining)
        if state == self.last_state:
            return
        self.last_state = state
        changed = {
            "PlaybackStatus": "Playing" if self.owner.running else "Paused",
            "Metadata": self.player.Metadata,
            "Position": (self.owner.total() - self.owner.remaining) * 1_000_000,
        }
        self.loop.call_soon_threadsafe(self.player.emit_properties_changed, changed)

    def close(self):
        """Stop the service event loop when the application quits."""
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
