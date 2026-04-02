"""
数据迁移页面 - 支持 PostgreSQL / ClickHouse 同构及异构迁移
"""
import tkinter as tk
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import ConnectionSelector
from gui.widgets.labels import TitleLabel, StyledLabel  # StyledLabel used in table input label
from gui.widgets.buttons import PrimaryButton
from gui.widgets.scrolled_texts import StyledScrolledText
from core.migrator import migrate_tables
import logging

logger = logging.getLogger(__name__)


class MigratorPage(BaseToolPage):
    """
    数据迁移页面

    左侧：源库选择、目标库选择、表名输入、truncate 选项、开始按钮
    右侧：标准日志面板
    """

    CONFIG_FILE = "~/.db_migrator_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 迁移日志",
            core_logger=logger,
        )

    def setup_left_panel_content(self, parent):
        """设置左侧面板内容"""
        TitleLabel(parent, text="🔀 数据迁移").pack(anchor="w", pady=(0, 15))

        # 源数据库连接
        self.src_selector = ConnectionSelector(parent, label_text="源数据库连接")
        self.src_selector.pack(fill="x", pady=(0, 10))

        # 目标数据库连接
        self.dst_selector = ConnectionSelector(parent, label_text="目标数据库连接")
        self.dst_selector.pack(fill="x", pady=(0, 15))

        # 兼容 ConnectionMixin 引用（以 src 为默认连接引用）
        self.connection_var = self.src_selector.connection_var
        self.connection_menu = self.src_selector.connection_menu

        # 表名输入
        StyledLabel(parent, text="迁移的表名（多个表可用逗号分隔）").pack(
            anchor="w", pady=(0, 3)
        )
        table_container = self.ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8,
        )
        table_container.pack(fill="both", pady=(0, 15))
        self.text_tables = StyledScrolledText(table_container)
        self.text_tables.pack(fill="both", expand=True, padx=5, pady=5)
        self.text_tables.configure(height=10)

        # TRUNCATE 选项
        truncate_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        truncate_frame.pack(anchor="w", pady=(0, 15))
        self.truncate_var = tk.BooleanVar(value=True)
        self.ctk.CTkCheckBox(
            truncate_frame,
            text="迁移前清空目标表（TRUNCATE）",
            variable=self.truncate_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        ).pack(side="left")

        # 开始迁移按钮
        self.migrate_button = PrimaryButton(
            parent,
            text="🚀 开始迁移",
            command=self.start_task,
        )
        self.migrate_button.pack(anchor="w", fill="x", pady=(10, 0))

    def get_config_dict(self):
        """返回要保存的配置字典"""
        return {
            "src_connection_name": self.src_selector.connection_var.get(),
            "dst_connection_name": self.dst_selector.connection_var.get(),
            "table_names": self.text_tables.get("1.0", tk.END).strip(),
            "truncate_before": self.truncate_var.get(),
        }

    def apply_config(self, config):
        """应用加载的配置"""
        try:
            src_name = config.get("src_connection_name", "")
            if src_name:
                self.src_selector.set_value(src_name)

            dst_name = config.get("dst_connection_name", "")
            if dst_name:
                self.dst_selector.set_value(dst_name)

            table_names = config.get("table_names", "")
            self.text_tables.delete("1.0", tk.END)
            self.text_tables.insert(tk.END, table_names)

            self.truncate_var.set(config.get("truncate_before", True))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {e}")

    def update_connections_combobox(self):
        """重写：同时刷新源库和目标库两个下拉框"""
        super().update_connections_combobox()
        # dst_selector 在 setup_left_panel_content 之后才存在
        if not hasattr(self, "dst_selector"):
            return
        if not self.connections:
            self.dst_selector.set_values(["无可用连接"])
            return
        names = [
            f"{c.get('name', '未命名连接')} ({c.get('host', '')}:{c.get('port', '')})"
            for c in self.connections
        ]
        current = self.dst_selector.connection_var.get()
        self.dst_selector.connection_menu.configure(values=names)
        if current in names:
            self.dst_selector.connection_menu.set(current)
        else:
            self.dst_selector.connection_menu.set(names[0])
            self.dst_selector.connection_var.set(names[0])

    def _get_connection_config_by_selector(self, selector):
        """根据 selector 的选中值查找连接配置"""
        selected = selector.connection_var.get()
        if not selected or selected in ("", "无可用连接"):
            return None
        for conn in self.connections:
            label = f"{conn.get('name', '未命名连接')} ({conn.get('host', '')}:{conn.get('port', '')})"
            if label == selected:
                return conn
        return None

    def start_task(self):
        """启动迁移任务"""
        self.run_task(
            button_widget=self.migrate_button,
            button_text="🚀 开始迁移",
            running_text="迁移中...",
        )

    def execute_task(self):
        """在后台线程中执行迁移"""
        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        src_config = self._get_connection_config_by_selector(self.src_selector)
        dst_config = self._get_connection_config_by_selector(self.dst_selector)

        if src_config is None:
            return {"success": False, "error": "请选择源数据库连接"}
        if dst_config is None:
            return {"success": False, "error": "请选择目标数据库连接"}

        raw = self.text_tables.get("1.0", tk.END).strip()
        table_names = []
        for line in raw.split("\n"):
            table_names.extend([t.strip() for t in line.split(",") if t.strip()])

        truncate_before = self.truncate_var.get()

        if self.logger:
            self.logger.info(
                f"开始数据迁移: {src_config.get('name')} → {dst_config.get('name')}"
            )
            self.logger.info(f"迁移表: {', '.join(table_names)}")
            self.logger.info(f"迁移前清空目标表: {truncate_before}")

        result = migrate_tables(
            src_config=src_config,
            dst_config=dst_config,
            table_names=table_names,
            truncate_before=truncate_before,
            logger=self.logger,
        )

        if result.get("success"):
            if self.logger:
                self.logger.info(
                    f"迁移完成: 成功 {len(result['migrated_tables'])} 张表，"
                    f"共 {result['total_rows']} 行"
                )
        else:
            failed = result.get("error_tables", [])
            if self.logger:
                self.logger.error(
                    f"迁移结束: 成功 {len(result['migrated_tables'])} 张，"
                    f"失败 {len(failed)} 张"
                )

        return result

    def validate(self):
        """验证输入"""
        raw = self.text_tables.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showerror("错误", "请输入要迁移的表名")
            return False
        return True

    def on_task_success(self, result):
        messagebox.showinfo("完成", f"数据迁移成功！共迁移 {result['total_rows']} 行数据。")

    def on_task_error(self, result):
        error_tables = result.get("error_tables", [])
        if error_tables:
            detail = "\n".join(
                f"• {t['name']}: {t['error']}" for t in error_tables
            )
            messagebox.showerror("部分表迁移失败", f"以下表迁移失败：\n{detail}")
        else:
            messagebox.showerror("错误", result.get("error", "迁移过程中发生错误"))
