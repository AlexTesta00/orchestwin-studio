"""Bounded TCP bridge for a host API to the private Compose PostgreSQL network.

Run only through compose.models.yaml: Docker publishes the listener on loopback.
PostgreSQL authentication remains end to end; this process reads no credentials.
"""

import select
import socket
import socketserver
import threading

MAX_CONNECTIONS = 16
IDLE_TIMEOUT_SECONDS = 60


def relay(client, upstream):
    """Bounded chunks, socket write deadlines, and explicit half-close propagation."""
    peers = {client: upstream, upstream: client}
    readers = [client, upstream]
    for stream in readers:
        stream.settimeout(10)
    while readers:
        readable, _, _ = select.select(readers, [], [], IDLE_TIMEOUT_SECONDS)
        if not readable:
            return
        for stream in readable:
            data = stream.recv(65536)
            if data:
                peers[stream].sendall(data)
            else:
                peers[stream].shutdown(socket.SHUT_WR)
                readers.remove(stream)


class Bridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, target):
        self.target = target
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, Handler)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.slots.acquire(blocking=False):
            return
        try:
            with socket.create_connection(self.server.target, timeout=10) as upstream:
                relay(self.request, upstream)
        except OSError:
            # Never log PostgreSQL protocol bytes, user names or authentication data.
            pass
        finally:
            self.server.slots.release()


if __name__ == "__main__":
    with Bridge(("0.0.0.0", 15432), ("database", 5432)) as server:
        server.serve_forever()
