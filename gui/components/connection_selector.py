"""
可复用组件 - 连接选择器
"""
import tkinter as tk
import customtkinter as ctk
from gui.widgets.labels import StyledLabel
from gui.widgets.option_menus import StyledOptionMenu
from gui.styling.themes import get_idea_dark_colors


class ConnectionSelector(ctk.CTkFrame):
    """
    数据库连接选择器组件

    提供一个标签和下拉框的组合,用于选择数据库连接
    """

    def __init__(self, master, label_text="数据库连接", **kwargs):
        """
        初始化连接选择器

        Args:
            master: 父容器
            label_text: 标签文本
            **kwargs: 其他 CTkFrame 参数
        """
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self.colors = get_idea_dark_colors()

        # 标签
        self.label = StyledLabel(self, text=label_text)
        self.label.pack(anchor='w', pady=(0, 3))

        # 下拉框
        self.connection_var = tk.StringVar()
        self.connection_menu = StyledOptionMenu(
            self,
            variable=self.connection_var,
            values=["加载中..."]
        )
        self.connection_menu.pack(anchor='w', fill='x')

    def set_values(self, values):
        """设置下拉框的值"""
        self.connection_menu.configure(values=values)
        if values:
            self.connection_menu.set(values[0])
            self.connection_var.set(values[0])

    def get_value(self):
        """获取当前选中的值"""
        return self.connection_var.get()

    def set_value(self, value):
        """设置当前选中的值"""
        self.connection_menu.set(value)
        self.connection_var.set(value)
