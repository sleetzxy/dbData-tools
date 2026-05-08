import customtkinter as ctk
from gui.styling.themes import get_idea_dark_colors

class StyledOptionMenu(ctk.CTkOptionMenu):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 默认样式
        default_style = {
            "anchor": 'w',
            "height": 26,
            "font": ('Microsoft YaHei', 10),
            "fg_color": colors["gray_button"],
            "button_color": colors["gray_button"],
            "button_hover_color": colors["gray_button_hover"],
            "text_color": colors["gray_button_fg"],
            "dropdown_fg_color": colors["bg_secondary"],
            "dropdown_hover_color": colors["gray_button_hover"],
            "dropdown_text_color": colors["text_primary"],
            "dropdown_font": ('Microsoft YaHei', 10),
            "corner_radius": 5
        }
        
        # 合并传入的样式
        style = {**default_style, **kwargs}
        
        super().__init__(master, **style)