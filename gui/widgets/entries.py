import customtkinter as ctk
from gui.styling.themes import get_idea_dark_colors

class StyledEntry(ctk.CTkEntry):
    def __init__(self, master, placeholder_text="", show=None, **kwargs):
        colors = get_idea_dark_colors()
        style = {
            "corner_radius": 5,
            "border_width": 1,
            "border_color": colors["gray_button_border"],
            "fg_color": colors["gray_button"],
            "text_color": colors["gray_button_fg"],
            "placeholder_text_color": colors["text_secondary"],
            "font": ("Microsoft YaHei", 10),
            "height": 26
        }
        if show:
            style["show"] = show

        super().__init__(master, placeholder_text=placeholder_text, **style, **kwargs)