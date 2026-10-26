"""Ensure repeated launches activate the user's existing timer window."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """Own local IPC and notify the primary process when launched again."""

    activated = Signal()

    def __init__(self, name):
        super().__init__()
        self.server = QLocalServer(self)
        self.is_primary = self.server.listen(name)
        if not self.is_primary:
            client = QLocalSocket()
            client.connectToServer(name)
            if client.waitForConnected(500):
                client.write(b"show")
                client.waitForBytesWritten(500)
                client.disconnectFromServer()
                return

            QLocalServer.removeServer(name)
            self.is_primary = self.server.listen(name)

        if self.is_primary:
            self.server.newConnection.connect(self.handle_connection)

    def handle_connection(self):
        client = self.server.nextPendingConnection()
        if client:
            client.readyRead.connect(lambda: self.handle_request(client))
            client.disconnected.connect(client.deleteLater)

    def handle_request(self, client):
        if bytes(client.readAll()).strip() == b"show":
            self.activated.emit()
