"""EmailMonitorService 轮询服务单元测试。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.email_monitor.dedup import DedupStore, make_dedup_key
from core.email_monitor.models import MonitorConfig
from core.email_monitor.service import EmailMonitorService


def _minimal_config(download_dir: Path) -> MonitorConfig:
    return MonitorConfig(
        host="imap.example.com",
        port=993,
        account="user@example.com",
        password="secret",
        senders=["sender@example.com"],
        download_dir=str(download_dir),
        extensions=[".csv"],
        lookback_days=7,
        interval_seconds=1,
    )


def test_service_stops_after_five_consecutive_failures(mocker, tmp_path):
    """连续五轮 tick 失败后应调用 on_fatal 并停止。"""
    on_fatal = mocker.Mock()
    fetch = mocker.Mock(side_effect=RuntimeError("imap down"))

    service = EmailMonitorService(
        dedup_path=tmp_path / "seen.json",
        on_fatal=on_fatal,
        fetch_attachments=fetch,
    )
    cfg = _minimal_config(tmp_path / "dl")
    cfg.interval_seconds = 1
    (tmp_path / "dl").mkdir()

    service.start(cfg)
    deadline = time.monotonic() + 10.0
    while service.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not service.is_running()
    on_fatal.assert_called_once()
    assert fetch.call_count >= 5


def test_service_skips_deduped_attachment(tmp_path, mocker):
    """已在去重库中的附件不应再次落盘。"""
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    dedup_path = tmp_path / "seen.json"

    account = "user@example.com"
    uid = "42"
    filename = "report.csv"
    key = make_dedup_key(account, uid, filename)
    DedupStore(dedup_path).add(key)

    save_mock = mocker.patch(
        "core.email_monitor.service.save_attachment_bytes",
        autospec=True,
    )
    fetch = mocker.Mock(
        return_value=iter([(uid, filename, b"csv-bytes")]),
    )

    service = EmailMonitorService(
        dedup_path=dedup_path,
        fetch_attachments=fetch,
    )
    cfg = _minimal_config(download_dir)
    cfg.account = account
    cfg.interval_seconds = 60

    service.start(cfg)
    # 等待首轮 tick 完成
    deadline = time.monotonic() + 5.0
    while fetch.call_count < 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    service.stop()

    assert fetch.call_count >= 1
    save_mock.assert_not_called()
    assert not any(download_dir.iterdir())


def test_service_runs_immediate_first_tick(tmp_path, mocker):
    """start 后应立即执行首轮 tick，无需等满整个 interval。"""
    download_dir = tmp_path / "dl"
    download_dir.mkdir()

    fetch = mocker.Mock(return_value=iter([]))
    service = EmailMonitorService(
        dedup_path=tmp_path / "seen.json",
        fetch_attachments=fetch,
    )
    cfg = _minimal_config(download_dir)
    cfg.interval_seconds = 60

    service.start(cfg)
    deadline = time.monotonic() + 2.0
    while fetch.call_count < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    service.stop()

    assert fetch.call_count >= 1


def test_start_refuses_when_stop_join_times_out(tmp_path, mocker):
    """stop join 超时后旧线程仍存活时，start 应拒绝且不得清除 stop。"""
    mocker.patch("core.email_monitor.service._JOIN_TIMEOUT_SECONDS", 0.05)

    entered = threading.Event()
    release = threading.Event()
    fetch_calls = {"n": 0}

    def blocking_fetch(_cfg: MonitorConfig):
        fetch_calls["n"] += 1
        entered.set()
        # 模拟卡住的 IMAP：忽略 stop，直到测试主动释放
        release.wait(timeout=10.0)
        return iter([])

    service = EmailMonitorService(
        dedup_path=tmp_path / "seen.json",
        fetch_attachments=blocking_fetch,
    )
    cfg = _minimal_config(tmp_path / "dl")
    (tmp_path / "dl").mkdir()
    cfg.interval_seconds = 60

    service.start(cfg)
    assert entered.wait(timeout=2.0)

    service.stop()
    assert service.is_running()
    assert service._stop_event.is_set()
    hung_thread = service._thread

    with pytest.raises(RuntimeError, match="仍在运行"):
        service.start(cfg)

    # 拒绝 start 后不得清 stop，且不得另起新线程
    assert service._stop_event.is_set()
    assert service._thread is hung_thread
    assert hung_thread is not None and hung_thread.is_alive()
    assert fetch_calls["n"] == 1

    release.set()
    hung_thread.join(timeout=2.0)
    service.stop()
    assert not service.is_running()
