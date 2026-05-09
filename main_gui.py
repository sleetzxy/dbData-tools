"""桌面应用入口。

仅负责创建 customtkinter 根窗口、装配 :class:`MainApplication` 并进入事件循环；
具体页面装配与 tooltip 等实现位于 :mod:`gui.app` 与 :mod:`gui.widgets.tooltip`。
"""

from __future__ import annotations

import logging
from tkinter import TclError, messagebox

from gui.app import MainApplication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """启动 GUI。

    在根窗口上装配主界面并进入事件循环。图标文件缺失或无法加载时仅跳过图标设置。
    其余启动期异常会记入日志并弹出错误对话框。
    """
    try:
        import customtkinter as ctk

        root = ctk.CTk()
        MainApplication(root)

        # 设置窗口图标（如果有的话）
        try:
            root.iconbitmap("icon.ico")
        except (OSError, TclError):
            pass

        root.mainloop()
    except Exception as e:
        logger.error("应用程序错误: %s", e, exc_info=True)
        messagebox.showerror(
            "应用程序错误",
            f"程序遇到错误:\n{e!s}\n\n详细信息请查看日志文件",
        )


if __name__ == "__main__":
    main()
