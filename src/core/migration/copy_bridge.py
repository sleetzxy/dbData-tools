"""Bounded in-memory pipe for concurrent PostgreSQL COPY TO/FROM STDIN/STDOUT."""

from __future__ import annotations

import csv
import io
import threading
from typing import Any


class CopyBridge:
    """Thread-safe, bounded buffer acting as a file-like COPY pipe.

    ``copy_expert`` on the source connection writes via ``write``; the
    destination reads via ``read``. ``max_bytes`` caps total in-flight data;
    writers block when the buffer is full (backpressure).
    """

    def __init__(self, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._can_write = threading.Condition(self._lock)
        self._can_read = threading.Condition(self._lock)
        self._buffer = bytearray()
        self._pending = 0
        self._writer_closed = False
        self._closed = False
        self._all_written = bytearray()

    @property
    def closed(self) -> bool:
        """True after ``close`` has been called."""
        return self._closed

    @property
    def pending_bytes(self) -> int:
        """Current in-flight byte count (for tests and diagnostics)."""
        with self._lock:
            return self._pending

    def write(self, data: bytes) -> int:
        """Write bytes; block until buffer has capacity."""
        if self._closed:
            raise ValueError("write to closed CopyBridge")
        if not data:
            return 0

        if isinstance(data, str):
            data = data.encode("utf-8")

        offset = 0
        total = len(data)
        while offset < total:
            with self._can_write:
                while (
                    self._pending >= self.max_bytes
                    and not self._closed
                    and not self._writer_closed
                ):
                    self._can_write.wait()
                if self._closed:
                    raise ValueError("write to closed CopyBridge")

                space = self.max_bytes - self._pending
                if space <= 0 and not self._writer_closed:
                    continue

                chunk_len = min(total - offset, space) if space > 0 else 0
                if chunk_len <= 0:
                    self._can_write.wait()
                    continue

                chunk = data[offset : offset + chunk_len]
                self._buffer.extend(chunk)
                self._all_written.extend(chunk)
                self._pending += chunk_len
                offset += chunk_len
                self._can_read.notify_all()

        return total

    def read(self, size: int = -1) -> bytes:
        """Read bytes; block until data or writer EOF."""
        with self._can_read:
            while True:
                if self._closed and not self._buffer:
                    return b""

                if self._buffer:
                    if size < 0:
                        n = len(self._buffer)
                    else:
                        n = min(size, len(self._buffer))
                    result = bytes(self._buffer[:n])
                    del self._buffer[:n]
                    self._pending -= n
                    self._can_write.notify_all()
                    return result

                if self._writer_closed or self._closed:
                    return b""

                self._can_read.wait()

    def close_writer(self) -> None:
        """Signal that COPY TO finished; readers drain then see EOF."""
        with self._lock:
            self._writer_closed = True
            self._can_read.notify_all()
            self._can_write.notify_all()

    def close(self) -> None:
        """Shut down the bridge and wake blocked threads."""
        with self._lock:
            self._closed = True
            self._writer_closed = True
            self._can_read.notify_all()
            self._can_write.notify_all()

    def row_count(self) -> int:
        """Count CSV rows transferred (accurate for well-formed COPY CSV)."""
        raw = bytes(self._all_written)
        if not raw.strip():
            return 0
        text = raw.decode("utf-8", errors="replace")
        return sum(1 for _ in csv.reader(io.StringIO(text)))


def copy_via_bridge(
    src_cursor: Any,
    dst_cursor: Any,
    src_copy_sql: str,
    dst_copy_sql: str,
    max_buffer_bytes: int,
) -> int:
    """Stream COPY TO STDOUT on ``src_cursor`` into COPY FROM STDIN on ``dst_cursor``.

    Runs source and destination ``copy_expert`` calls concurrently on a shared
    :class:`CopyBridge`. On error the bridge is closed and the exception is
    re-raised.

    :param src_cursor: Cursor for COPY TO (writes into bridge).
    :param dst_cursor: Cursor for COPY FROM (reads from bridge).
    :param src_copy_sql: COPY ... TO STDOUT SQL.
    :param dst_copy_sql: COPY ... FROM STDIN SQL.
    :param max_buffer_bytes: Maximum in-flight buffer size.
    :return: Number of CSV data rows transferred (0 if empty).
    """
    bridge = CopyBridge(max_buffer_bytes)
    errors: list[BaseException] = []

    def _src_copy() -> None:
        try:
            src_cursor.copy_expert(src_copy_sql, bridge)
        except BaseException as exc:
            errors.append(exc)
        finally:
            bridge.close_writer()

    def _dst_copy() -> None:
        try:
            dst_cursor.copy_expert(dst_copy_sql, bridge)
        except BaseException as exc:
            errors.append(exc)

    src_thread = threading.Thread(target=_src_copy, name="copy-bridge-src")
    dst_thread = threading.Thread(target=_dst_copy, name="copy-bridge-dst")

    try:
        src_thread.start()
        dst_thread.start()
        src_thread.join()
        dst_thread.join()
    finally:
        bridge.close()

    if errors:
        raise errors[0]

    return bridge.row_count()
