"""
可复用组件 - 路径选择器
"""
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog
from gui.widgets.labels import StyledLabel
from gui.widgets.entries import StyledEntry
from gui.widgets.buttons import StyledButton
from gui.styling.themes import get_idea_dark_colors


class PathSelector(ctk.CTkFrame):
    """
    路径选择器组件

    提供一个标签、输入框和浏览按钮的组合,用于选择文件或文件夹
    """

    def __init__(self, master, label_text="路径", mode="file", file_types=None, **kwargs):
        """
        初始化路径选择器

        Args:
            master: 父容器
            label_text: 标签文本
            mode: 选择模式 ("file", "folder", "zip")
            file_types: 文件类型过滤 (仅在 mode="file" 时有效)
            **kwargs: 其他 CTkFrame 参数
        """
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self.mode = mode
        self.file_types = file_types or [("所有文件", "*.*")]
        self.colors = get_idea_dark_colors()

        # 标签
        self.label = StyledLabel(self, text=label_text)
        self.label.pack(anchor='w', pady=(0, 3))

        # 路径输入框和浏览按钮
        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(anchor='w', fill='x')

        self.path_var = tk.StringVar()
        self.entry_path = StyledEntry(path_frame, textvariable=self.path_var)
        self.entry_path.pack(side='left', fill='x', expand=True, padx=(0, 8))

        self.browse_button = StyledButton(
            path_frame,
            text="浏览",
            command=self.browse_path
        )
        self.browse_button.pack(side='left')

    def browse_path(self):
        """浏览选择路径"""
        selected_path = ""

        if self.mode == "folder":
            folder_path = filedialog.askdirectory()
            if folder_path:
                selected_path = folder_path
        elif self.mode == "zip":
            path = filedialog.askopenfilename(
                title="选择ZIP压缩包",
                filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")]
            )
            if path:
                selected_path = path
        else:  # file
            path = filedialog.askopenfilename(
                title="选择文件",
                filetypes=self.file_types
            )
            if path:
                selected_path = path

        if selected_path:
            self.path_var.set(selected_path)
            # 触发回调 (如果设置了)
            if hasattr(self, 'on_path_selected') and callable(self.on_path_selected):
                self.on_path_selected(selected_path)

    def get_path(self):
        """获取当前路径"""
        return self.path_var.get().strip()

    def set_path(self, path):
        """设置路径"""
        self.path_var.set(path)

    def set_callback(self, callback):
        """设置路径选择后的回调函数"""
        self.on_path_selected = callback
