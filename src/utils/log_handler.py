"""将 ``logging`` 输出桥接到 Tkinter 文本类控件的 Handler 与装配函数。"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any


class TextHandler(logging.Handler):
    """把日志记录写入 Tkinter 文本控件，并用 ``after`` 在主线程追加内容。"""

    def __init__(self, text_widget: Any) -> None:
        """创建处理器并配置按级别区分的文本标签颜色。

        :param text_widget: 支持 ``configure``、``cget``、``tag_config``、
            ``after``、``insert``、``see`` 的文本控件（含部分第三方封装）。
        """
        super().__init__()
        self.text_widget = text_widget
        # 设置文本控件初始状态
        self.text_widget.configure(state="normal")

        # 读取控件默认前景色，保证与现有 UI 的 fg 保持一致
        default_fg = (
            self.text_widget.cget("fg")
            if hasattr(self.text_widget, "cget")
            else "#d4d4d4"
        )
        # 统一深色风格的配色（更柔和）
        # INFO：沿用默认前景色，WARNING：琥珀色，ERROR：主题中的红色，DEBUG：柔和蓝色
        self.text_widget.tag_config("INFO", foreground=default_fg)
        self.text_widget.tag_config(
            "WARNING", foreground="#E0AF68"
        )  # 琥珀色，避免刺眼的纯黄
        self.text_widget.tag_config(
            "ERROR", foreground="#F44336"
        )  # 与 UI 主题一致的红色
        self.text_widget.tag_config("DEBUG", foreground="#9CDCFE")  # 柔和的蓝色

    def emit(self, record: logging.LogRecord) -> None:
        """格式化记录并调度到主线程追加文本。

        :param record: 当前日志记录。
        """
        try:
            msg = self.format(record)
            self.text_widget.after(0, self._append_log, msg, record.levelname)
        except (KeyError, TypeError, ValueError, tk.TclError) as e:
            print(f"日志输出失败: {e}")

    def _append_log(self, msg: str, level: str) -> None:
        """在 UI 线程中向控件尾部插入一行日志。

        :param msg: 已格式化的日志文本。
        :param level: 日志级别名称，用作 Tk 文本标签。
        """
        try:
            self.text_widget.configure(state="normal")
            self.text_widget.insert(tk.END, msg + "\n", level)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state="disabled")
        except tk.TclError as e:
            print(f"追加日志失败: {e}")


def setup_logger(text_widget: Any, logger: logging.Logger) -> logging.Logger:
    """将已有记录器重绑为仅使用 GUI ``TextHandler``（先移除旧处理器）。

    :param text_widget: 可为 ``None``；非空则挂载 :class:`TextHandler`。
    :param logger: 待装配的记录器实例。
    :return: 与入参相同的记录器实例，便于链式赋值。
    """
    # 清除现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    # 添加GUI处理器
    if text_widget:
        gui_handler = TextHandler(text_widget)
        # 更紧凑的时间格式，更适合面板展示
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )
        gui_handler.setFormatter(formatter)
        logger.addHandler(gui_handler)
    return logger
