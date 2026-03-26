import tkinter as tk

def style_tk_scrollbar(scrollbar, colors):
    """统一 Tk 滚动条样式（例如 ScrolledText 的 vbar）。"""
    if not scrollbar:
        return
    try:
        scrollbar.configure(
            troughcolor=colors.get("scrollbar_bg", "#2d2d2d"),
            background=colors.get("scrollbar_button", "#5c5f62"),
            activebackground=colors.get("scrollbar_hover", "#6c6f72"),
            relief="flat",
            borderwidth=0,
            width=10,
        )
    except tk.TclError:
        # 某些平台可能不支持上述样式属性
        pass