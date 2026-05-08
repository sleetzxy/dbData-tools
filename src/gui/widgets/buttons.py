import customtkinter as ctk
from gui.styling.themes import get_idea_dark_colors

class StyledButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 默认样式
        default_style = {
            "height": 26,
            "width": 64,
            "corner_radius": 5,
            "font": ('Microsoft YaHei', 10),
            "fg_color": colors["gray_button"],
            "hover_color": colors["gray_button_hover"],
            "border_color": colors["gray_button_border"],
            "text_color": colors["gray_button_fg"]
        }
        
        # 合并传入的样式
        style = {**default_style, **kwargs}
        
        super().__init__(master, **style)

class PrimaryButton(StyledButton):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 主要按钮的特定样式
        primary_style = {
            "height": 36,
            "corner_radius": 6,
            "font": ('Microsoft YaHei', 12, 'bold'),
            "fg_color": colors["accent"],
            "hover_color": colors["accent_hover"],
            "text_color": "white"
        }
        
        # 合并传入的样式
        style = {**primary_style, **kwargs}
        
        super(StyledButton, self).__init__(master, **style)