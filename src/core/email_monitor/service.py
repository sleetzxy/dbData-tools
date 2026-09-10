"""邮件附件监控后台轮询服务。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Optional

from core.email_monitor.dedup import DedupStore, make_dedup_key
from core.email_monitor.imap_client import iter_matching_attachments
from core.email_monitor.models import MonitorConfig
from core.email_monitor.saver import save_attachment_bytes

# 连续 tick 失败达到该阈值后触发致命回调并停止
_MAX_CONSECUTIVE_FAILURES = 5

# stop() 等待后台线程退出的超时（避免长时间卡住 UI）
_JOIN_TIMEOUT_SECONDS = 2.0

# 默认去重文件路径
_DEFAULT_DEDUP_PATH = Path.home() / ".dbdata_tools" / "email_monitor_seen.json"

FetchAttachmentsFn = Callable[
    [MonitorConfig],
    Iterable[tuple[str, str, bytes]],
]
OnFatalFn = Callable[[str], None]


class EmailMonitorService:
    """在后台线程中按间隔轮询 IMAP 并下载匹配附件。

    :param dedup_path: 去重 JSON 路径；默认 ``~/.dbdata_tools/email_monitor_seen.json``。
    :param on_fatal: 连续失败达阈值时的可选回调（单次调用）。
    :param logger: 可选日志记录器。
    :param fetch_attachments: 可选注入的附件拉取函数（便于单测）。
    """

    def __init__(
        self,
        dedup_path: Optional[Path] = None,
        on_fatal: Optional[OnFatalFn] = None,
        logger: Optional[logging.Logger] = None,
        fetch_attachments: Optional[FetchAttachmentsFn] = None,
    ) -> None:
        self._dedup_path = (
            Path(dedup_path) if dedup_path is not None else _DEFAULT_DEDUP_PATH
        )
        self._on_fatal = on_fatal
        self._logger = logger or logging.getLogger(__name__)
        self._fetch = fetch_attachments or iter_matching_attachments

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """服务后台线程是否仍在运行。"""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, config_snapshot: MonitorConfig) -> None:
        """启动监控：立即执行首轮 tick，再按间隔循环。

        若已在运行（含 stop 超时仍存活的旧线程）则拒绝启动，
        且不得清除 ``_stop_event``，以免复活旧轮询线程。

        :param config_snapshot: 本轮监控使用的配置快照。
        :raises RuntimeError: 旧后台线程仍存活时拒绝启动。
        """
        with self._lock:
            if self.is_running():
                # 旧线程仍存活时绝不能 clear stop，否则会双线程轮询
                msg = "邮件监控线程仍在运行，拒绝 start（请待旧线程退出后再启动）"
                self._logger.error(msg)
                raise RuntimeError(msg)

            # 仅在确认无存活线程后才允许清除停止信号并启动新线程
            self._stop_event.clear()
            self._consecutive_failures = 0
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(config_snapshot,),
                name="EmailMonitorService",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """请求协作停止并等待后台线程结束。

        若 join 超时后线程仍存活，保留 ``_thread`` 引用且保持
        ``is_running()`` 为 True，避免后续 start 误清 stop 信号。
        """
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            if self._thread is not thread:
                return
            if thread is not None and thread.is_alive():
                self._logger.warning(
                    "邮件监控线程在 stop 超时后仍存活，保留引用且不视为已停止"
                )
                return
            self._thread = None

    def _run_loop(self, cfg: MonitorConfig) -> None:
        """后台循环：tick → 按 interval 等待，直到 stop 或致命失败。"""
        dedup = DedupStore(self._dedup_path)
        interval = max(1, int(cfg.interval_seconds))

        while not self._stop_event.is_set():
            try:
                self._tick(cfg, dedup)
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                self._logger.exception(
                    "邮件监控单轮失败（连续 %s/%s）: %s",
                    self._consecutive_failures,
                    _MAX_CONSECUTIVE_FAILURES,
                    exc,
                )
                if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    message = (
                        f"邮件监控连续失败 {_MAX_CONSECUTIVE_FAILURES} 次，已自动停止："
                        f"{exc}"
                    )
                    self._stop_event.set()
                    if self._on_fatal is not None:
                        try:
                            self._on_fatal(message)
                        except Exception:
                            self._logger.exception("on_fatal 回调执行失败")
                    break

            # 使用 Event.wait 以便 stop 时快速退出，无需睡满整个间隔
            if self._stop_event.wait(timeout=interval):
                break

    def _tick(self, cfg: MonitorConfig, dedup: DedupStore) -> None:
        """执行单轮拉取、去重与落盘。

        单附件失败不中断本轮其余附件；整轮拉取异常向上抛出由循环计数。

        :param cfg: 配置快照。
        :param dedup: 去重存储。
        """
        attachments = self._fetch(cfg)
        # 兼容一次性返回 iterable / iterator
        if not isinstance(attachments, Iterator):
            attachments = iter(attachments)

        download_dir = Path(cfg.download_dir)
        saved = 0
        skipped = 0

        for uid, filename, payload in attachments:
            if self._stop_event.is_set():
                break

            key = make_dedup_key(cfg.account, uid, filename)
            if dedup.has(key):
                skipped += 1
                continue

            try:
                save_attachment_bytes(download_dir, filename, payload)
                dedup.add(key)
                saved += 1
            except Exception:
                self._logger.exception(
                    "保存附件失败，跳过: uid=%s filename=%s",
                    uid,
                    filename,
                )

        self._logger.info(
            "邮件监控本轮完成：保存 %s，跳过(去重) %s",
            saved,
            skipped,
        )
