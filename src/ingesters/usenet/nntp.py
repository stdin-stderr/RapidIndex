"""Minimal NNTP client using raw SSL sockets.

Implements only the commands needed by the Spotnet ingester:
GROUP, XOVER, ARTICLE. nntplib was removed in Python 3.13.
"""

from __future__ import annotations

import logging
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Iterator

log = logging.getLogger(__name__)

_BACKOFF = [1, 2, 4, 8, 15, 30]
_RECV_SIZE = 65536


@dataclass
class GroupInfo:
    name: str
    count: int
    low: int
    high: int


@dataclass
class Article:
    article_num: int
    subject: str
    poster: str
    date: str
    message_id: str
    references: str
    bytes: int
    lines: int


class NNTPError(Exception):
    pass


class NNTPClient:
    def __init__(self, host: str, port: int, ssl: bool, username: str, password: str):
        self.host = host
        self.port = port
        self.use_ssl = ssl
        self.username = username
        self.password = password
        self._sock: socket.socket | None = None
        self._buf = b""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        for attempt, delay in enumerate([0] + _BACKOFF):
            if delay:
                log.info("Reconnecting in %ds (attempt %d)", delay, attempt)
                time.sleep(delay)
            try:
                self._connect_once()
                return
            except (OSError, NNTPError) as exc:
                log.warning("Connect failed: %s", exc)
                self._close_socket()
        raise RuntimeError(f"Could not connect to {self.host} after retries")

    def _connect_once(self) -> None:
        raw = socket.create_connection((self.host, self.port), timeout=30)
        if self.use_ssl:
            ctx = ssl.create_default_context()
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            self._sock = raw
        self._buf = b""

        code, _ = self._read_response()
        if code not in (200, 201):
            raise NNTPError(f"Unexpected greeting: {code}")

        if self.username:
            self._send(f"AUTHINFO USER {self.username}")
            code, msg = self._read_response()
            if code == 381:
                self._send(f"AUTHINFO PASS {self.password}")
                code, msg = self._read_response()
                if code != 281:
                    raise NNTPError(f"Auth failed: {code} {msg}")
            elif code != 281:
                raise NNTPError(f"AUTHINFO USER failed: {code} {msg}")

        log.info("Connected to %s:%d", self.host, self.port)

    def quit(self) -> None:
        if self._sock:
            try:
                self._send("QUIT")
            except Exception:
                pass
            self._close_socket()

    def _close_socket(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _ensure_connected(self) -> None:
        if self._sock is None:
            self.connect()

    # ------------------------------------------------------------------
    # Low-level protocol I/O
    # ------------------------------------------------------------------

    def _send(self, cmd: str) -> None:
        assert self._sock is not None
        self._sock.sendall((cmd + "\r\n").encode("utf-8"))

    def _readline(self) -> bytes:
        """Read one CRLF-terminated line from the socket buffer."""
        while b"\n" not in self._buf:
            chunk = self._sock.recv(_RECV_SIZE)  # type: ignore[union-attr]
            if not chunk:
                raise NNTPError("Connection closed by server")
            self._buf += chunk
        idx = self._buf.index(b"\n")
        line, self._buf = self._buf[: idx + 1], self._buf[idx + 1 :]
        return line

    def _read_response(self) -> tuple[int, str]:
        line = self._readline().decode("utf-8", errors="replace").rstrip("\r\n")
        if len(line) < 3 or not line[:3].isdigit():
            raise NNTPError(f"Invalid response: {line!r}")
        return int(line[:3]), line[4:]

    def _read_multiline(self) -> list[bytes]:
        """Read a dot-terminated multiline response body."""
        result: list[bytes] = []
        while True:
            line = self._readline()
            stripped = line.rstrip(b"\r\n")
            if stripped == b".":
                break
            # Undo dot-stuffing: leading ".." → "."
            result.append(stripped[1:] if stripped.startswith(b"..") else stripped)
        return result

    # ------------------------------------------------------------------
    # NNTP commands
    # ------------------------------------------------------------------

    def group_info(self, name: str) -> GroupInfo:
        self._ensure_connected()
        self._send(f"GROUP {name}")
        code, msg = self._read_response()
        if code != 211:
            raise NNTPError(f"GROUP {name} failed: {code} {msg}")
        parts = msg.split()
        return GroupInfo(name=name, count=int(parts[0]), low=int(parts[1]), high=int(parts[2]))

    def xover(self, low: int, high: int) -> list[Article]:
        """Fetch overview records for the article range [low, high] inclusive."""
        self._ensure_connected()
        self._send(f"XOVER {low}-{high}")
        code, msg = self._read_response()
        if code in (420, 423):   # no current article / no articles in range
            return []
        if code != 224:
            log.debug("XOVER %d-%d returned %d: %s", low, high, code, msg)
            return []
        articles: list[Article] = []
        for line in self._read_multiline():
            try:
                articles.append(_parse_overview(line.decode("utf-8", errors="replace")))
            except Exception as exc:
                log.debug("Skip overview line: %s", exc)
        return articles

    def fetch_article(self, message_id: str) -> list[bytes] | None:
        """Download a full article (headers + body). Returns raw lines without CRLF."""
        self._ensure_connected()
        mid = f"<{message_id.strip('<>')}>"
        self._send(f"ARTICLE {mid}")
        code, _ = self._read_response()
        if code != 220:
            log.debug("ARTICLE %s returned %d", mid, code)
            return None
        return self._read_multiline()

    def fetch_segment_body(self, message_id: str) -> bytes | None:
        """Return the body bytes of a Spotnet segment article (headers stripped)."""
        lines = self.fetch_article(message_id)
        if not lines:
            return None
        body: list[bytes] = []
        in_body = False
        for line in lines:
            if not in_body:
                if line == b"":
                    in_body = True
                continue
            body.append(line)
        return b"".join(body) if body else None

    def xover_batched(
        self, low: int, high: int, batch_size: int = 5000
    ) -> Iterator[list[Article]]:
        """Yield batches of Article objects across [low, high]."""
        pos = low
        while pos <= high:
            end = min(pos + batch_size - 1, high)
            try:
                batch = self.xover(pos, end)
            except (OSError, NNTPError) as exc:
                log.warning("XOVER error at %d-%d: %s — reconnecting", pos, end, exc)
                self._sock = None
                self.connect()
                batch = self.xover(pos, end)
            yield batch
            pos = end + 1


def _parse_overview(line: str) -> Article:
    """Parse a tab-separated XOVER response line."""
    parts = line.split("\t")

    def _s(i: int) -> str:
        return parts[i].strip() if i < len(parts) else ""

    def _i(i: int) -> int:
        try:
            return int(_s(i))
        except ValueError:
            return 0

    return Article(
        article_num=_i(0),
        subject=_s(1),
        poster=_s(2),
        date=_s(3),
        message_id=_s(4).strip("<>"),
        references=_s(5),
        bytes=_i(6),
        lines=_i(7),
    )
