"""
基础页面类 - 所有工具页面的基类
"""
import tkinter as tk
import customtkinter as ctk
import threading
from abc import ABC, abstractmethod
from typing import Optional, Dict, Callable
from tkinter import messagebox

from gui.base.mixins import ConnectionMixin, ConfigMixin
from gui.styling.themes import get_idea_dark_colors, init_theme
from gui.widgets.frames import ScrollableFrame, LogPanel
from gui.widgets.labels import TitleLabel
from gui.utils.gui_utils import safe_configure
from utils.log_handler import setup_logger


class BaseToolPage(ctk.CTkFrame, ConnectionMixin, ABC):
    """
    工具页面基类

    提供标准的左右面板布局:
    - 左侧: 配置面板 (可滚动)
    - 右侧: 日志面板

    子类需要实现:
    - setup_left_panel_content(parent): 设置左侧面板的具体内容
    - get_config_dict(): 返回要保存的配置字典
    - apply_config(config): 应用加载的配置
    - execute_task(): 执行主要任务 (在后台线程中运行)
    """

    def __init__(self, root, config_file: str, log_title: str = "📋 操作日志", core_logger=None):
        """
        初始化基础页面

        Args:
            root: 父容器
            config_file: 配置文件路径
            log_title: 日志面板标题
            core_logger: 核心日志记录器
        """
        ctk.CTkFrame.__init__(self, root, corner_radius=0, fg_color="transparent")
        ConnectionMixin.__init__(self)

        self.root = root
        self.config_file = config_file
        self.core_logger = core_logger

        # 初始化 CTk
        self.ctk = ctk
        init_theme(ctk)

        # IDEA 深色主题颜色
        self.idea_dark_colors = get_idea_dark_colors()

        # 配置管理器
        from utils.config_manager import ConfigManager
        self.config_manager = ConfigManager(config_file)

        # 主容器 - 左右分割布局
        main_container = self.ctk.CTkFrame(self, corner_radius=0, fg_color=self.idea_dark_colors["bg"])
        main_container.pack(fill='both', expand=True, padx=0, pady=0)

        # 左侧配置面板
        left_panel = self.ctk.CTkFrame(
            main_container,
            width=420,
            corner_radius=0,
            fg_color=self.idea_dark_colors["sidebar_bg"]
        )
        left_panel.pack(side='left', fill='y', padx=(0, 1), pady=0)
        left_panel.pack_propagate(False)

        # 右侧日志面板
        right_panel = self.ctk.CTkFrame(
            main_container,
            corner_radius=0,
            fg_color=self.idea_dark_colors["bg"]
        )
        right_panel.pack(side='left', fill='both', expand=True, padx=(1, 0), pady=0)

        # 设置左侧面板
        self._setup_left_panel(left_panel, log_title)

        # 设置右侧面板
        self._setup_right_panel(right_panel, log_title)

        # 日志输出
        self.logger = setup_logger(self.text_log, self.core_logger)

        # 加载连接并填充
        try:
            self.root.bind("<Map>", lambda e: self.load_connections_and_update())
        except Exception:
            pass
        self.load_connections_and_update()

        # 加载配置
        self.load_and_apply_config()

    def _setup_left_panel(self, parent, log_title):
        """设置左侧配置面板"""
        # 滚动容器
        scroll_frame = ScrollableFrame(parent)
        self.left_content = scroll_frame.inner_content

        # 调用子类实现的内容设置方法
        self.setup_left_panel_content(self.left_content)

    def _setup_right_panel(self, parent, log_title):
        """设置右侧日志面板"""
        log_panel = LogPanel(parent, title=log_title)
        log_panel.pack(fill='both', expand=True, padx=(1, 0), pady=0)
        self.text_log = log_panel.text_log

    @abstractmethod
    def setup_left_panel_content(self, parent):
        """
        设置左侧面板的具体内容 (子类必须实现)

        Args:
            parent: 左侧面板的父容器
        """
        pass

    @abstractmethod
    def get_config_dict(self) -> Dict:
        """
        返回要保存的配置字典 (子类必须实现)

        Returns:
            配置字典
        """
        pass

    @abstractmethod
    def apply_config(self, config: Dict):
        """
        应用加载的配置 (子类必须实现)

        Args:
            config: 配置字典
        """
        pass

    @abstractmethod
    def execute_task(self) -> Dict:
        """
        执行主要任务 (子类必须实现)

        在后台线程中运行,应该返回结果字典:
        {"success": bool, "error": str (可选)}

        Returns:
            结果字典
        """
        pass

    def save_current_config(self):
        """保存当前配置"""
        config = self.get_config_dict()
        success = self.config_manager.save(config, self.core_logger)
        if not success and hasattr(self, 'logger') and self.logger:
            self.logger.warning("配置保存失败")

    def load_and_apply_config(self):
        """加载并应用配置"""
        config = self.config_manager.load(self.core_logger)
        if config:
            try:
                self.apply_config(config)
                if hasattr(self, 'logger') and self.logger:
                    self.logger.info("配置已加载")
            except Exception as e:
                error_msg = f"加载配置失败: {str(e)}"
                if hasattr(self, 'logger') and self.logger:
                    self.logger.error(error_msg)
        else:
            if hasattr(self, 'logger') and self.logger:
                self.logger.info("未找到配置文件,使用默认设置")

    def run_task(self, button_widget=None, button_text="🚀 开始", running_text="执行中..."):
        """
        执行任务 (在后台线程中)

        Args:
            button_widget: 要禁用的按钮控件
            button_text: 按钮的正常文本
            running_text: 按钮的运行中文本
        """
        # 保存当前配置
        self.save_current_config()

        # 清空日志
        if hasattr(self, 'text_log'):
            self.text_log.delete(1.0, tk.END)

        if hasattr(self, 'logger') and self.logger:
            self.logger.info("开始执行任务...")

        # 禁用按钮
        if button_widget:
            safe_configure(button_widget, state='disabled', text=running_text)

        def task():
            try:
                result = self.execute_task()

                # 在主线程中更新 UI
                def update_ui():
                    if button_widget:
                        safe_configure(button_widget, state='normal', text=button_text)

                    if result.get("success"):
                        messagebox.showinfo("完成", "任务执行成功!")
                        if hasattr(self, 'logger') and self.logger:
                            self.logger.info("任务执行成功完成")
                    else:
                        error_msg = result.get("error", "任务执行过程中发生错误")
                        messagebox.showerror("错误", error_msg)
                        if hasattr(self, 'logger') and self.logger:
                            self.logger.error(f"任务失败: {error_msg}")

                self.root.after(0, update_ui)

            except Exception as e:
                # 在主线程中显示错误
                def show_error():
                    if button_widget:
                        safe_configure(button_widget, state='normal', text=button_text)
                    messagebox.showerror("错误", f"任务失败: {str(e)}")
                    if hasattr(self, 'logger') and self.logger:
                        self.logger.exception("任务执行过程中发生异常")

                self.root.after(0, show_error)

        # 在新线程中执行任务
        threading.Thread(target=task, daemon=True).start()
