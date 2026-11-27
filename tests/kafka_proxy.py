"""A TCP proxy in front of Kafka's FAULTS listener that can cut connections just before the broker's reply.

    with KafkaReplyCutter() as proxy:       # listens on 127.0.0.1:19092, forwards to 127.0.0.1:19093
        proxy.cut_replies.set()             # a request still reaches the broker, which writes it; the moment the
        ...                                 # broker starts to reply, the proxy resets both sides of the connection
        proxy.cut_replies.clear()

This is the Toxiproxy pattern, in-process. It gives "written, but the acknowledgement was lost": the producer
reconnects and sends the same batch again, so the broker sees it twice. Kafka advertises the FAULTS listener as
127.0.0.1:19092 (docker-compose.yml), so every connection a client opens, including the reconnects, comes back
through here.

Built because pausing the Kafka container didn't reliably time out a request on Docker Desktop. A first version that
silently dropped reply bytes broke Kafka's message framing, and the producer never recovered. Resetting the connection
is what a real lost reply looks like to a client (verification log, M2 PR-B2b).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any

LISTEN = ("127.0.0.1", 19092)
TARGET = ("127.0.0.1", 19093)


class KafkaReplyCutter:
    def __init__(self, listen: tuple[str, int] = LISTEN, target: tuple[str, int] = TARGET) -> None:
        self.listen, self.target = listen, target
        self.cut_replies = threading.Event()
        self.forwarded_bytes = 0  # client -> broker
        self.cuts = 0  # connections reset because the broker started to reply while cut_replies was set
        self.produce_requests = 0  # ProduceRequests (API key 0) passed to the broker
        self.produce_acks_cut = 0  # ProduceRequests the broker received whose reply never reached the client
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._server: Any = None
        self._tasks: set[asyncio.Task[None]] = set()

    def __enter__(self) -> KafkaReplyCutter:
        self._thread.start()
        self._server = asyncio.run_coroutine_threadsafe(
            asyncio.start_server(self._handle, *self.listen), self._loop
        ).result(10)
        return self

    def __exit__(self, *exc: object) -> None:
        async def close() -> None:
            self._server.close()
            for task in list(self._tasks):  # open connections end with the proxy
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 5)

        asyncio.run_coroutine_threadsafe(close(), self._loop).result(15)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)

    async def _handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            broker_reader, broker_writer = await asyncio.open_connection(*self.target)
        except OSError:
            client_writer.close()
            return

        def reset() -> None:
            for writer in (client_writer, broker_writer):
                transport = writer.transport
                if hasattr(transport, "abort"):
                    transport.abort()  # an RST, like a dropped network path; never a half-sent reply
                else:
                    writer.close()

        unanswered = {"produce": 0}  # ProduceRequests on this connection with no reply passed back yet
        frames = bytearray()

        def count_requests(data: bytes) -> None:
            # A Kafka request is a 4-byte size, then a 2-byte API key (0 = Produce). Frames can span reads.
            frames.extend(data)
            while len(frames) >= 6:
                size = int.from_bytes(frames[0:4], "big")
                if len(frames) < 4 + size:
                    return
                if int.from_bytes(frames[4:6], "big") == 0:
                    self.produce_requests += 1
                    unanswered["produce"] += 1
                del frames[: 4 + size]

        async def up() -> None:  # requests always reach the broker
            while data := await client_reader.read(65536):
                self.forwarded_bytes += len(data)
                count_requests(data)
                broker_writer.write(data)
                await broker_writer.drain()

        async def down() -> None:
            while data := await broker_reader.read(65536):
                if self.cut_replies.is_set():
                    self.cuts += 1
                    self.produce_acks_cut += unanswered["produce"]
                    reset()
                    return
                unanswered["produce"] = 0  # replies come in request order: these answer what was sent before
                client_writer.write(data)
                await client_writer.drain()

        try:
            await asyncio.gather(up(), down())
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            reset()
            if task is not None:
                self._tasks.discard(task)
