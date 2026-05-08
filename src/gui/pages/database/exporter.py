"""
重构后的数据库导出页面 - 使用新的基类和组件架构
"""
import tkinter as tk
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import ConnectionSelector, PathSelector
from gui.widgets.labels import TitleLabel, StyledLabel
from gui.widgets.buttons import PrimaryButton
from gui.widgets.scrolled_texts import StyledScrolledText
from core.exporter_db import export_database_to_sql, logger as core_logger


class ExportDbPage(BaseToolPage):
    """
    数据库导出页面 - 重构版本

    使用 BaseToolPage 基类,提供:
    - 标准的左右面板布局
    - 连接管理功能
    - 配置管理功能
    - 日志记录功能
    - 线程执行功能
    """

    CONFIG_FILE = "~/.db_exporter_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 导出日志",
            core_logger=core_logger
        )

    def setup_left_panel_content(self, parent):
        """设置左侧面板的具体内容"""
        # 标题
        title = TitleLabel(parent, text="📦 数据库导出")
        title.pack(anchor='w', pady=(0, 15))

        # 数据库连接选择器
        self.connection_selector = ConnectionSelector(parent, label_text="数据库连接")
        self.connection_selector.pack(fill='x', pady=(0, 15))

        # 设置连接变量引用 (用于兼容 ConnectionMixin)
        self.connection_var = self.connection_selector.connection_var
        self.connection_menu = self.connection_selector.connection_menu

        # 排除表名
        exclude_label = StyledLabel(parent, text="排除的表名（多个表可用逗号分隔）")
        exclude_label.pack(anchor='w', pady=(0, 3))

        # 排除表名文本框容器
        exclude_container = self.ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8
        )
        exclude_container.pack(fill='both', pady=(0, 15))

        self.text_exclude_tables = StyledScrolledText(exclude_container)
        self.text_exclude_tables.pack(fill='both', expand=True, padx=5, pady=5)
        self.text_exclude_tables.configure(height=10)

        # 导出目录选择器
        self.path_selector = PathSelector(
            parent,
            label_text="导出目录",
            mode="folder"
        )
        self.path_selector.pack(fill='x', pady=(0, 15))

        # 包含清空表语句选项
        truncate_checkbox_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        truncate_checkbox_frame.pack(anchor='w', pady=(0, 15))

        self.truncate_var = tk.BooleanVar(value=True)
        self.truncate_checkbox = self.ctk.CTkCheckBox(
            truncate_checkbox_frame,
            text="包含清空表语句",
            variable=self.truncate_var,
            font=('Microsoft YaHei', 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"]
        )
        self.truncate_checkbox.pack(side='left')

        # 开始导出按钮
        self.export_button = PrimaryButton(
            parent,
            text="🚀 开始导出",
            command=self.start_task
        )
        self.export_button.pack(anchor='w', fill='x', pady=(10, 0))

    def get_config_dict(self):
        """返回要保存的配置字典"""
        selected_name = self.get_selected_connection_name()
        return {
            'selected_connection_name': selected_name,
            'exclude_tables': self.text_exclude_tables.get("1.0", tk.END).strip(),
            'export_dir': self.path_selector.get_path(),
            'include_truncate': self.truncate_var.get()
        }

    def apply_config(self, config):
        """应用加载的配置"""
        try:
            # 设置连接
            selected_name = config.get('selected_connection_name')
            if selected_name:
                idx = self.find_connection_index_by_name(selected_name)
                if idx is not None and idx >= 0:
                    connection_names = [
                        f"{c.get('name', '未命名连接')} ({c.get('host', '')}:{c.get('port', '')})"
                        for c in self.connections
                    ]
                    if idx < len(connection_names):
                        self.connection_selector.set_value(connection_names[idx])

            # 设置排除表名
            exclude_tables = config.get('exclude_tables', '')
            self.text_exclude_tables.delete("1.0", tk.END)
            self.text_exclude_tables.insert(tk.END, exclude_tables)

            # 设置导出目录
            export_dir = config.get('export_dir', '')
            self.path_selector.set_path(export_dir)

            # 设置包含清空表选项
            self.truncate_var.set(config.get('include_truncate', True))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {str(e)}")

    def start_task(self):
        """启动导出任务"""
        self.run_task(
            button_widget=self.export_button,
            button_text="🚀 开始导出",
            running_text="导出中..."
        )

    def execute_task(self):
        """执行导出任务 - 在后台线程中运行"""
        # 验证参数
        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        # 获取选中的连接配置
        selected_name = self.get_selected_connection_name()
        idx = self.find_connection_index_by_name(selected_name) if selected_name else None
        if idx is None or idx < 0 or idx >= len(self.connections):
            return {"success": False, "error": "请选择一个有效的数据库连接"}

        db_config = self.connections[idx]
        exclude_tables_str = self.text_exclude_tables.get("1.0", tk.END).strip()
        export_dir = self.path_selector.get_path()
        include_truncate = self.truncate_var.get()

        # 支持逗号或换行分隔的表名
        exclude_tables = []
        if exclude_tables_str:
            for line in exclude_tables_str.split('\n'):
                exclude_tables.extend([t.strip() for t in line.split(',') if t.strip()])

        if self.logger:
            self.logger.info("开始数据库导出...")
            if exclude_tables:
                self.logger.info(f"排除表: {', '.join(exclude_tables)}")
            self.logger.info(f"导出目录: {export_dir}")
            self.logger.info(f"包含清空表语句: {include_truncate}")

        # 执行导出
        result = export_database_to_sql(
            db_config=db_config,
            export_dir=export_dir,
            schema=db_config.get('schema', 'public'),
            exclude_tables=exclude_tables,
            include_truncate=include_truncate
        )

        if result["success"]:
            if self.logger:
                self.logger.info("数据库导出成功完成")
        else:
            error_msg = result.get("error", "导出过程中发生错误")
            if self.logger:
                self.logger.error(f"导出失败: {error_msg}")

        return result

    def validate(self):
        """验证输入参数"""
        export_dir = self.path_selector.get_path()

        if not export_dir:
            messagebox.showerror("错误", "请选择导出目录")
            return False

        return True

    def on_task_success(self, result):
        """任务成功完成时的回调"""
        messagebox.showinfo("完成", "数据库导出成功！")

    def on_task_error(self, result):
        """任务失败时的回调"""
        error_msg = result.get("error", "导出过程中发生错误")
        messagebox.showerror("错误", error_msg)


# 向后兼容别名
ExportDbApp = ExportDbPage