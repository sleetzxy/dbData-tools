import tkinter as tk

def safe_configure(widget, **kwargs):
    """安全地更新 Tk/CTk 控件属性，避免已销毁控件导致的 TclError"""
    try:
        if widget is not None and widget.winfo_exists():
            widget.configure(**kwargs)
    except tk.TclError:
        # 控件可能在一次 UI 切换或缩放回调中销毁
        pass