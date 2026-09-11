import tkinter as tk
from tkinter import scrolledtext

import customtkinter as ctk

from gui.styling.styles import style_tk_scrollbar
from gui.styling.themes import get_idea_dark_colors


class ScrollableFrame(ctk.CTkFrame):
    """左侧可滚动面板。

    首次塞入大量控件时会对 ``<Configure>`` 做防抖，并在建页期间冻结
    滚动条显隐，避免滚动条反复 pack/forget 造成一卡一卡。
    """

    # Configure 防抖间隔（毫秒）
    _SCROLL_DEBOUNCE_MS = 50

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        super().__init__(master, **kwargs)

        self.pack(fill="both", expand=True, padx=0, pady=0)

        colors = get_idea_dark_colors()
        self._scroll_after_id = None
        self._scroll_frozen = False

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            bg=colors.get("sidebar_bg", "#252526"),
        )

        self.v_scrollbar = ctk.CTkScrollbar(
            self, orientation="vertical", command=self.canvas.yview
        )

        try:
            self.v_scrollbar.configure(
                fg_color=colors.get("scrollbar_bg", "#2d2d2d"),
                button_color=colors.get("scrollbar_button", "#5c5f62"),
                button_hover_color=colors.get("scrollbar_hover", "#6c6f72"),
            )
        except Exception:
            pass

        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        # 滚动条始终占位，避免显隐时画布宽度抖动引发布局抖动
        self.canvas.pack(side="left", fill="both", expand=True)
        self.v_scrollbar.pack(side="right", fill="y")

        self.outer_content = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self.window_id = self.canvas.create_window(
            (0, 0), window=self.outer_content, anchor="nw"
        )

        self.inner_content = ctk.CTkFrame(self.outer_content, fg_color="transparent")
        self.inner_content.pack(fill="both", expand=True, padx=20, pady=15)

        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.outer_content.bind("<Configure>", lambda e: self.schedule_update_scroll())
        self.inner_content.bind("<Configure>", lambda e: self.schedule_update_scroll())
        self.bind("<Configure>", lambda e: self.schedule_update_scroll())
        self.after(self._SCROLL_DEBOUNCE_MS, self.update_scroll)

        self._wheel_bound_all = False
        self._content_overflows = False
        # 进入面板时临时 bind_all，离开即解除；滚轮处理里再判断指针是否仍在面板内
        try:
            self.bind("<Enter>", self._on_panel_enter, add="+")
            self.bind("<Leave>", self._on_panel_leave, add="+")
            self.outer_content.bind("<Enter>", self._on_panel_enter, add="+")
            self.outer_content.bind("<Leave>", self._on_panel_leave, add="+")
            self.inner_content.bind("<Enter>", self._on_panel_enter, add="+")
            self.inner_content.bind("<Leave>", self._on_panel_leave, add="+")
        except Exception:
            pass

    def freeze_scroll_updates(self) -> None:
        """建页期间冻结滚动区域重算。"""
        self._scroll_frozen = True
        self._cancel_scheduled_update()

    def unfreeze_scroll_updates(self) -> None:
        """结束冻结并统一刷新一次滚动区域。"""
        self._scroll_frozen = False
        self.update_scroll()

    def schedule_update_scroll(self) -> None:
        """合并短时间内的多次 Configure，降低布局抖动。"""
        if self._scroll_frozen:
            return
        self._cancel_scheduled_update()
        try:
            self._scroll_after_id = self.after(
                self._SCROLL_DEBOUNCE_MS, self.update_scroll
            )
        except Exception:
            self._scroll_after_id = None

    def _cancel_scheduled_update(self) -> None:
        if self._scroll_after_id is None:
            return
        try:
            self.after_cancel(self._scroll_after_id)
        except Exception:
            pass
        self._scroll_after_id = None

    def on_canvas_configure(self, event):
        try:
            self.canvas.itemconfigure(self.window_id, width=self.canvas.winfo_width())
        except Exception:
            pass

    def update_scroll(self):
        self._scroll_after_id = None
        if self._scroll_frozen:
            return
        try:
            self.outer_content.update_idletasks()
            self.inner_content.update_idletasks()
            self.canvas.update_idletasks()

            req_h = self.outer_content.winfo_reqheight()
            can_h = self.canvas.winfo_height()
            if can_h <= 1:
                can_h = self.canvas.winfo_reqheight()

            bbox = self.canvas.bbox("all")
            if bbox is None:
                bbox = (0, 0, self.canvas.winfo_width(), req_h)
            self.canvas.configure(scrollregion=bbox)

            self._content_overflows = req_h > can_h
            # 内容不够高时复位到顶部（滚动条仍占位，避免布局抖动）
            if not self._content_overflows:
                self.canvas.yview_moveto(0)
        except Exception:
            pass

    def _on_panel_enter(self, _event: object = None) -> None:
        if self._wheel_bound_all:
            return
        try:
            self.winfo_toplevel().bind_all("<MouseWheel>", self._on_mousewheel)
            self._wheel_bound_all = True
        except Exception:
            self._wheel_bound_all = False

    def _on_panel_leave(self, event: object = None) -> None:
        # Leave 会在进入子控件时误触发；仅当指针真正离开本面板再解绑
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            widget = self.winfo_containing(x, y)
            if widget is not None and self._is_descendant(widget):
                return
        except Exception:
            pass
        if not self._wheel_bound_all:
            return
        try:
            self.winfo_toplevel().unbind_all("<MouseWheel>")
        except Exception:
            pass
        self._wheel_bound_all = False

    def _is_descendant(self, widget: object) -> bool:
        current = widget
        while current is not None:
            if current is self or current is self.canvas or current is self.outer_content:
                return True
            current = getattr(current, "master", None)
        return False

    def _widget_is_nested_scrollable(self, widget: object) -> bool:
        """落在自带纵向滚动的子控件上时，不抢滚轮。"""
        current = widget
        while current is not None and current is not self:
            cls = current.__class__.__name__.lower()
            # Text / CTkTextbox 内部文本区、ScrolledText 等
            if cls in {"text", "scrolledtext", "ctktextbox"}:
                return True
            if "textbox" in cls or "scrolled" in cls:
                return True
            current = getattr(current, "master", None)
        return False

    def _on_mousewheel(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
            if widget is None or not self._is_descendant(widget):
                return
            # 内容未超出可视区：输入框本身无滚动条，整页也不应跟着滚
            if not self._content_overflows:
                return
            # 发件人等多行框优先自己滚动
            if self._widget_is_nested_scrollable(widget):
                return
            delta = int(-event.delta / 120)
            if delta != 0:
                self.canvas.yview_scroll(delta, "units")
                return "break"
        except Exception:
            pass


class LogPanel(ctk.CTkFrame):
    def __init__(self, master, title, **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)

        colors = get_idea_dark_colors()

        self.pack(fill="both", expand=True, padx=0, pady=0)

        log_header = ctk.CTkFrame(
            self,
            height=40,
            corner_radius=0,
            fg_color=colors.get("bg_secondary", "#3c3f41"),
        )
        log_header.pack(fill="x", padx=0, pady=0)
        log_header.pack_propagate(False)

        log_label = ctk.CTkLabel(
            log_header,
            text=title,
            font=("Microsoft YaHei", 13, "bold"),
            text_color=colors.get("text_primary", "#bbbbbb"),
        )
        log_label.pack(side="left", padx=15, pady=10)

        log_container = ctk.CTkFrame(
            self, corner_radius=0, fg_color=colors.get("bg_secondary", "#3c3f41")
        )
        log_container.pack(fill="both", expand=True, padx=0, pady=0)

        self.text_log = scrolledtext.ScrolledText(
            log_container,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground=colors.get("highlight", "#264f78"),
            font=("Consolas", 12),
            wrap=tk.WORD,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        self.text_log.pack(fill="both", expand=True, padx=15, pady=15)

        scrollbar = getattr(self.text_log, "vbar", None)
        style_tk_scrollbar(scrollbar, colors)
