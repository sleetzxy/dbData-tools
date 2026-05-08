import customtkinter as ctk
from gui.styling.themes import get_idea_dark_colors

class StyledLabel(ctk.CTkLabel):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 默认样式
        default_style = {
            "font": ('Microsoft YaHei', 11),
            "text_color": colors["text_secondary"]
        }
        
        # 合并传入的样式
        style = {**default_style, **kwargs}
        
        super().__init__(master, **style)

class TitleLabel(StyledLabel):
    def __init__(self, master, **kwargs):
        colors = get_idea_dark_colors()
        
        # 标题标签的特定样式
        title_style = {
            "font": ('Microsoft YaHei', 16, 'bold'),
            "text_color": colors["text_primary"]
        }
        
        # 合并传入的样式
        style = {**title_style, **kwargs}
        
        super(StyledLabel, self).__init__(master, **style)