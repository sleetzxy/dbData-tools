"""邮件附件监控后台轮询服务。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Optional

from core.email_monitor.dedup import DedupStore, make_dedup_key
from core.email_monitor.imap_client import iter_matching_attachments
from core.email_monitor.large_attachment import DownloadProgressFn
from core.email_monitor.models import MonitorConfig
from core.email_monitor.saver import save_attachment_bytes

# 连续 tick 失败达到该阈值后触发致命回调并停止
_MAX_CONSECUTIVE_FAILURES = 5

# stop() 等待后台线程退出的超时（避免长时间卡住 UI）
_JOIN_TIMEOUT_SECONDS = 2.0

# 默认去重文件路径
_DEFAULT_DEDUP_PATH = Path.home() / ".dbdata_tools" / "email_monitor_seen.json"

FetchAttachmentsFn = Callable[
    ...,
    Iterable[tuple[str, str, bytes]],
]
OnFatalFn = Callable[[str], None]
ShouldSkipFn = Callable[[str, str], bool]
# 落盘成功：(filename, size_bytes)
OnSavedFn = Callable[[str, int], None]


class EmailMonitorService:
    """在后台线程中按间隔轮询 IMAP 并下载匹配附件。

    :param dedup_path: 去重 JSON 路径；默认 ``~/.dbdata_tools/email_monitor_seen.json``。
    :param on_fatal: 连续失败达阈值时的可选回调（单次调用）。
    :param logger: 可选日志记录器。
    :param fetch_attachments: 可选注入的附件拉取函数（便于单测）。
    :param on_download_progress: 可选下载进度回调（超大附件分块下载时触发）。
    :param on_attachment_saved: 可选落盘成功回调（用于把进度行改为「已保存」）。
    """

    def __init__(
        self,
        dedup_path: Optional[Path] = None,
        on_fatal: Optional[OnFatalFn] = None,
        logger: Optional[logging.Logger] = None,
        fetch_attachments: Optional[FetchAttachmentsFn] = None,
        on_download_progress: Optional[DownloadProgressFn] = None,
        on_attachment_saved: Optional[OnSavedFn] = None,
    ) -> None:
        self._dedup_path = (
            Path(dedup_path) if dedup_path is not None else _DEFAULT_DEDUP_PATH
        )
        self._on_fatal = on_fatal
        self._on_download_progress = on_download_progress
        self._on_attachment_saved = on_attachment_saved
        self._logger = logger or logging.getLogger(__name__)
        if fetch_attachments is not None:
            self._fetch = fetch_attachments
        else:
            # 把服务日志传入 IMAP 扫描，便于 GUI 右侧看到诊断信息
            def _default_fetch(
                cfg: MonitorConfig,
                should_skip: Optional[ShouldSkipFn] = None,
            ) -> Iterable[tuple[str, str, bytes]]:
                return iter_matching_attachments(
                    cfg,
                    log=self._logger,
                    should_skip=should_skip,
                    on_download_progress=self._emit_progress,
                )

            self._fetch = _default_fetch

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._lock = threading.Lock()
        # 本轮已展示过下载进度的文件；落盘时走回调改「已保存」，避免重复 INFO
        self._progress_seen_files: set[str] = set()

    def _emit_progress(
        self,
        filename: str,
        downloaded: int,
        total: Optional[int],
        finished: bool,
    ) -> None:
        """转发下载进度；回调异常不影响下载主流程。"""
        self._progress_seen_files.add(filename)
        if self._on_download_progress is None:
            return
        try:
            self._on_download_progress(filename, downloaded, total, finished)
        except Exception:
            self._logger.exception("下载进度回调失败")

    def _emit_saved(self, filename: str, size: int) -> None:
        """落盘成功通知：有进度 UI 则回调，否则打 INFO。"""
        if (
            filename in self._progress_seen_files
            and self._on_attachment_saved is not None
        ):
            try:
                self._on_attachment_saved(filename, size)
            except Exception:
                self._logger.exception("落盘回调失败")
            return
        self._logger.info("已保存：%s（%s 字节）", filename, size)

    def _call_fetch(
        self,
        cfg: MonitorConfig,
        should_skip: ShouldSkipFn,
    ) -> Iterable[tuple[str, str, bytes]]:
        """调用 fetch；兼容只接受 cfg 的旧注入函数。"""
        try:
            return self._fetch(cfg, should_skip=should_skip)
        except TypeError:
            return self._fetch(cfg)

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
        download_dir = Path(cfg.download_dir)
        saved = 0
        skipped = 0
        self._progress_seen_files.clear()

        def should_skip(uid: str, filename: str) -> bool:
            return dedup.has(make_dedup_key(cfg.account, uid, filename))

        # 去重判断下传给 fetch，超大附件可在 HTTP 下载前跳过
        attachments = self._call_fetch(cfg, should_skip)
        # 兼容一次性返回 iterable / iterator
        if not isinstance(attachments, Iterator):
            attachments = iter(attachments)

        for uid, filename, payload in attachments:
            if self._stop_event.is_set():
                break

            key = make_dedup_key(cfg.account, uid, filename)
            # 防御性再检查（自定义 fetch 可能未接 should_skip）
            if dedup.has(key):
                skipped += 1
                continue

            try:
                save_attachment_bytes(download_dir, filename, payload)
                dedup.add(key)
                saved += 1
                self._emit_saved(filename, len(payload))
            except Exception:
                self._logger.exception(
                    "保存附件失败，跳过: uid=%s filename=%s",
                    uid,
                    filename,
                )

        # 明细汇总已由 IMAP 扫描输出；此处仅在有落盘时补一句，避免重复啰嗦
        if saved:
            self._logger.debug("本轮落盘 %s 个附件", saved)
        elif skipped:
            self._logger.debug("本轮落盘前再跳过(去重) %s", skipped)
