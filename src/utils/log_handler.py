import tkinter as tk
import logging
from typing import Any


class TextHandler(logging.Handler):
    """
    自定义日志处理器，将日志输出到tkinter文本控件
    增强版：处理文本控件状态，确保线程安全
    """

    def __init__(self, text_widget: Any):
        super().__init__()
        self.text_widget = text_widget
        # 设置文本控件初始状态
        self.text_widget.configure(state='normal')

        # 读取控件默认前景色，保证与现有 UI 的 fg 保持一致
        default_fg = self.text_widget.cget('fg') if hasattr(self.text_widget, 'cget') else "#d4d4d4"
        # 统一深色风格的配色（更柔和）
        # INFO：沿用默认前景色，WARNING：琥珀色，ERROR：主题中的红色，DEBUG：柔和蓝色
        self.text_widget.tag_config('INFO', foreground=default_fg)
        self.text_widget.tag_config('WARNING', foreground='#E0AF68')  # 琥珀色，避免刺眼的纯黄
        self.text_widget.tag_config('ERROR', foreground='#F44336')    # 与 UI 主题一致的红色
        self.text_widget.tag_config('DEBUG', foreground='#9CDCFE')    # 柔和的蓝色

    def emit(self, record: logging.LogRecord) -> None:
        """重写emit方法，确保线程安全"""
        try:
            msg = self.format(record)
            self.text_widget.after(0, self._append_log, msg, record.levelname)
        except Exception as e:
            print(f"日志输出失败: {e}")

    def _append_log(self, msg: str, level: str) -> None:
        """实际追加日志到文本控件"""
        try:
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n', level)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state='disabled')
        except Exception as e:
            print(f"追加日志失败: {e}")


def setup_logger(text_widget: Any, logger: logging):
    """
    设置日志输出到GUI文本控件

    参数:
        text_widget: tkinter的文本控件
        logger_name: 日志记录器名称
    """

    # 清除现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    # 添加GUI处理器
    if text_widget:
        gui_handler = TextHandler(text_widget)
        # 更紧凑的时间格式，更适合面板展示
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        gui_handler.setFormatter(formatter)
        logger.addHandler(gui_handler)
    return logger
