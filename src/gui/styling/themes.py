def get_idea_dark_colors():
    """返回统一的 IDEA 深色主题颜色字典"""
    return {
        "bg": "#2b2b2b",
        "bg_secondary": "#3c3f41",
        "sidebar_bg": "#252526",
        "border": "#454545",
        "text_primary": "#bbbbbb",
        "text_secondary": "#808080",
        "accent": "#4b6eaf",
        "accent_hover": "#5b7ec0",
        "error": "#F44336",
        "button_hover": "#4c5153",
        "card_bg": "#383838",
        "highlight": "#264f78",
        "gray_button": "#5c5f62",
        "gray_button_hover": "#6c6f72",
        "gray_button_border": "#454545",
        "gray_button_fg": "#d4d4d4",
        # 统一新增的滚动条与灰色系按钮键名（供所有GUI使用）
        "button_bg": "#4a4a4a",
        "button_hover_gray": "#5a5a5a",
        "button_active": "#6a6a6a",
        "scrollbar_bg": "#2d2d2d",
        "scrollbar_button": "#5c5f62",
        "scrollbar_hover": "#6c6f72",
    }

def init_theme(ctk):
    """初始化 customtkinter 的深色主题设置"""
    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
    except Exception:
        # 在某些环境下可能未安装或初始化失败，忽略以继续运行
        pass