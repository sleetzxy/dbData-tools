import tkinter as tk
from tkinter import scrolledtext
from gui.styling.themes import get_idea_dark_colors
from gui.styling.styles import style_tk_scrollbar

class StyledScrolledText(scrolledtext.ScrolledText):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 默认样式
        default_style = {
            "bg": colors["bg"],
            "fg": colors["text_primary"],
            "insertbackground": colors["text_primary"],
            "selectbackground": colors["highlight"],
            "font": ("Microsoft YaHei", 10),
            "wrap": tk.WORD,
            "relief": 'flat',
            "borderwidth": 0,
            "highlightthickness": 1,
            "highlightbackground": colors["border"],
            "highlightcolor": colors["accent"]
        }
        
        # 合并传入的样式
        style = {**default_style, **kwargs}
        
        super().__init__(master, **style)
        
        # 统一 Tk 滚动条样式
        style_tk_scrollbar(getattr(self, 'vbar', None), colors)