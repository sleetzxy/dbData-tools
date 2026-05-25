"""Tests for PG CopyBridge bounded COPY pipe."""

from __future__ import annotations

import threading
import time

import pytest

from core.migration.copy_bridge import CopyBridge, copy_via_bridge


def test_copy_bridge_write_then_read() -> None:
    bridge = CopyBridge(max_bytes=4096)
    assert bridge.write(b"hello") == 5
    assert bridge.read(5) == b"hello"
    bridge.close()


def test_copy_bridge_read_write_ordering_with_threads() -> None:
    bridge = CopyBridge(max_bytes=256)
    chunks = [b"aaa", b"bbb", b"ccc"]
    read_results: list[bytes] = []

    def writer() -> None:
        for chunk in chunks:
            bridge.write(chunk)
        bridge.close_writer()

    def reader() -> None:
        while True:
            data = bridge.read(3)
            if not data:
                break
            read_results.append(data)

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()
    wt.join(timeout=5)
    rt.join(timeout=5)
    assert b"".join(read_results) == b"aaabbbccc"


def test_copy_bridge_bounded_queue_does_not_exceed_max_bytes() -> None:
    max_bytes = 512
    bridge = CopyBridge(max_bytes=max_bytes)
    peak_pending: list[int] = []
    stop = threading.Event()

    def slow_reader() -> None:
        while not stop.is_set():
            bridge.read(64)
            time.sleep(0.001)

    def fast_writer() -> None:
        block = b"x" * 256
        for _ in range(40):
            bridge.write(block)
            peak_pending.append(bridge.pending_bytes)
        bridge.close_writer()

    rt = threading.Thread(target=slow_reader, daemon=True)
    wt = threading.Thread(target=fast_writer)
    rt.start()
    wt.start()
    wt.join(timeout=10)
    stop.set()
    rt.join(timeout=2)
    bridge.close()
    assert peak_pending, "writer should have recorded pending sizes"
    assert max(peak_pending) <= max_bytes


def test_copy_bridge_write_blocks_when_buffer_full() -> None:
    bridge = CopyBridge(max_bytes=128)
    bridge.write(b"a" * 128)
    blocked = threading.Event()
    released = threading.Event()

    def writer() -> None:
        blocked.set()
        bridge.write(b"b" * 64)
        released.set()

    wt = threading.Thread(target=writer)
    wt.start()
    assert blocked.wait(timeout=2)
    time.sleep(0.05)
    assert not released.is_set()
    bridge.read(64)
    assert released.wait(timeout=2)
    wt.join(timeout=2)
    bridge.close()


def test_copy_bridge_closed_property() -> None:
    bridge = CopyBridge(max_bytes=1024)
    assert bridge.closed is False
    bridge.close()
    assert bridge.closed is True


def test_copy_bridge_write_after_close_raises() -> None:
    bridge = CopyBridge(max_bytes=1024)
    bridge.close()
    with pytest.raises(ValueError, match="closed"):
        bridge.write(b"x")


def test_copy_via_bridge_mock_copy_expert(mocker) -> None:
    bridge_holder: list[CopyBridge] = []

    def copy_out(sql: str, buf: CopyBridge) -> None:
        bridge_holder.append(buf)
        buf.write(b"1,a\n2,b\n3,c\n")
        buf.close_writer()

    def copy_in(sql: str, buf: CopyBridge) -> None:
        while buf.read(4096):
            pass

    src_cursor = mocker.MagicMock()
    dst_cursor = mocker.MagicMock()
    src_cursor.copy_expert.side_effect = copy_out
    dst_cursor.copy_expert.side_effect = copy_in

    count = copy_via_bridge(
        src_cursor,
        dst_cursor,
        "COPY (SELECT 1) TO STDOUT",
        "COPY t FROM STDIN",
        max_buffer_bytes=1024,
    )
    assert count == 3
    src_cursor.copy_expert.assert_called_once()
    dst_cursor.copy_expert.assert_called_once()


def test_copy_via_bridge_empty_returns_zero(mocker) -> None:
    def copy_out(sql: str, buf: CopyBridge) -> None:
        buf.close_writer()

    def copy_in(sql: str, buf: CopyBridge) -> None:
        pass

    src_cursor = mocker.MagicMock()
    dst_cursor = mocker.MagicMock()
    src_cursor.copy_expert.side_effect = copy_out
    dst_cursor.copy_expert.side_effect = copy_in

    count = copy_via_bridge(
        src_cursor,
        dst_cursor,
        "COPY (SELECT 1) TO STDOUT WHERE false",
        "COPY t FROM STDIN",
        max_buffer_bytes=1024,
    )
    assert count == 0


def test_copy_via_bridge_src_error_closes_bridge_and_reraises(mocker) -> None:
    def copy_out(sql: str, buf: CopyBridge) -> None:
        buf.write(b"partial\n")
        raise RuntimeError("src copy failed")

    src_cursor = mocker.MagicMock()
    dst_cursor = mocker.MagicMock()
    src_cursor.copy_expert.side_effect = copy_out
    dst_cursor.copy_expert.side_effect = lambda sql, buf: None

    with pytest.raises(RuntimeError, match="src copy failed"):
        copy_via_bridge(
            src_cursor,
            dst_cursor,
            "COPY TO STDOUT",
            "COPY FROM STDIN",
            max_buffer_bytes=1024,
        )
