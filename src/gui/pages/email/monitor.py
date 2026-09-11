"""邮件附件监控页面。"""

from __future__ import annotations

import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox
from typing import Any, Deque, Optional

from core.email_monitor import EmailMonitorService, MonitorConfig, validate_monitor_config
from core.email_monitor.filters import normalize_extensions, parse_sender_list
from core.email_monitor.imap_client import test_connection
from core.email_monitor.large_attachment import format_byte_size
from gui.base import BaseToolPage
from gui.components import PathSelector
from gui.utils.gui_utils import safe_configure
from gui.widgets.buttons import PrimaryButton, StyledButton
from gui.widgets.entries import StyledEntry
from gui.widgets.labels import StyledLabel, TitleLabel
from utils.credential_crypto import decrypt_secret, encrypt_secret

# 腾讯企业邮默认 IMAP
_DEFAULT_HOST = "imap.exmail.qq.com"
_DEFAULT_PORT = "993"
_DEFAULT_LOOKBACK = "7"
_DEFAULT_INTERVAL = "600"

# 与日志面板同风格的文本进度条宽度
_ASCII_BAR_WIDTH = 20
_PROGRESS_MARK = "email_dl_progress"


class EmailMonitorPage(BaseToolPage):
    """邮件附件 IMAP 监控页：配置、测试连接、启停后台轮询。

    本页不依赖数据库当前连接，也不展示连接页头；
    主操作走「开始监控 / 停止」，不使用基类一次性 ``run_task``。
    """

    CONFIG_FILE = "~/.dbdata_tools/email_monitor.json"

    def __init__(self, root: Any) -> None:
        self._monitor_service: Optional[EmailMonitorService] = None
        self._is_monitoring = False
        # 进度事件队列：避免单槽合并跨文件丢掉 finished
        self._progress_queue: Deque[tuple[str, int, Optional[int], bool]] = (
            deque()
        )
        self._progress_flush_scheduled = False
        # 当前「正在下载」行；下载完成后清空，避免同名文件覆盖旧行
        self._active_log_progress: Optional[dict[str, Any]] = None
        # 等待落盘回调改写为「已保存」的文件名（与 mark 对应）
        self._awaiting_save_filename: Optional[str] = None
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 邮件监控日志",
        )

    def _on_download_progress(
        self,
        filename: str,
        downloaded: int,
        total: Optional[int],
        finished: bool,
    ) -> None:
        """后台线程进度入口：入队后投递到 UI 线程（跨文件不丢事件）。"""
        self._progress_queue.append((filename, downloaded, total, finished))
        if self._progress_flush_scheduled:
            return
        self._progress_flush_scheduled = True
        delay_ms = 0 if finished else 50
        try:
            self.root.after(delay_ms, self._flush_download_progress)
        except tk.TclError:
            self._progress_flush_scheduled = False

    def _on_attachment_saved(self, filename: str, size: int) -> None:
        """落盘成功：把对应进度行改为「已保存」（投递主线程）。"""
        try:
            self.root.after(
                0,
                lambda f=filename, s=size: self._apply_attachment_saved(f, s),
            )
        except tk.TclError:
            pass

    @staticmethod
    def _build_ascii_bar(ratio: float, width: int = _ASCII_BAR_WIDTH) -> str:
        """生成与 Consolas 日志兼容的文本进度条。"""
        ratio = min(1.0, max(0.0, ratio))
        filled = int(round(ratio * width))
        filled = min(width, max(0, filled))
        return "#" * filled + "-" * (width - filled)

    def _format_progress_message(
        self,
        filename: str,
        downloaded: int,
        total: Optional[int],
        *,
        phase: str,
        started_at: str,
    ) -> str:
        """格式化为与 TextHandler 一致的日志行（无末尾换行）。

        :param phase: ``downloading`` | ``downloaded`` | ``saved``。
        """
        if total and total > 0:
            if phase == "downloading":
                ratio = min(1.0, max(0.0, downloaded / total))
                action = "正在下载"
            else:
                ratio = 1.0
                action = "已保存" if phase == "saved" else "下载完成"
            bar = self._build_ascii_bar(ratio)
            pct = int(round(ratio * 100))
            size_text = (
                f"{format_byte_size(downloaded)} / {format_byte_size(total)}"
            )
            body = f"{action}：{filename} [{bar}] {pct}% {size_text}"
        else:
            size_text = format_byte_size(downloaded)
            if phase == "saved":
                bar = self._build_ascii_bar(1.0)
                body = f"已保存：{filename} [{bar}] {size_text}"
            elif phase == "downloaded":
                bar = self._build_ascii_bar(1.0)
                body = f"下载完成：{filename} [{bar}] {size_text}"
            else:
                bar = self._build_ascii_bar(0.0)
                body = f"正在下载：{filename} [{bar}] 已接收 {size_text}"
        return f"{started_at} - INFO - {body}"

    def _flush_download_progress(self) -> None:
        """在主线程按队列顺序刷新进度行。"""
        self._progress_flush_scheduled = False
        try:
            if not hasattr(self, "text_log") or not self.text_log.winfo_exists():
                self._progress_queue.clear()
                return
        except tk.TclError:
            self._progress_queue.clear()
            return

        while self._progress_queue:
            filename, downloaded, total, finished = self._progress_queue.popleft()
            self._apply_download_progress(
                filename, downloaded, total, finished
            )

        if self._progress_queue and not self._progress_flush_scheduled:
            self._progress_flush_scheduled = True
            try:
                self.root.after(0, self._flush_download_progress)
            except tk.TclError:
                self._progress_flush_scheduled = False

    def _apply_download_progress(
        self,
        filename: str,
        downloaded: int,
        total: Optional[int],
        finished: bool,
    ) -> None:
        """应用单条下载进度（同文件就地更新；换文件新起一行）。"""
        active = self._active_log_progress
        same_file = active is not None and active.get("filename") == filename

        if not same_file:
            started_at = datetime.now().strftime("%H:%M:%S")
            self._active_log_progress = {
                "filename": filename,
                "started_at": started_at,
                "total": total,
                "downloaded": downloaded,
            }
            phase = "downloaded" if finished else "downloading"
            self._write_progress_line(
                self._format_progress_message(
                    filename,
                    downloaded,
                    total,
                    phase=phase,
                    started_at=started_at,
                ),
                replace=False,
            )
            if finished:
                self._awaiting_save_filename = filename
                self._active_log_progress = None
            return

        assert active is not None
        started_at = str(active["started_at"])
        active["downloaded"] = downloaded
        if total is not None:
            active["total"] = total
        effective_total = active.get("total")
        if isinstance(effective_total, int):
            total = effective_total

        phase = "downloaded" if finished else "downloading"
        self._write_progress_line(
            self._format_progress_message(
                filename,
                downloaded,
                total,
                phase=phase,
                started_at=started_at,
            ),
            replace=True,
        )
        if finished:
            self._awaiting_save_filename = filename
            self._active_log_progress = None

    def _apply_attachment_saved(self, filename: str, size: int) -> None:
        """将等待中的进度行改为「已保存」。"""
        try:
            if not hasattr(self, "text_log") or not self.text_log.winfo_exists():
                return
        except tk.TclError:
            return

        started_at = datetime.now().strftime("%H:%M:%S")
        can_replace = (
            self._awaiting_save_filename == filename
            and _PROGRESS_MARK in self.text_log.mark_names()
        )
        if can_replace:
            try:
                start = self.text_log.index(_PROGRESS_MARK)
                existing = self.text_log.get(start, f"{start} lineend")
                parts = existing.split(" - ", 2)
                if parts and len(parts[0]) == 8:
                    started_at = parts[0]
            except tk.TclError:
                pass

        line = self._format_progress_message(
            filename,
            size,
            size,
            phase="saved",
            started_at=started_at,
        )
        self._write_progress_line(line, replace=can_replace)
        if self._awaiting_save_filename == filename:
            self._awaiting_save_filename = None

    def _write_progress_line(self, line: str, *, replace: bool) -> None:
        """追加或就地替换当前进度日志行。"""
        text = self.text_log
        try:
            text.configure(state="normal")
            if replace and _PROGRESS_MARK in text.mark_names():
                start = text.index(_PROGRESS_MARK)
                text.delete(start, f"{start} lineend")
                text.insert(start, line, "INFO")
                text.mark_set(_PROGRESS_MARK, start)
                text.mark_gravity(_PROGRESS_MARK, tk.LEFT)
            else:
                text.insert(tk.END, line + "\n", "INFO")
                start = text.index("end-2c linestart")
                text.mark_set(_PROGRESS_MARK, start)
                text.mark_gravity(_PROGRESS_MARK, tk.LEFT)
            text.see(tk.END)
            text.configure(state="disabled")
        except tk.TclError:
            try:
                text.configure(state="disabled")
            except tk.TclError:
                pass

    def setup_left_panel_content(self, parent: Any) -> None:
        """构建左侧配置表单与操作按钮（不展示数据库连接页头）。"""
        title = TitleLabel(parent, text="邮件附件监控")
        title.pack(anchor="w", pady=(0, 12))

        self.host_entry = self._labeled_entry(
            parent, "IMAP 主机", _DEFAULT_HOST
        )
        self.port_entry = self._labeled_entry(
            parent, "端口", _DEFAULT_PORT
        )

        self.use_ssl_var = tk.BooleanVar(value=True)
        self.ssl_checkbox = self.ctk.CTkCheckBox(
            parent,
            text="使用 SSL",
            variable=self.use_ssl_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        )
        self.ssl_checkbox.pack(anchor="w", pady=(0, 15))

        self.account_entry = self._labeled_entry(parent, "账号", "")
        self.password_entry = self._labeled_entry(
            parent, "密码 / 授权码", "", show="●"
        )

        StyledLabel(parent, text="发件人列表（逗号或换行）").pack(
            anchor="w", pady=(0, 3)
        )
        self.senders_box = self.ctk.CTkTextbox(
            parent,
            height=72,
            font=("Microsoft YaHei", 10),
            fg_color=self.idea_dark_colors["gray_button"],
            text_color=self.idea_dark_colors["gray_button_fg"],
            border_width=1,
            border_color=self.idea_dark_colors["gray_button_border"],
            corner_radius=5,
            wrap="word",
        )
        self.senders_box.pack(anchor="w", fill="x", pady=(0, 15))

        self.download_selector = PathSelector(
            parent, label_text="下载目录", mode="folder"
        )
        self.download_selector.pack(fill="x", pady=(0, 15))

        self.extensions_entry = self._labeled_entry(
            parent,
            "扩展名白名单（如 .csv,.xlsx,.zip）",
            "",
        )
        self.lookback_entry = self._labeled_entry(
            parent, "最近 N 天", _DEFAULT_LOOKBACK
        )
        self.interval_entry = self._labeled_entry(
            parent, "轮询间隔（秒）", _DEFAULT_INTERVAL
        )

        # 操作按钮：等宽一行，主操作为「开始监控」
        btn_row = self.ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(anchor="w", fill="x", pady=(8, 4))
        btn_row.grid_columnconfigure((0, 1, 2), weight=1, uniform="email_ops")

        self.test_button = StyledButton(
            btn_row,
            text="测试连接",
            command=self._on_test_connection,
            height=36,
            font=("Microsoft YaHei", 11),
        )
        self.test_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.start_button = PrimaryButton(
            btn_row,
            text="开始监控",
            command=self._on_start_monitor,
            height=36,
        )
        self.start_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self.stop_button = StyledButton(
            btn_row,
            text="停止",
            command=self._on_stop_monitor,
            height=36,
            font=("Microsoft YaHei", 11),
        )
        self.stop_button.grid(row=0, column=2, sticky="ew")
        safe_configure(self.stop_button, state="disabled")

    def _labeled_entry(
        self,
        parent: Any,
        label: str,
        default: str,
        *,
        show: Optional[str] = None,
    ) -> StyledEntry:
        """创建带标签的输入框并预填默认值。"""
        StyledLabel(parent, text=label).pack(anchor="w", pady=(0, 3))
        entry = StyledEntry(parent, show=show) if show else StyledEntry(parent)
        if default:
            entry.insert(0, default)
        entry.pack(anchor="w", fill="x", pady=(0, 15))
        return entry

    @staticmethod
    def _set_entry(entry: StyledEntry, value: str) -> None:
        """替换 Entry 全部内容。"""
        entry.delete(0, tk.END)
        if value:
            entry.insert(0, value)

    def get_config_dict(self) -> dict[str, Any]:
        """返回可落盘配置；密码经 encrypt_secret 混淆。"""
        password = self.password_entry.get()
        return {
            "host": self.host_entry.get().strip(),
            "port": self.port_entry.get().strip(),
            "use_ssl": bool(self.use_ssl_var.get()),
            "account": self.account_entry.get().strip(),
            "password": encrypt_secret(password) if password else "",
            "senders": self.senders_box.get("1.0", tk.END).strip(),
            "download_dir": self.download_selector.get_path(),
            "extensions": self.extensions_entry.get().strip(),
            "lookback_days": self.lookback_entry.get().strip(),
            "interval_seconds": self.interval_entry.get().strip(),
        }

    def apply_config(self, config: dict) -> None:
        """应用配置；密码优先解密，失败或非 enc:v1 时按明文兼容。"""
        host = str(config.get("host") or _DEFAULT_HOST).strip() or _DEFAULT_HOST
        port = str(config.get("port") or _DEFAULT_PORT).strip() or _DEFAULT_PORT
        lookback = (
            str(config.get("lookback_days") or _DEFAULT_LOOKBACK).strip()
            or _DEFAULT_LOOKBACK
        )
        interval = (
            str(config.get("interval_seconds") or _DEFAULT_INTERVAL).strip()
            or _DEFAULT_INTERVAL
        )

        self._set_entry(self.host_entry, host)
        self._set_entry(self.port_entry, port)
        self.use_ssl_var.set(bool(config.get("use_ssl", True)))
        self._set_entry(self.account_entry, str(config.get("account") or ""))
        self._set_entry(self.password_entry, self._decrypt_password(config.get("password")))
        self.senders_box.delete("1.0", tk.END)
        senders = config.get("senders", "")
        if isinstance(senders, list):
            senders = "\n".join(str(s) for s in senders if str(s).strip())
        self.senders_box.insert("1.0", str(senders or ""))
        download_dir = str(config.get("download_dir") or "")
        if download_dir:
            self.download_selector.set_path(download_dir)
        extensions = config.get("extensions", "")
        if isinstance(extensions, list):
            extensions = ",".join(str(e) for e in extensions if str(e).strip())
        self._set_entry(self.extensions_entry, str(extensions or ""))
        self._set_entry(self.lookback_entry, lookback)
        self._set_entry(self.interval_entry, interval)

    @staticmethod
    def _decrypt_password(stored: Any) -> str:
        """解密落盘密码；非 enc:v1 或解密失败时按明文兼容。"""
        raw = str(stored or "")
        if not raw:
            return ""
        try:
            return decrypt_secret(raw)
        except Exception:
            return raw

    def execute_task(self) -> dict[str, Any]:
        """基类抽象方法占位：本页请使用「开始监控」按钮。"""
        return {"success": True, "error": "请使用开始监控按钮"}

    def _build_monitor_config(self) -> MonitorConfig:
        """从表单构建 MonitorConfig 快照。"""
        port_text = self.port_entry.get().strip() or _DEFAULT_PORT
        lookback_text = self.lookback_entry.get().strip() or _DEFAULT_LOOKBACK
        interval_text = self.interval_entry.get().strip() or _DEFAULT_INTERVAL
        try:
            port = int(port_text)
        except ValueError:
            port = 0
        try:
            lookback_days = int(lookback_text)
        except ValueError:
            lookback_days = 0
        try:
            interval_seconds = int(interval_text)
        except ValueError:
            interval_seconds = 0

        senders_raw = self.senders_box.get("1.0", tk.END)
        extensions_raw = self.extensions_entry.get()
        return MonitorConfig(
            host=self.host_entry.get().strip() or _DEFAULT_HOST,
            port=port,
            use_ssl=bool(self.use_ssl_var.get()),
            account=self.account_entry.get().strip(),
            password=self.password_entry.get(),
            senders=sorted(parse_sender_list(senders_raw)),
            download_dir=self.download_selector.get_path().strip(),
            extensions=sorted(normalize_extensions(extensions_raw)),
            lookback_days=lookback_days,
            interval_seconds=interval_seconds,
        )

    def _set_monitoring_ui(self, monitoring: bool) -> None:
        """启停互斥：更新按钮可用状态。"""
        self._is_monitoring = monitoring
        start_state = "disabled" if monitoring else "normal"
        stop_state = "normal" if monitoring else "disabled"
        try:
            if self.start_button.winfo_exists():
                safe_configure(self.start_button, state=start_state)
            if self.stop_button.winfo_exists():
                safe_configure(self.stop_button, state=stop_state)
        except tk.TclError:
            pass

    def _ensure_service(self) -> EmailMonitorService:
        """懒创建监控服务，日志与下载进度接到本页右侧面板。"""
        if self._monitor_service is None:
            self._monitor_service = EmailMonitorService(
                on_fatal=self._on_monitor_fatal,
                logger=self.logger,
                on_download_progress=self._on_download_progress,
                on_attachment_saved=self._on_attachment_saved,
            )
        return self._monitor_service

    def _on_test_connection(self) -> None:
        """后台线程测试 IMAP 连接，结果回到 UI 线程弹窗与日志。"""
        if self._is_monitoring:
            messagebox.showwarning("测试连接", "监控运行中，请先停止后再测试连接")
            return

        cfg = self._build_monitor_config()
        if not cfg.host or not cfg.account or not cfg.password:
            messagebox.showwarning(
                "测试连接", "请至少填写 IMAP 主机、账号与密码后再测试"
            )
            return

        self.save_current_config()
        if self.logger:
            self.logger.debug("配置已自动保存")

        safe_configure(self.test_button, state="disabled")
        if self.logger:
            self.logger.info("正在测试 IMAP 连接…")

        def worker() -> None:
            error: Optional[str] = None
            try:
                test_connection(cfg)
            except Exception as exc:
                error = str(exc)

            def update_ui() -> None:
                safe_configure(self.test_button, state="normal")
                if error:
                    if self.logger:
                        self.logger.error(f"连接测试失败: {error}")
                    messagebox.showerror("测试连接", f"连接失败：{error}")
                else:
                    if self.logger:
                        self.logger.info("IMAP 连接测试成功")
                    messagebox.showinfo("测试连接", "连接成功")

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True, name="EmailMonitorTest").start()

    def _on_start_monitor(self) -> None:
        """校验配置后启动后台监控。"""
        if self._is_monitoring:
            return

        cfg = self._build_monitor_config()
        errors = validate_monitor_config(cfg)
        if errors:
            messagebox.showwarning("无法开始监控", "\n".join(errors))
            if self.logger:
                self.logger.warning("配置校验未通过: %s", "; ".join(errors))
            return

        self.save_current_config()
        if self.logger:
            self.logger.debug("配置已自动保存")
        service = self._ensure_service()
        try:
            service.start(cfg)
        except Exception as exc:
            if self.logger:
                self.logger.exception("启动监控失败")
            messagebox.showerror("开始监控", f"启动失败：{exc}")
            return

        self._set_monitoring_ui(True)
        if self.logger:
            self.logger.info(
                "已开始监控：%s@%s，间隔 %s 秒",
                cfg.account,
                cfg.host,
                cfg.interval_seconds,
            )

    def _on_stop_monitor(self) -> None:
        """停止监控。"""
        if not self._is_monitoring and (
            self._monitor_service is None or not self._monitor_service.is_running()
        ):
            return

        if self.logger:
            self.logger.info("正在停止邮件监控…")
        self.stop_monitor_if_running(user_initiated=True)

    def _on_monitor_fatal(self, message: str) -> None:
        """Service 致命失败回调（可能在后台线程）；切回 UI 线程处理。"""

        def update_ui() -> None:
            if self.logger:
                self.logger.error(message)
            self._set_monitoring_ui(False)
            messagebox.showerror("监控已停止", message)

        try:
            self.root.after(0, update_ui)
        except Exception:
            # 应用关闭过程中 after 可能不可用
            pass

    def stop_monitor_if_running(self, *, user_initiated: bool = False) -> None:
        """若监控仍在运行则停止；供停止按钮与主壳关闭调用。

        :param user_initiated: True 表示用户主动点停止（仅影响日志文案）。
        """
        service = self._monitor_service
        was_running = self._is_monitoring or (
            service is not None and service.is_running()
        )
        if service is not None:
            try:
                service.stop()
            except Exception:
                if self.logger:
                    self.logger.exception("停止邮件监控时出错")

        self._set_monitoring_ui(False)
        if was_running and self.logger and user_initiated:
            self.logger.info("邮件监控已停止")
        elif was_running and self.logger and not user_initiated:
            self.logger.info("应用关闭，邮件监控已停止")
