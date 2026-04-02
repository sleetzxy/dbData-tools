"""
CSV 导出页面 - 使用新的基类和组件架构
"""
import tkinter as tk
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import ConnectionSelector, PathSelector
from gui.widgets.labels import TitleLabel, StyledLabel
from gui.widgets.buttons import PrimaryButton
from gui.widgets.scrolled_texts import StyledScrolledText
from core.exporter_csv import export_tables_to_csv, logger as core_logger


class ExportCsvPage(BaseToolPage):
    """CSV 导出页面。"""

    CONFIG_FILE = "~/.csv_exporter_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 导出日志",
            core_logger=core_logger,
        )

    def setup_left_panel_content(self, parent):
        title = TitleLabel(parent, text="📄 CSV 导出")
        title.pack(anchor="w", pady=(0, 15))

        self.connection_selector = ConnectionSelector(parent, label_text="数据库连接")
        self.connection_selector.pack(fill="x", pady=(0, 15))

        self.connection_var = self.connection_selector.connection_var
        self.connection_menu = self.connection_selector.connection_menu

        tables_label = StyledLabel(parent, text="要导出的表名（多个表可用逗号分隔）")
        tables_label.pack(anchor="w", pady=(0, 3))

        tables_container = self.ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8,
        )
        tables_container.pack(fill="both", pady=(0, 15))

        self.text_tables = StyledScrolledText(tables_container)
        self.text_tables.pack(fill="both", expand=True, padx=5, pady=5)
        self.text_tables.configure(height=10)

        self.path_selector = PathSelector(parent, label_text="导出目录", mode="folder")
        self.path_selector.pack(fill="x", pady=(0, 15))

        header_frame_checkbox = self.ctk.CTkFrame(parent, fg_color="transparent")
        header_frame_checkbox.pack(anchor="w", pady=(0, 15))

        self.header_var = tk.BooleanVar(value=True)
        self.header_checkbox = self.ctk.CTkCheckBox(
            header_frame_checkbox,
            text="包含表头",
            variable=self.header_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        )
        self.header_checkbox.pack(side="left")

        self.export_button = PrimaryButton(parent, text="🚀 开始导出", command=self.start_task)
        self.export_button.pack(anchor="w", fill="x", pady=(10, 0))

    def get_config_dict(self):
        selected_name = self.get_selected_connection_name()
        return {
            "selected_connection_name": selected_name,
            "tables": self.text_tables.get("1.0", tk.END).strip(),
            "export_dir": self.path_selector.get_path(),
            "include_header": self.header_var.get(),
        }

    def apply_config(self, config):
        try:
            selected_name = config.get("selected_connection_name")
            if selected_name:
                idx = self.find_connection_index_by_name(selected_name)
                if idx is not None and idx >= 0:
                    connection_names = [
                        f"{c.get('name', '未命名连接')} ({c.get('host', '')}:{c.get('port', '')})"
                        for c in self.connections
                    ]
                    if idx < len(connection_names):
                        self.connection_selector.set_value(connection_names[idx])

            tables_text = config.get("tables", "")
            self.text_tables.delete("1.0", tk.END)
            self.text_tables.insert(tk.END, tables_text)

            export_dir = config.get("export_dir", "")
            self.path_selector.set_path(export_dir)
            self.header_var.set(config.get("include_header", True))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {str(e)}")

    def start_task(self):
        payload, error_message = self.collect_task_payload()
        if error_message:
            messagebox.showerror("错误", error_message)
            return

        self._task_payload = payload
        self.run_task(
            button_widget=self.export_button,
            button_text="🚀 开始导出",
            running_text="导出中...",
        )

    def execute_task(self):
        payload = getattr(self, "_task_payload", None)
        if not payload:
            return {"success": False, "error": "导出参数为空"}

        db_config = payload["db_config"]
        tables = payload["tables"]
        export_dir = payload["export_dir"]
        include_header = payload["include_header"]
        schema = payload["schema"]

        if self.logger:
            self.logger.info("开始导出 CSV...")
            self.logger.info(f"导出表: {', '.join(tables)}")
            self.logger.info(f"导出目录: {export_dir}")

        result = export_tables_to_csv(
            db_config=db_config,
            tables=tables,
            export_dir=export_dir,
            schema=schema,
            include_header=include_header,
        )

        if result["success"]:
            if self.logger:
                self.logger.info("CSV 导出完成")
        else:
            error_msg = result.get("error", "导出过程中发生错误")
            if self.logger:
                self.logger.error(f"导出失败: {error_msg}")

        return result

    def collect_task_payload(self):
        selected_name = self.get_selected_connection_name()
        idx = self.find_connection_index_by_name(selected_name) if selected_name else None
        if idx is None or idx < 0 or idx >= len(self.connections):
            return None, "请选择一个有效的数据库连接"

        db_config = self.connections[idx]
        tables_str = self.text_tables.get("1.0", tk.END).strip()
        export_dir = self.path_selector.get_path()
        include_header = self.header_var.get()

        if not tables_str:
            return None, "请输入要导出的表名"
        if not export_dir:
            return None, "请选择导出目录"

        tables = []
        for line in tables_str.splitlines():
            tables.extend([t.strip() for t in line.split(",") if t.strip()])

        if not tables:
            return None, "未解析出有效的表名"

        return (
            {
                "db_config": db_config,
                "tables": tables,
                "export_dir": export_dir,
                "include_header": include_header,
                "schema": db_config.get("schema", "public"),
            },
            None,
        )


ExportCsvApp = ExportCsvPage
