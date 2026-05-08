import tkinter as tk
import customtkinter as ctk
from tkinter import scrolledtext
from gui.styling.themes import get_idea_dark_colors
from gui.styling.styles import style_tk_scrollbar

class ScrollableFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        super().__init__(master, **kwargs)
        
        self.pack(fill='both', expand=True, padx=0, pady=0)
        
        colors = get_idea_dark_colors()
        
        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            bg=colors.get("sidebar_bg", "#252526")
        )
        
        self.v_scrollbar = ctk.CTkScrollbar(
            self,
            orientation="vertical",
            command=self.canvas.yview
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
        self.canvas.pack(side="left", fill="both", expand=True)
        self.v_scrollbar.pack(side="right", fill="y")
        
        self.outer_content = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self.window_id = self.canvas.create_window((0, 0), window=self.outer_content, anchor="nw")
        
        self.inner_content = ctk.CTkFrame(self.outer_content, fg_color="transparent")
        self.inner_content.pack(fill="both", expand=True, padx=20, pady=15)
        
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.outer_content.bind("<Configure>", lambda e: self.update_scroll())
        self.inner_content.bind("<Configure>", lambda e: self.update_scroll())
        self.bind("<Configure>", lambda e: self.update_scroll())
        self.after(80, self.update_scroll)
        
        for w in (self.canvas, self, self.outer_content, self.inner_content):
            try:
                w.bind("<MouseWheel>", self._on_mousewheel)
            except Exception:
                pass
                
        try:
            root = self.winfo_toplevel()
            def _on_enter(_):
                try:
                    root.bind_all("<MouseWheel>", self._on_mousewheel)
                except Exception:
                    pass
            def _on_leave(_):
                try:
                    root.unbind_all("<MouseWheel>")
                except Exception:
                    pass
            self.bind("<Enter>", _on_enter)
            self.bind("<Leave>", _on_leave)
            self.outer_content.bind("<Enter>", _on_enter)
            self.outer_content.bind("<Leave>", _on_leave)
            self.inner_content.bind("<Enter>", _on_enter)
            self.inner_content.bind("<Leave>", _on_leave)
        except Exception:
            pass
            
    def on_canvas_configure(self, event):
        try:
            self.canvas.itemconfigure(self.window_id, width=self.canvas.winfo_width())
        except Exception:
            pass
            
    def update_scroll(self):
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

            if req_h > can_h:
                if not self.v_scrollbar.winfo_ismapped():
                    self.v_scrollbar.pack(side="right", fill="y")
            else:
                if self.v_scrollbar.winfo_ismapped():
                    self.v_scrollbar.pack_forget()
        except Exception:
            pass
            
    def _on_mousewheel(self, event):
        try:
            delta = int(-event.delta / 120)
            if delta != 0:
                self.canvas.focus_set()
                self.canvas.yview_scroll(delta, "units")
        except Exception:
            pass

class LogPanel(ctk.CTkFrame):
    def __init__(self, master, title, **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)
        
        colors = get_idea_dark_colors()
        
        self.pack(fill='both', expand=True, padx=0, pady=0)
        
        log_header = ctk.CTkFrame(
            self,
            height=40,
            corner_radius=0,
            fg_color=colors.get("bg_secondary", "#3c3f41")
        )
        log_header.pack(fill='x', padx=0, pady=0)
        log_header.pack_propagate(False)

        log_label = ctk.CTkLabel(
            log_header,
            text=title,
            font=('Microsoft YaHei', 13, 'bold'),
            text_color=colors.get("text_primary", "#bbbbbb")
        )
        log_label.pack(side='left', padx=15, pady=10)

        log_container = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=colors.get("bg_secondary", "#3c3f41")
        )
        log_container.pack(fill='both', expand=True, padx=0, pady=0)

        self.text_log = scrolledtext.ScrolledText(
            log_container,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground=colors.get("highlight", "#264f78"),
            font=("Consolas", 12),
            wrap=tk.WORD,
            relief='flat',
            borderwidth=0,
            highlightthickness=0
        )
        self.text_log.pack(fill='both', expand=True, padx=15, pady=15)

        scrollbar = getattr(self.text_log, 'vbar', None)
        style_tk_scrollbar(scrollbar, colors)