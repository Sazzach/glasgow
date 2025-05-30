import argparse
import asyncio
import logging
import re
from collections import deque

from .aobject import *
from .logging import dump_hex


__all__ = ["ServerEndpoint", "ClientEndpoint"]


def endpoint(spec):
    m = re.match(r"^(unix):(.*)$", spec)
    if m: return (m[1], m[2])

    m = re.match(r"^(tcp):(?:()|\*|\[([a-fA-F0-9:]+)\]|(\d+(?:\.\d+){3})|([a-zA-Z.-]+))"
                 r":(\d+)$", spec)
    if m: return (m[1], m[3] or m[4] or m[5] if m[2] is None else "localhost", int(m[6]))

    raise argparse.ArgumentTypeError(f"invalid endpoint: {spec!r}")


class ServerEndpoint(aobject, asyncio.Protocol):
    @classmethod
    def add_argument(cls, parser, name, default=None):
        metavar = name.upper().replace("_", "-")
        help    = "listen at %s, either unix:PATH or tcp:HOST:PORT" % metavar
        if default is None:
            nargs = None
        else:
            nargs = "?"
            help += " (default: %(default)s)"

        parser.add_argument(
            name, metavar=metavar, type=endpoint, nargs=nargs, default=default,
            help=help)

    async def __init__(self, name, logger, sock_addr, queue_size=None, *,
                       deprecated_cancel_on_eof=False):
        assert isinstance(sock_addr, tuple)

        self.name    = name
        self._logger = logger

        proto, *proto_args = sock_addr
        loop = asyncio.get_event_loop()
        if proto == "unix":
            self.server = await loop.create_unix_server(lambda: self, *proto_args, backlog=1)
            unix_path, = proto_args
            self._log(logging.INFO, "listening at unix:%s", unix_path)
        elif proto == "tcp":
            self.server = await loop.create_server(lambda: self, *proto_args, backlog=1)
            tcp_host, tcp_port = proto_args
            self._log(logging.INFO, "listening at tcp:%s:%d", tcp_host or "*", tcp_port)
        else:
            raise ValueError("unknown protocol %s" % proto)

        self._transport     = None
        self._new_transport = None

        self._send_epoch = 0
        self._recv_epoch = 1
        self._queue      = deque()
        self._queued     = 0
        self._queue_size = queue_size
        self._future     = None

        self._buffer = None
        self._pos    = 0

        self._read_paused = False

        self._cancel_on_eof = deprecated_cancel_on_eof
        if self._cancel_on_eof:
            self._log(logging.WARNING,
                "ServerEndpoint with cancel-on-EOF behavior is deprecated; please fix this applet "
                "and submit a pull request (thanks in advance!)")

    def _log(self, level, message, *args):
        self._logger.log(level, self.name + ": " + message, *args)

    def connection_made(self, transport):
        self._send_epoch += 1

        peername = transport.get_extra_info("peername")
        if peername:
            self._log(logging.INFO, "new connection from [%s]:%d", *peername[0:2])
        else:
            self._log(logging.INFO, "new connection")

        if self._transport is None:
            self._transport = transport
        else:
            self._log(logging.INFO, "closing old connection")
            self._transport.close()
            self._new_transport = transport
        self.data_received(b"")

    def connection_lost(self, exc):
        peername = self._transport.get_extra_info("peername")
        if peername:
            self._log(logging.INFO, "connection from [%s]:%d lost", *peername[0:2])
        else:
            self._log(logging.INFO, "connection lost")

        self._transport, self._new_transport = self._new_transport, None
        self._queue.append(exc)
        self._check_future()

    def data_received(self, data):
        self._log(logging.TRACE, "endpoint received %d bytes", len(data))
        self._queue.append(data)
        self._queued += len(data)
        self._check_pushback()
        self._check_future()

    def _check_pushback(self):
        if self._queue_size is None:
            return
        elif not self._read_paused and self._queued >= self._queue_size:
            self._log(logging.TRACE, "queue full, pausing reads")
            self._transport.pause_reading()
            self._read_paused = True
        elif self._read_paused and self._queued < self._queue_size:
            self._log(logging.TRACE, "queue not full, resuming reads")
            self._transport.resume_reading()
            self._read_paused = False

    def _check_future(self):
        if self._queue and self._future is not None:
            item = self._queue.popleft()
            if isinstance(item, Exception):
                self._future.set_exception(item)
            else:
                self._future.set_result(item)
            self._future = None

    async def _refill(self):
        self._future = future = asyncio.Future()
        self._check_future()
        try:
            self._buffer = await future
        except BrokenPipeError:
            self._buffer = None
        if self._buffer is None:
            self._buffer = b""
            self._log(logging.TRACE, "recv end-of-stream")
            self._recv_epoch += 1
            if self._cancel_on_eof:
                raise asyncio.CancelledError
            else:
                raise EOFError

    async def recv(self, length=0):
        data = bytearray()
        while length == 0 or len(data) < length:
            if not self._buffer:
                self._log(logging.TRACE, "recv waits for %d bytes", length - len(data))
                await self._refill()

            if length == 0:
                length = len(self._buffer)

            chunk = self._buffer[:length - len(data)]
            self._buffer = self._buffer[len(chunk):]
            self._queued -= len(chunk)
            self._check_pushback()
            data += chunk

        self._log(logging.TRACE, "recv <%s>", dump_hex(data))
        return data

    async def recv_until(self, separator):
        separator = bytes(separator)
        data = bytearray()
        while True:
            if not self._buffer:
                self._log(logging.TRACE, "recv waits for <%s>", separator.hex())
                await self._refill()

            try:
                index = self._buffer.index(separator)
                chunk = self._buffer[:index]
                self._buffer = self._buffer[index + 1:]
                self._queued -= len(chunk)
                self._check_pushback()
                data += chunk
                break

            except ValueError:
                data += self._buffer
                self._queued -= len(self._buffer)
                self._check_pushback()
                self._buffer = None

        self._log(logging.TRACE, "recv <%s%s>", dump_hex(data), separator.hex())
        return data

    async def recv_wait(self):
        if not self._buffer:
            self._log(logging.TRACE, "recv wait")
            await self._refill()

    async def send(self, data):
        data = bytes(data)
        if self._transport is not None and self._send_epoch == self._recv_epoch:
            self._log(logging.TRACE, "send <%s>", dump_hex(data))
            self._transport.write(data)
            return True
        else:
            self._log(logging.TRACE, "send to previous connection discarded")
            return False

    async def close(self):
        if self._transport:
            self._transport.close()


class ClientEndpoint(aobject, asyncio.Protocol):
    @classmethod
    def add_argument(cls, parser, name, default=None):
        metavar = name.upper().replace("_", "-")
        help    = "connect to %s, either unix:PATH or tcp:HOST:PORT" % metavar
        if default is None:
            nargs = None
        else:
            nargs = "?"
            help += " (default: %(default)s)"

        parser.add_argument(
            name, metavar=metavar, type=endpoint, nargs=nargs, default=default,
            help=help)

    # FIXME: finish this
