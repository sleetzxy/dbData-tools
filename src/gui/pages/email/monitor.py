"""邮件附件监控页面。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, Optional

from core.email_monitor import EmailMonitorService, MonitorConfig, validate_monitor_config
from core.email_monitor.filters import normalize_extensions, parse_sender_list
from core.email_monitor.imap_client import test_connection
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


class EmailMonitorPage(BaseToolPage):
    """邮件附件 IMAP 监控页：配置、测试连接、启停后台轮询。

    本页不依赖数据库当前连接，也不展示连接页头；
    主操作走「开始监控 / 停止」，不使用基类一次性 ``run_task``。
    """

    CONFIG_FILE = "~/.dbdata_tools/email_monitor.json"

    def __init__(self, root: Any) -> None:
        self._monitor_service: Optional[EmailMonitorService] = None
        self._is_monitoring = False
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 邮件监控日志",
        )

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
        """懒创建监控服务，日志接到本页右侧面板。"""
        if self._monitor_service is None:
            self._monitor_service = EmailMonitorService(
                on_fatal=self._on_monitor_fatal,
                logger=self.logger,
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
            self.logger.info("配置已自动保存")

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
            self.logger.info("配置已自动保存")
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
