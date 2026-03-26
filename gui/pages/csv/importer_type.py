"""
重构后的 CSV 指定类型导入页面 - 使用新的基类和组件架构
"""
import tkinter as tk
import os
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import ConnectionSelector, PathSelector
from gui.widgets.labels import TitleLabel, StyledLabel
from gui.widgets.buttons import PrimaryButton
from gui.widgets.entries import StyledEntry
from core.importer_csv_type import logger as core_logger


class ImportCsvTypePage(BaseToolPage):
    """
    CSV 指定类型导入页面 - 重构版本

    使用 BaseToolPage 基类,提供:
    - 标准的左右面板布局
    - 连接管理功能
    - 配置管理功能
    - 日志记录功能
    - 线程执行功能
    """

    CONFIG_FILE = "~/.csv_importer_type_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 导入日志",
            core_logger=core_logger
        )

        # 初始化变量
        self.csv_entries = []
        self.last_path = None  # 记录上次刷新列表时的路径

    def setup_left_panel_content(self, parent):
        """设置左侧面板的具体内容"""
        # 标题
        title = TitleLabel(parent, text="📝 CSV导入（指定类型）")
        title.pack(anchor='w', pady=(0, 15))

        # 数据库连接选择器
        self.connection_selector = ConnectionSelector(parent, label_text="数据库连接")
        self.connection_selector.pack(fill='x', pady=(0, 15))

        # 设置连接变量引用 (用于兼容 ConnectionMixin)
        self.connection_var = self.connection_selector.connection_var
        self.connection_menu = self.connection_selector.connection_menu

        # CSV 目录路径选择器
        self.path_selector = PathSelector(
            parent,
            label_text="CSV目录路径",
            mode="folder"
        )
        self.path_selector.pack(fill='x', pady=(0, 15))

        # 设置路径变更回调
        self.path_selector.set_callback(self._on_path_changed)

        # CSV列表配置区标题
        config_title = self.ctk.CTkLabel(
            parent,
            text="CSV文件列表与类型配置",
            font=('Microsoft YaHei', 11),
            text_color=self.idea_dark_colors["text_secondary"]
        )
        config_title.pack(anchor='w', pady=(0, 3))

        # CSV列表配置区框架
        self.csv_list_container = self.ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=self.idea_dark_colors["card_bg"],
            height=200
        )
        self.csv_list_container.pack(fill='both', expand=True, pady=(0, 15))
        self.csv_list_container.pack_propagate(False)

        # 创建内部滚动容器
        self.csv_scrollable_frame = self.ctk.CTkScrollableFrame(
            self.csv_list_container,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8,
            scrollbar_fg_color=self.idea_dark_colors.get("scrollbar_bg", "#2d2d2d"),
            scrollbar_button_color=self.idea_dark_colors.get("scrollbar_button", "#5c5f62"),
            scrollbar_button_hover_color=self.idea_dark_colors.get("scrollbar_hover", "#6c6f72"),
        )
        self.csv_scrollable_frame.pack(fill='both', expand=True, padx=5, pady=5)

        # 备份选项
        backup_checkbox_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        backup_checkbox_frame.pack(anchor='w', pady=(0, 15))

        self.backup_var = tk.BooleanVar(value=True)
        self.backup_checkbox = self.ctk.CTkCheckBox(
            backup_checkbox_frame,
            text="导入前备份数据",
            variable=self.backup_var,
            font=('Microsoft YaHei', 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"]
        )
        self.backup_checkbox.pack(side='left')

        # 开始导入按钮
        self.import_button = PrimaryButton(
            parent,
            text="🚀 开始导入",
            command=self.start_task
        )
        self.import_button.pack(anchor='w', fill='x', pady=(10, 0))

    def _on_path_changed(self, path):
        """仅在路径变化时更新CSV列表，避免因焦点切换导致清空配置"""
        try:
            if path and path != self.last_path:
                self.last_path = path
                self.update_csv_list()
                if self.logger:
                    self.logger.info(f"已选择文件夹: {path}")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"路径变更处理失败: {e}")

    def clear_csv_list(self):
        """清空CSV列表配置区"""
        for widget in self.csv_scrollable_frame.winfo_children():
            widget.destroy()
        self.csv_entries.clear()

    def update_csv_list(self):
        """根据当前选择的文件夹，识别所有CSV并展示，每个CSV可选择类型列与数据类型"""
        # 先清空现有列表
        self.clear_csv_list()

        path = self.path_selector.get_path()
        if not path:
            if self.logger:
                self.logger.info("请输入文件夹路径")
            return

        csv_files = []
        try:
            # 只支持文件夹模式
            if os.path.isdir(path):
                for name in os.listdir(path):
                    if name.lower().endswith('.csv'):
                        csv_files.append(os.path.join(path, name))
            else:
                if self.logger:
                    self.logger.error(f"路径不是有效的文件夹: {path}")
                return
        except Exception as e:
            if self.logger:
                self.logger.error(f"识别CSV列表失败: {e}")
            return

        # 如果没有CSV文件，显示提示
        if not csv_files:
            no_files_label = self.ctk.CTkLabel(
                self.csv_scrollable_frame,
                text="未找到CSV文件",
                font=('Microsoft YaHei', 11, 'italic'),
                text_color=self.idea_dark_colors["text_secondary"]
            )
            no_files_label.pack(pady=20)
            return

        if self.logger:
            self.logger.info(f"找到 {len(csv_files)} 个CSV文件")

        # 记录当前路径，避免重复刷新导致清空配置
        self.last_path = path

        # 创建表头框架
        self._create_csv_list_header()

        # 创建文件列表
        for csv_path in csv_files:
            self._create_csv_entry_row(csv_path)

    def _create_csv_list_header(self):
        """创建CSV列表的表头"""
        header_frame = self.ctk.CTkFrame(
            self.csv_scrollable_frame,
            fg_color=self.idea_dark_colors["bg_secondary"],
            corner_radius=5,
            height=40
        )
        header_frame.pack(fill='x', padx=5, pady=(5, 10))

        # 配置网格布局，使各列宽度合理分配
        header_frame.grid_columnconfigure(0, weight=1, minsize=70)   # 表名列
        header_frame.grid_columnconfigure(1, weight=1, minsize=80)   # 类型列（缩小）
        header_frame.grid_columnconfigure(2, weight=1, minsize=60)   # 数据类型（缩小）
        header_frame.grid_columnconfigure(3, weight=2, minsize=140)  # 类型值（更宽的权重）

        # 表头标签
        labels = ["表名", "类型列", "数据类型", "类型值"]
        for i, text in enumerate(labels):
            label = self.ctk.CTkLabel(
                header_frame,
                text=text,
                font=("Microsoft YaHei", 10, "bold"),
                text_color=self.idea_dark_colors["text_primary"]
            )
            label.grid(row=0, column=i, sticky='w', padx=(10 if i == 0 else 5, 5), pady=8)

    def _create_csv_entry_row(self, csv_path):
        """为单个CSV文件创建配置行"""
        try:
            # 读取首行表头
            columns = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                header_line = f.readline().strip()
                columns = [c.strip() for c in header_line.split(',') if c.strip()]

            # 表名取文件名去除扩展名
            table_name = os.path.splitext(os.path.basename(csv_path))[0]

            # 创建每行框架
            row_frame = self.ctk.CTkFrame(
                self.csv_scrollable_frame,
                fg_color=self.idea_dark_colors["card_bg"],
                corner_radius=5,
                height=40
            )
            row_frame.pack(fill='x', padx=5, pady=2)

            # 配置网格布局，与表头保持一致
            row_frame.grid_columnconfigure(0, weight=1, minsize=70)   # 表名列
            row_frame.grid_columnconfigure(1, weight=1, minsize=80)   # 类型列（缩小）
            row_frame.grid_columnconfigure(2, weight=1, minsize=60)   # 数据类型（缩小）
            row_frame.grid_columnconfigure(3, weight=2, minsize=140)  # 类型值（更宽的权重）

            # 表名标签
            table_label = self.ctk.CTkLabel(
                row_frame,
                text=table_name,
                font=("Microsoft YaHei", 10),
                text_color=self.idea_dark_colors["text_primary"],
                anchor='w'
            )
            table_label.grid(row=0, column=0, sticky='ew', padx=(10, 5), pady=8)

            # 类型列选择框
            type_col_var = tk.StringVar()
            type_col_cb = self.ctk.CTkOptionMenu(
                row_frame,
                variable=type_col_var,
                values=columns,
                width=80,
                height=24,
                font=('Microsoft YaHei', 9),
                fg_color=self.idea_dark_colors["card_bg"],
                button_color=self.idea_dark_colors["gray_button"],
                button_hover_color=self.idea_dark_colors["gray_button_hover"],
                text_color=self.idea_dark_colors["gray_button_fg"],
                dropdown_fg_color=self.idea_dark_colors["card_bg"],
                dropdown_text_color=self.idea_dark_colors["text_primary"],
                corner_radius=3
            )
            type_col_cb.grid(row=0, column=1, sticky='w', padx=5, pady=8)

            # 数据类型选择框
            type_type_var = tk.StringVar(value="string")
            type_type_cb = self.ctk.CTkOptionMenu(
                row_frame,
                variable=type_type_var,
                values=["string", "number"],
                width=60,
                height=24,
                font=('Microsoft YaHei', 9),
                fg_color=self.idea_dark_colors["card_bg"],
                button_color=self.idea_dark_colors["gray_button"],
                button_hover_color=self.idea_dark_colors["gray_button_hover"],
                text_color=self.idea_dark_colors["gray_button_fg"],
                dropdown_fg_color=self.idea_dark_colors["card_bg"],
                dropdown_text_color=self.idea_dark_colors["text_primary"],
                corner_radius=3
            )
            type_type_cb.grid(row=0, column=2, sticky='w', padx=5, pady=8)

            # 类型值输入框
            value_var = tk.StringVar()
            value_entry = StyledEntry(
                row_frame,
                textvariable=value_var
            )
            value_entry.grid(row=0, column=3, sticky='ew', padx=(5, 10), pady=8)

            # 添加到条目列表
            self.csv_entries.append({
                "table": table_name,
                "type_col_var": type_col_var,
                "type_type_var": type_type_var,
                "value_var": value_var,
                "columns": columns,
                "type_col_cb": type_col_cb,
                "type_type_cb": type_type_cb,
                "value_entry": value_entry
            })

        except Exception as e:
            if self.logger:
                self.logger.error(f"读取CSV表头失败: {csv_path}, 错误: {e}")

    def get_config_dict(self):
        """返回要保存的配置字典"""
        selected_name = self.get_selected_connection_name()
        return {
            'selected_connection_name': selected_name,
            'data_path': self.path_selector.get_path(),
            'need_backup': self.backup_var.get(),
            'type_mapping': [
                {
                    "table": entry["table"],
                    "type_column": entry["type_col_var"].get(),
                    "type_datatype": entry["type_type_var"].get(),
                    "type_value": entry["value_var"].get()
                } for entry in self.csv_entries
            ]
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

            # 设置路径
            path = config.get('data_path', '')
            if path:
                self.path_selector.set_path(path)

            # 设置备份选项
            self.backup_var.set(config.get('need_backup', True))

            # 如果路径存在，更新CSV列表并应用配置
            if path and os.path.isdir(path):
                # 延迟执行，确保界面初始化完成
                self.root.after(100, lambda: self._load_csv_and_apply_config(path, config))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {str(e)}")

    def _load_csv_and_apply_config(self, path, config):
        """加载CSV列表并应用配置"""
        self.update_csv_list()
        # 给一点时间让CSV列表完全渲染
        self.root.after(300, lambda: self._apply_type_mapping(config))

    def _apply_type_mapping(self, config):
        """应用类型映射配置"""
        try:
            type_mapping = config.get('type_mapping', [])
            if not type_mapping:
                if self.logger:
                    self.logger.info("未找到类型映射配置")
                return

            mapping_by_table = {m["table"]: m for m in type_mapping if isinstance(m, dict)}

            applied_count = 0
            for entry in self.csv_entries:
                m = mapping_by_table.get(entry["table"])
                if m:
                    # 仅在列存在时应用
                    if m.get("type_column") in entry["columns"]:
                        entry["type_col_var"].set(m.get("type_column"))
                        entry["type_col_cb"].set(m.get("type_column"))
                    if m.get("type_datatype") in ["string", "number"]:
                        entry["type_type_var"].set(m.get("type_datatype"))
                        entry["type_type_cb"].set(m.get("type_datatype"))
                    # 应用类型值
                    type_value = m.get("type_value", "")
                    entry["value_var"].set(type_value)
                    entry["value_entry"].delete(0, tk.END)
                    entry["value_entry"].insert(0, type_value)
                    applied_count += 1

            if self.logger:
                self.logger.info(f"配置已加载，成功应用了 {applied_count} 个表的配置")
        except Exception as e:
            if self.logger:
                self.logger.error(f"应用类型映射配置失败: {str(e)}")

    def start_task(self):
        """启动导入任务"""
        self.run_task(
            button_widget=self.import_button,
            button_text="🚀 开始导入",
            running_text="导入中..."
        )

    def execute_task(self):
        """执行导入任务 - 在后台线程中运行"""
        # 验证参数
        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        # 获取选中的连接配置
        selected_name = self.get_selected_connection_name()
        idx = self.find_connection_index_by_name(selected_name) if selected_name else None
        if idx is None or idx < 0 or idx >= len(self.connections):
            return {"success": False, "error": "请选择一个有效的数据库连接"}

        db_config = self.connections[idx]
        data_path = self.path_selector.get_path()
        need_backup = self.backup_var.get()

        # 准备类型列映射
        type_column_map = {}
        for entry in self.csv_entries:
            table = entry["table"]
            type_col = entry["type_col_var"].get().strip()
            type_type = entry["type_type_var"].get().strip()
            type_value = entry["value_var"].get().strip()

            # 将单个值封装为列表，兼容多个值（逗号/分号分隔）
            unified = type_value.replace("；", ";").replace("，", ",").replace(";", ",")
            parts = [p.strip() for p in unified.split(",") if p.strip()]

            type_column_map[table] = {
                "column": type_col,
                "datatype": type_type,
                "values": parts
            }

        if self.logger:
            self.logger.info("开始导入数据...")
            self.logger.info(f"数据源: {data_path}")
            self.logger.info(f"需要备份: {need_backup}")

        try:
            from core.importer_csv_type import import_csv_incremental_segmented_to_db
            result = import_csv_incremental_segmented_to_db(
                db_config=db_config,
                data_source=data_path,
                source_type="folder",
                schema=db_config.get('schema', 'public'),
                need_backup=need_backup,
                type_column_map=type_column_map
            )

            if result["success"]:
                if self.logger:
                    self.logger.info("导入成功完成")
            else:
                error_msg = result.get("error", "导入过程中发生错误")
                if self.logger:
                    self.logger.error(f"导入失败: {error_msg}")

            return result

        except Exception as e:
            error_msg = f"导入失败: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def validate(self):
        """验证输入参数"""
        data_path = self.path_selector.get_path()

        if not data_path:
            messagebox.showerror("错误", "请选择CSV文件目录")
            return False

        # 验证数据来源（目录）
        if not os.path.isdir(data_path):
            messagebox.showerror("错误", f"目录不存在: {data_path}")
            return False

        # 如果未识别到任何CSV文件，给出提示并终止
        if not self.csv_entries:
            messagebox.showerror("错误", "未识别到任何CSV文件，请确认数据源路径有效，并在列表中完成类型列与数据类型的选择后再试。")
            return False

        # 验证每个CSV文件的配置
        for entry in self.csv_entries:
            table = entry["table"]
            type_col = entry["type_col_var"].get().strip()
            type_type = entry["type_type_var"].get().strip()
            type_value = entry["value_var"].get().strip()

            if not type_col:
                messagebox.showerror("错误", f"请为表 {table} 选择类型列")
                return False
            if type_type not in ["string", "number"]:
                messagebox.showerror("错误", f"请为表 {table} 选择类型数据类型（字符串或数字）")
                return False
            if not type_value:
                messagebox.showerror("错误", f"请为表 {table} 输入类型值")
                return False

        return True

    def on_task_success(self, result):
        """任务成功完成时的回调"""
        messagebox.showinfo("完成", "数据导入成功！")

    def on_task_error(self, result):
        """任务失败时的回调"""
        error_msg = result.get("error", "导入过程中发生错误")
        messagebox.showerror("错误", error_msg)


# 向后兼容别名
ImportCsvTypeApp = ImportCsvTypePage