from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


SERVER_NAME = "CleanDesk.SingleInstance"
SHOW_MESSAGE = "show"


class SingleInstanceError(RuntimeError):
    pass


class SingleInstanceManager(QObject):
    show_requested = Signal()

    def __init__(
        self,
        server_name: str = SERVER_NAME,
        *,
        server_factory: Callable[[], QLocalServer] = QLocalServer,
        socket_factory: Callable[[], QLocalSocket] = QLocalSocket,
        remove_server: Callable[[str], bool] = QLocalServer.removeServer,
    ) -> None:
        super().__init__()
        self.server_name = server_name
        self._server_factory = server_factory
        self._socket_factory = socket_factory
        self._remove_server = remove_server
        self._server: QLocalServer | None = None
        self._clients: set[QLocalSocket] = set()
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def acquire(self, notify_message: str = SHOW_MESSAGE) -> bool:
        if self.try_notify_existing_instance(notify_message):
            return False

        if self._listen():
            return True

        # A second process may have won the race between our connect and listen.
        if self.try_notify_existing_instance(notify_message):
            return False

        self._remove_server(self.server_name)
        if self._listen():
            return True
        raise SingleInstanceError("无法建立 CleanDesk 单实例通信，请稍后重试。")

    def try_notify_existing_instance(self, message: str = SHOW_MESSAGE) -> bool:
        socket = self._socket_factory()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(300):
            socket.abort()
            return False
        socket.write(f"{message}\n".encode("utf-8"))
        socket.flush()
        if socket.bytesToWrite() and not socket.waitForBytesWritten(300):
            socket.abort()
            return False
        socket.waitForReadyRead(500)
        socket.disconnectFromServer()
        return True

    def close(self) -> None:
        for socket in tuple(self._clients):
            socket.abort()
        self._clients.clear()
        self._buffers.clear()
        if self._server is not None:
            self._server.close()
            self._server = None
            self._remove_server(self.server_name)

    def _listen(self) -> bool:
        server = self._server_factory()
        if not server.listen(self.server_name):
            server.close()
            return False
        self._server = server
        server.newConnection.connect(self._accept_connections)
        return True

    def _accept_connections(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._clients.add(socket)
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_client(current))
            socket.disconnected.connect(lambda current=socket: self._discard_client(current))
            self._read_client(socket)

    def _read_client(self, socket: QLocalSocket) -> None:
        if socket not in self._buffers:
            return
        self._buffers[socket].extend(bytes(socket.readAll()))
        buffer = self._buffers[socket]
        while b"\n" in buffer:
            raw_message, _, remainder = buffer.partition(b"\n")
            self._buffers[socket] = buffer = bytearray(remainder)
            message = raw_message.decode("utf-8", errors="ignore").strip()
            if message == SHOW_MESSAGE:
                self.show_requested.emit()
            socket.write(b"ok\n")
            socket.flush()

    def _discard_client(self, socket: QLocalSocket) -> None:
        self._clients.discard(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()
