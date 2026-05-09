"""桌面应用入口。

仅负责创建 customtkinter 根窗口、装配 :class:`MainApplication` 并进入事件循环；
具体页面装配与 tooltip 等实现位于 :mod:`gui.app` 与 :mod:`gui.widgets.tooltip`。
"""

from __future__ import annotations

import logging
from tkinter import messagebox

from gui.app import MainApplication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """启动 GUI。"""
    try:
        import customtkinter as ctk

        root = ctk.CTk()
        app = MainApplication(root)

        # 设置窗口图标（如果有的话）
        try:
            root.iconbitmap("icon.ico")
        except Exception:
            pass

        root.mainloop()
    except Exception as e:
        logger.error(f"应用程序错误: {e}", exc_info=True)
        messagebox.showerror(
            "应用程序错误", f"程序遇到错误:\n{str(e)}\n\n详细信息请查看日志文件"
        )


if __name__ == "__main__":
    main()
