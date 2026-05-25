"""
重构后的 CSV 导入页面 - 使用新的基类和组件架构
"""

import os
import re
import tkinter as tk

from pypinyin import Style, lazy_pinyin

from core.importer_csv import import_csv_to_db
from core.importer_csv import logger as core_logger
from gui.base import BaseToolPage
from gui.components import ConnectionSelector, PathSelector
from gui.widgets.buttons import PrimaryButton
from gui.widgets.entries import StyledEntry
from gui.widgets.labels import StyledLabel, TitleLabel


class ImportCsvPage(BaseToolPage):
    """
    CSV 导入页面 - 重构版本

    使用 BaseToolPage 基类,提供:
    - 标准的左右面板布局
    - 连接管理功能
    - 配置管理功能
    - 日志记录功能
    - 线程执行功能
    """

    CONFIG_FILE = "~/.csv_importer_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 导入日志",
            core_logger=core_logger,
        )

    def setup_left_panel_content(self, parent):
        """设置左侧面板的具体内容"""
        # 标题
        title = TitleLabel(parent, text="📥 CSV 导入")
        title.pack(anchor="w", pady=(0, 15))

        # 数据库连接选择器
        self.connection_selector = ConnectionSelector(parent, label_text="数据库连接")
        self.connection_selector.pack(fill="x", pady=(0, 15))

        # 设置连接变量引用 (用于兼容 ConnectionMixin)
        self.connection_var = self.connection_selector.connection_var
        self.connection_menu = self.connection_selector.connection_menu

        # 数据源选择
        self.data_source_var = tk.StringVar(value="zip")
        source_label = self.ctk.CTkLabel(
            parent,
            text="数据源类型",
            font=("Microsoft YaHei", 11),
            text_color=self.idea_dark_colors["text_secondary"],
        )
        source_label.pack(anchor="w", pady=(0, 3))

        data_source_frame = self.ctk.CTkFrame(
            parent, fg_color=self.idea_dark_colors["card_bg"], corner_radius=8
        )
        data_source_frame.pack(anchor="w", fill="x", pady=(0, 15))

        # 内部容器,用于居中对齐单选按钮
        data_source_inner_frame = self.ctk.CTkFrame(
            data_source_frame, fg_color=self.idea_dark_colors["card_bg"]
        )
        data_source_inner_frame.pack(pady=15)

        self.zip_radio = self.ctk.CTkRadioButton(
            data_source_inner_frame,
            text="ZIP文件",
            variable=self.data_source_var,
            value="zip",
            command=self.toggle_data_source,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
        )
        self.zip_radio.pack(side="left", padx=(20, 30))

        self.folder_radio = self.ctk.CTkRadioButton(
            data_source_inner_frame,
            text="文件夹",
            variable=self.data_source_var,
            value="folder",
            command=self.toggle_data_source,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
        )
        self.folder_radio.pack(side="left")

        # 数据源路径选择器
        self.path_selector = PathSelector(parent, label_text="数据源路径", mode="zip")
        self.path_selector.pack(fill="x", pady=(0, 15))
        self.path_selector.set_callback(self.on_path_selected)

        # ZIP 密码
        self.zip_password_label = StyledLabel(parent, text="ZIP文件密码")
        self.zip_password_label.pack(anchor="w", pady=(0, 3))

        self.archive_password_var = tk.StringVar()
        self.zip_password_entry = StyledEntry(
            parent, textvariable=self.archive_password_var
        )
        self.zip_password_entry.pack(anchor="w", fill="x", pady=(0, 3))

        self.zip_password_optional = self.ctk.CTkLabel(
            parent,
            text="(可选,文件夹类型非必填)",
            font=("Microsoft YaHei", 9),
            text_color=self.idea_dark_colors["text_secondary"],
        )
        self.zip_password_optional.pack(anchor="w", pady=(0, 15))

        # 导入前执行 SQL
        sql_label = StyledLabel(parent, text="导入前SQL脚本")
        sql_label.pack(anchor="w", pady=(0, 3))

        self.pre_sql_selector = PathSelector(
            parent,
            label_text="",
            mode="file",
            file_types=[
                ("SQL文件", "*.sql"),
                ("文本文件", "*.txt"),
                ("所有文件", "*.*"),
            ],
        )
        self.pre_sql_selector.pack(fill="x", pady=(0, 15))

        # 导入选项
        options_checkbox_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        options_checkbox_frame.pack(anchor="w", pady=(0, 15))

        self.truncate_var = tk.BooleanVar(value=True)
        self.truncate_checkbox = self.ctk.CTkCheckBox(
            options_checkbox_frame,
            text="导入前清空表（TRUNCATE）",
            variable=self.truncate_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        )
        self.truncate_checkbox.pack(side="left", padx=(0, 20))

        self.backup_var = tk.BooleanVar(value=True)
        self.backup_checkbox = self.ctk.CTkCheckBox(
            options_checkbox_frame,
            text="导入前备份数据",
            variable=self.backup_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        )
        self.backup_checkbox.pack(side="left")

        # 开始导入按钮
        self.import_button = PrimaryButton(
            parent, text="🚀 开始导入", command=self.start_import
        )
        self.import_button.pack(anchor="w", fill="x", pady=(10, 0))

    def toggle_data_source(self):
        """切换数据源类型时更新控件状态"""
        source_type = self.data_source_var.get()
        if source_type == "zip":
            self.zip_password_entry.configure(state="normal")
            self.path_selector.mode = "zip"
        else:
            self.zip_password_entry.configure(state="disabled")
            self.path_selector.mode = "folder"

    def on_path_selected(self, path):
        """路径选择后的回调"""
        source_type = self.data_source_var.get()

        if source_type == "zip":
            # 自动识别密码 (如有)
            zip_name = os.path.splitext(os.path.basename(path))[0]
            password = self.get_zip_password(zip_name)
            if password:
                self.archive_password_var.set(password)
                if hasattr(self, "logger") and self.logger:
                    self.logger.info(f"根据文件名识别到ZIP密码: {password}")

        if hasattr(self, "logger") and self.logger:
            self.logger.info(
                f"已选择{'ZIP文件' if source_type == 'zip' else '文件夹'}: {path}"
            )

    def get_zip_password(self, zip_filename: str) -> str:
        """
        根据压缩包文件名推导密码
        规则: 城市前两个字的拼音首字母(大写) + its312 + 日期MMDD
        """
        # 提取城市名(假设文件名第一个汉字开始到 '大脑' 前)
        city_match = re.match(r"^([\u4e00-\u9fa5]{2,})", zip_filename)
        if not city_match:
            return ""
        city_name = city_match.group(1)[:2]  # 前两个字

        # 获取拼音首字母并转大写
        initials = "".join(
            [p[0].upper() for p in lazy_pinyin(city_name, style=Style.FIRST_LETTER)]
        )

        # 提取日期 (8位数字)
        date_match = re.search(r"(20\d{6})", zip_filename)
        if not date_match:
            return ""
        date_str = date_match.group(1)
        mmdd = date_str[4:]  # 取 MMDD

        return f"{initials}its312{mmdd}"

    def start_import(self):
        """开始导入 - 包装 run_task 方法"""
        self.run_task(
            button_widget=self.import_button,
            button_text="🚀 开始导入",
            running_text="导入中...",
        )

    def get_config_dict(self):
        """返回要保存的配置字典"""
        return {
            "selected_connection_name": self.get_selected_connection_name(),
            "data_source_type": self.data_source_var.get(),
            "pre_sql_file": self.pre_sql_selector.get_path(),
            "data_path": self.path_selector.get_path(),
            "archive_password": self.archive_password_var.get(),
            "truncate_before": self.truncate_var.get(),
            "need_backup": self.backup_var.get(),
        }

    def apply_config(self, config):
        """应用加载的配置"""
        # 连接选择
        selected_name = config.get("selected_connection_name")
        if selected_name:
            idx = self.find_connection_index_by_name(selected_name)
            if (
                idx is not None
                and hasattr(self, "connection_names")
                and 0 <= idx < len(self.connection_names)
            ):
                self.connection_selector.set_value(self.connection_names[idx])

        # 数据源类型
        data_source_type = config.get("data_source_type", "zip")
        self.data_source_var.set(data_source_type)
        self.toggle_data_source()

        # 路径
        self.pre_sql_selector.set_path(config.get("pre_sql_file", ""))
        self.path_selector.set_path(config.get("data_path", ""))

        # 其他设置
        self.archive_password_var.set(config.get("archive_password", ""))
        self.truncate_var.set(config.get("truncate_before", True))
        self.backup_var.set(config.get("need_backup", True))

    def execute_task(self):
        """执行导入任务"""
        # 获取当前选中的连接
        db_config = self.get_selected_connection()
        if not db_config:
            return {"success": False, "error": "请选择一个有效的数据库连接"}

        # 获取参数
        pre_sql_file = self.pre_sql_selector.get_path()
        data_path = self.path_selector.get_path()
        truncate_before = self.truncate_var.get()
        need_backup = self.backup_var.get()
        archive_password = self.archive_password_var.get().strip()
        source_type = self.data_source_var.get()

        # 验证参数
        if not data_path:
            return {"success": False, "error": "请选择CSV文件目录或ZIP压缩包"}

        if pre_sql_file and not os.path.exists(pre_sql_file):
            return {"success": False, "error": f"SQL脚本文件不存在: {pre_sql_file}"}

        if pre_sql_file and not pre_sql_file.lower().endswith((".sql", ".txt")):
            return {"success": False, "error": "只支持.sql和.txt格式的SQL脚本文件"}

        if source_type == "folder" and not os.path.isdir(data_path):
            return {"success": False, "error": "请选择有效的目录"}

        if source_type == "zip" and not (
            os.path.isfile(data_path) and data_path.lower().endswith(".zip")
        ):
            return {"success": False, "error": "请选择有效的.zip压缩包文件"}

        # 执行导入
        return import_csv_to_db(
            db_config=db_config,
            data_source=data_path,
            source_type=source_type,
            schema=db_config.get("schema", "public"),
            pre_sql_file=pre_sql_file if pre_sql_file else "",
            need_backup=need_backup,
            truncate_before=truncate_before,
            archive_password=archive_password if archive_password else None,
        )


# 兼容性别名 - 保持与原有代码的兼容性
ImportCsvApp = ImportCsvPage
