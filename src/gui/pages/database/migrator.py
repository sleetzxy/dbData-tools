"""
数据迁移页面 - 支持 PostgreSQL / ClickHouse 同构及异构迁移

支持条件迁移（WHERE/SQL 双模）、分块迁移、断点续传。
"""

import re
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core.migration.models import MigrationCondition
from core.migration.resume_manager import ResumeManager
from core.migrator import logger as core_logger
from core.migrator import migrate_tables
from gui.base import BaseToolPage
from gui.components import ConnectionSelector
from gui.widgets.buttons import PrimaryButton, StyledButton
from gui.widgets.labels import StyledLabel, TitleLabel


class _TableCard:
    """单张表的迁移配置卡片（可折叠）。"""

    _TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def __init__(
        self, parent, index: int, on_remove, colors: dict, table_name: str = ""
    ) -> None:
        self.index = index
        self.on_remove = on_remove
        self.colors = colors
        self.expanded = False

        # ---- 折叠行头部 ----
        self.header = ctk.CTkFrame(parent, fg_color=colors["card_bg"], corner_radius=6)
        self.header.pack(fill="x", pady=(4, 0))

        # 表名输入
        self.name_var = tk.StringVar(value=table_name)
        self.name_entry = ctk.CTkEntry(
            self.header,
            textvariable=self.name_var,
            placeholder_text=f"表名 #{index + 1}",
            font=("Microsoft YaHei", 11),
            height=30,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)

        # 展开/折叠
        self.expand_btn = ctk.CTkButton(
            self.header,
            text="▸",
            width=28,
            height=28,
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color=colors["button_hover"],
            text_color=colors["text_primary"],
            command=self._toggle,
        )
        self.expand_btn.pack(side="left", padx=1, pady=4)

        # 删除
        self.del_btn = ctk.CTkButton(
            self.header,
            text="×",
            width=28,
            height=28,
            font=("Segoe UI", 13, "bold"),
            fg_color="transparent",
            hover_color="#8B0000",
            text_color=colors["text_secondary"],
            command=self._remove,
        )
        self.del_btn.pack(side="left", padx=(1, 8), pady=4)

        # ---- 展开面板（默认隐藏） ----
        self.panel = ctk.CTkFrame(parent, fg_color=colors["card_bg"], corner_radius=6)
        self._panel_widgets: dict[str, tk.Widget] = {}

        # 模式选择
        mode_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        mode_frame.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            mode_frame,
            text="模式",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 8))
        self.mode_var = tk.StringVar(value="where")
        self.mode_where = ctk.CTkRadioButton(
            mode_frame,
            text="条件",
            variable=self.mode_var,
            value="where",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_primary"],
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            border_color=colors["border"],
            command=self._on_mode_change,
        )
        self.mode_where.pack(side="left", padx=(0, 12))
        self.mode_sql = ctk.CTkRadioButton(
            mode_frame,
            text="自定义 SQL",
            variable=self.mode_var,
            value="sql",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_primary"],
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            border_color=colors["border"],
            command=self._on_mode_change,
        )
        self.mode_sql.pack(side="left")

        # 条件/SQL 输入
        self.cond_label = ctk.CTkLabel(
            self.panel,
            text="WHERE 子句（不含 WHERE 关键字）",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
            anchor="w",
        )
        self.cond_label.pack(fill="x", padx=12, pady=(6, 2))
        self.cond_entry = ctk.CTkEntry(
            self.panel,
            placeholder_text="例: status = 'active' AND amount > 100",
            font=("Consolas", 10),
            height=28,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.cond_entry.pack(fill="x", padx=12)

        # 分块键
        chunk_key_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        chunk_key_frame.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(
            chunk_key_frame,
            text="分块键",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 8))
        self.chunk_key_var = tk.StringVar()
        self.chunk_key_entry = ctk.CTkEntry(
            chunk_key_frame,
            textvariable=self.chunk_key_var,
            placeholder_text="空=自动检测主键",
            font=("Consolas", 10),
            height=28,
            width=120,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.chunk_key_entry.pack(side="left", fill="x", expand=True)

        # 分块行数
        ctk.CTkLabel(
            chunk_key_frame,
            text="块行数",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(10, 4))
        self.chunk_size_var = tk.StringVar()
        self.chunk_size_entry = ctk.CTkEntry(
            chunk_key_frame,
            textvariable=self.chunk_size_var,
            placeholder_text="100000",
            font=("Consolas", 10),
            height=28,
            width=70,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.chunk_size_entry.pack(side="left")

        self._on_mode_change()

    def _toggle(self) -> None:
        self.expanded = not self.expanded
        self.expand_btn.configure(text="▾" if self.expanded else "▸")
        if self.expanded:
            self.panel.pack(fill="x", after=self.header, pady=(0, 0))
        else:
            self.panel.pack_forget()

    def _remove(self) -> None:
        self.header.pack_forget()
        self.panel.pack_forget()
        self.on_remove(self)

    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        if mode == "where":
            self.cond_label.configure(text="WHERE 子句（不含 WHERE 关键字）")
            self.cond_entry.configure(
                placeholder_text="例: status = 'active' AND amount > 100", height=28
            )
            self.chunk_key_entry.configure(border_color=self.colors["border"])
        else:
            self.cond_label.configure(text="自定义 SQL（完整 SELECT 语句）")
            self.cond_entry.configure(
                placeholder_text="例: SELECT * FROM orders WHERE status = 'paid'",
                height=60,
            )
            self._update_chunk_key_hint()

    def _update_chunk_key_hint(self) -> None:
        """SQL 模式下 chunk_key 为空时红色提示。"""
        if self.mode_var.get() == "sql" and not self.chunk_key_var.get().strip():
            self.chunk_key_entry.configure(border_color=self.colors["error"])
        else:
            self.chunk_key_entry.configure(border_color=self.colors["border"])

    def bind_chunk_key_trace(self) -> None:
        self.chunk_key_var.trace_add("write", lambda *_: self._update_chunk_key_hint())

    def to_condition(self) -> MigrationCondition | None:
        name = self.name_var.get().strip()
        if not name or not self._TABLE_NAME_RE.match(name):
            return None
        mode = self.mode_var.get()
        chunk_size_str = self.chunk_size_var.get().strip()
        chunk_size = int(chunk_size_str) if chunk_size_str.isdigit() else 100_000
        return MigrationCondition(
            table_name=name,
            mode=mode,  # type: ignore[arg-type]
            where_clause=self.cond_entry.get().strip() if mode == "where" else "",
            custom_sql=self.cond_entry.get().strip() if mode == "sql" else "",
            chunk_key=self.chunk_key_var.get().strip(),
            chunk_size=chunk_size,
            enabled=True,
        )

    def configure(self, cond: MigrationCondition) -> None:
        self.name_var.set(cond.table_name)
        self.mode_var.set(cond.mode)
        self.cond_entry.delete(0, "end")
        cond_text = cond.custom_sql if cond.mode == "sql" else cond.where_clause
        self.cond_entry.insert(0, cond_text)
        self.chunk_key_var.set(cond.chunk_key)
        if cond.chunk_size != 100_000:
            self.chunk_size_var.set(str(cond.chunk_size))
        self._on_mode_change()

    @property
    def table_name(self) -> str:
        return self.name_var.get().strip()


class MigratorPage(BaseToolPage):
    """数据迁移页面

    左侧：源库/目标库选择器、表配置列表（条件/分块）、进度条、操作按钮
    右侧：标准日志面板
    """

    CONFIG_FILE = "~/.db_migrator_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 迁移日志",
            core_logger=core_logger,
        )
        self._table_cards: list[_TableCard] = []
        self._running = False
        self._paused = False
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_label_var = tk.StringVar(value="")

    # ------------------------------------------------------------------
    # 左侧面板
    # ------------------------------------------------------------------

    def setup_left_panel_content(self, parent):
        TitleLabel(parent, text="🔀 数据迁移").pack(anchor="w", pady=(0, 12))

        # 源数据库连接
        self.src_selector = ConnectionSelector(parent, label_text="源数据库连接")
        self.src_selector.pack(fill="x", pady=(0, 8))

        # 目标数据库连接
        self.dst_selector = ConnectionSelector(parent, label_text="目标数据库连接")
        self.dst_selector.pack(fill="x", pady=(0, 12))

        # 兼容 ConnectionMixin
        self.connection_var = self.src_selector.connection_var
        self.connection_menu = self.src_selector.connection_menu

        # ---- 全局设置 ----
        settings_frame = self.ctk.CTkFrame(
            parent, fg_color=self.idea_dark_colors["card_bg"], corner_radius=8
        )
        settings_frame.pack(fill="x", pady=(0, 10))

        # TRUNCATE
        trunc_row = self.ctk.CTkFrame(settings_frame, fg_color="transparent")
        trunc_row.pack(fill="x", padx=10, pady=(8, 2))
        self.truncate_var = tk.BooleanVar(value=True)
        self.ctk.CTkCheckBox(
            trunc_row,
            text="迁移前清空目标表（TRUNCATE）",
            variable=self.truncate_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        ).pack(side="left")

        # 默认分块行数
        chunk_row = self.ctk.CTkFrame(settings_frame, fg_color="transparent")
        chunk_row.pack(fill="x", padx=10, pady=(0, 8))
        StyledLabel(chunk_row, text="默认分块行数").pack(side="left", padx=(0, 6))
        self.default_chunk_var = tk.StringVar(value="100000")
        self.ctk.CTkEntry(
            chunk_row,
            textvariable=self.default_chunk_var,
            font=("Consolas", 10),
            height=26,
            width=80,
            fg_color=self.idea_dark_colors["bg"],
            border_color=self.idea_dark_colors["border"],
        ).pack(side="left")

        # ---- 表配置列表 ----
        table_header = self.ctk.CTkFrame(parent, fg_color="transparent")
        table_header.pack(fill="x", pady=(4, 4))
        StyledLabel(table_header, text="迁移表配置").pack(side="left")
        add_btn = StyledButton(
            table_header,
            text="＋ 添加表",
            command=self._add_table_row,
        )
        add_btn.pack(side="right")

        self._table_list = self.ctk.CTkFrame(parent, fg_color="transparent")
        self._table_list.pack(fill="both", pady=(0, 8))

        # ---- 进度条 ----
        progress_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        progress_frame.pack(fill="x", pady=(2, 6))
        self.progress_bar = self.ctk.CTkProgressBar(progress_frame, height=16)
        self.progress_bar.pack(fill="x", side="top")
        self.progress_bar.set(0.0)
        self.progress_label = self.ctk.CTkLabel(
            progress_frame,
            textvariable=self._progress_label_var,
            font=("Microsoft YaHei", 9),
            text_color=self.idea_dark_colors["text_secondary"],
        )
        self.progress_label.pack(anchor="e", pady=(1, 0))

        # ---- 按钮 ----
        btn_row = self.ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(4, 0))

        self.migrate_button = PrimaryButton(
            btn_row, text="🚀 开始迁移", command=self.start_task
        )
        self.migrate_button.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.stop_button = StyledButton(
            btn_row,
            text="⏹ 停止",
            command=self._stop_task,
        )
        self.stop_button.pack(side="left", padx=(0, 0))
        self.stop_button.configure(state="disabled")

        # 初始添加一行
        self._add_table_row()

    # ------------------------------------------------------------------
    # 表配置管理
    # ------------------------------------------------------------------

    def _add_table_row(self) -> _TableCard:
        card = _TableCard(
            self._table_list,
            index=len(self._table_cards),
            on_remove=self._remove_table_row,
            colors=self.idea_dark_colors,
        )
        card.bind_chunk_key_trace()
        self._table_cards.append(card)
        self._renumber_cards()
        return card

    def _remove_table_row(self, card: _TableCard) -> None:
        if card in self._table_cards:
            self._table_cards.remove(card)
        card.header.destroy()
        card.panel.destroy()
        self._renumber_cards()

    def _renumber_cards(self) -> None:
        for i, card in enumerate(self._table_cards):
            card.index = i
            card.name_entry.configure(placeholder_text=f"表名 #{i + 1}")

    def _collect_conditions(self) -> list[MigrationCondition]:
        conditions: list[MigrationCondition] = []
        seen: set[str] = set()
        for card in self._table_cards:
            cond = card.to_condition()
            if cond is None:
                continue
            if cond.table_name in seen:
                continue
            seen.add(cond.table_name)
            if not cond.chunk_size or cond.chunk_size <= 0:
                chunk_str = self.default_chunk_var.get().strip()
                cond.chunk_size = int(chunk_str) if chunk_str.isdigit() else 100_000
            conditions.append(cond)
        return conditions

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------

    def get_config_dict(self):
        return {
            "src_connection_name": self.src_selector.connection_var.get(),
            "dst_connection_name": self.dst_selector.connection_var.get(),
            "truncate_before": self.truncate_var.get(),
            "default_chunk_size": self.default_chunk_var.get(),
            "table_configs": [
                {
                    "table_name": c.table_name,
                    "mode": c.mode_var.get(),
                    "where_clause": c.cond_entry.get().strip()
                    if c.mode_var.get() == "where"
                    else "",
                    "custom_sql": c.cond_entry.get().strip()
                    if c.mode_var.get() == "sql"
                    else "",
                    "chunk_key": c.chunk_key_var.get().strip(),
                    "chunk_size": c.chunk_size_var.get().strip(),
                }
                for c in self._table_cards
                if c.table_name
            ],
        }

    def apply_config(self, config):
        try:
            src_name = config.get("src_connection_name", "")
            if src_name:
                self.src_selector.set_value(src_name)
            dst_name = config.get("dst_connection_name", "")
            if dst_name:
                self.dst_selector.set_value(dst_name)
            self.truncate_var.set(config.get("truncate_before", True))
            chunk_size = config.get("default_chunk_size", "100000")
            if chunk_size:
                self.default_chunk_var.set(str(chunk_size))

            table_configs = config.get("table_configs", [])
            if table_configs:
                # 清除默认卡片
                for card in list(self._table_cards):
                    self._remove_table_row(card)
                for tc in table_configs:
                    card = self._add_table_row()
                    card.name_var.set(tc.get("table_name", ""))
                    card.mode_var.set(tc.get("mode", "where"))
                    card.cond_entry.delete(0, "end")
                    card.cond_entry.insert(
                        0,
                        tc.get("custom_sql")
                        if tc.get("mode") == "sql"
                        else tc.get("where_clause", ""),
                    )
                    card.chunk_key_var.set(tc.get("chunk_key", ""))
                    card.chunk_size_var.set(str(tc.get("chunk_size", "")))
                    card._on_mode_change()

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {e}")

    def update_connections_combobox(self):
        super().update_connections_combobox()
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

    # ------------------------------------------------------------------
    # 任务控制
    # ------------------------------------------------------------------

    def start_task(self):
        """启动迁移任务，检查断点续传。"""
        self._running = True
        self._paused = False
        self._set_buttons_state("running")

        # 检查是否有未完成的断点
        resume_mgr = ResumeManager()
        incomplete = resume_mgr.list_incomplete()
        self._resume_id: str | None = None
        if incomplete:
            self._ask_resume(incomplete, resume_mgr)

        self.run_task(
            button_widget=self.migrate_button,
            button_text="🚀 开始迁移",
            running_text="迁移中...",
        )

    def _ask_resume(self, incomplete, resume_mgr) -> None:
        """弹出续传选择对话框。"""
        # 只取最近一个
        meta = incomplete[0]
        answer = messagebox.askyesnocancel(
            "断点续传",
            f"检测到未完成的迁移任务（{meta.migration_id[:8]}…），\n"
            f"创建于 {meta.created_at}\n\n"
            "• 是 — 从断点继续\n"
            "• 否 — 重新开始\n"
            "• 取消 — 留在当前页面",
        )
        if answer is True:
            self._resume_id = meta.migration_id
            if self.logger:
                self.logger.info("将从断点 %s 继续迁移", meta.migration_id[:8])
        elif answer is False:
            resume_mgr.delete(meta.migration_id)
            if self.logger:
                self.logger.info("已删除旧断点，开始全新迁移")
        else:
            self._running = False
            self._set_buttons_state("idle")
            raise RuntimeError("用户取消")

    def _stop_task(self) -> None:
        self._paused = True
        self._running = False
        self._set_buttons_state("idle")
        if self.logger:
            self.logger.warning("用户已请求停止迁移")

    def _set_buttons_state(self, state: str) -> None:
        if state == "running":
            self.migrate_button.configure(state="disabled", text="迁移中...")
            self.stop_button.configure(state="normal")
        else:
            self.migrate_button.configure(state="normal", text="🚀 开始迁移")
            self.stop_button.configure(state="disabled")

    def _get_connection_config_by_selector(self, selector):
        selected = selector.connection_var.get()
        if not selected or selected in ("", "无可用连接"):
            return None
        for conn in self.connections:
            label = (
                f"{conn.get('name', '未命名连接')} "
                f"({conn.get('host', '')}:{conn.get('port', '')})"
            )
            if label == selected:
                return conn
        return None

    # ------------------------------------------------------------------
    # 核心执行
    # ------------------------------------------------------------------

    def execute_task(self):
        if not self._running:
            return {"success": False, "error": "任务已取消"}

        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        src_config = self._get_connection_config_by_selector(self.src_selector)
        dst_config = self._get_connection_config_by_selector(self.dst_selector)
        if src_config is None:
            return {"success": False, "error": "请选择源数据库连接"}
        if dst_config is None:
            return {"success": False, "error": "请选择目标数据库连接"}

        conditions = self._collect_conditions()
        if not conditions:
            return {"success": False, "error": "没有有效的表配置"}

        truncate_before = self.truncate_var.get()

        if self.logger:
            self.logger.info(
                "开始数据迁移: %s → %s",
                src_config.get("name"), dst_config.get("name"),
            )
            self.logger.info("迁移表: %s", ", ".join(c.table_name for c in conditions))
            self.logger.info("迁移前清空目标表: %s", truncate_before)
            for c in conditions:
                chunk_hint = c.chunk_key or "自动"
                if c.mode == "sql":
                    self.logger.info(
                        "  %s: SQL 模式, chunk_key=%s", c.table_name, chunk_hint
                    )
                elif c.where_clause:
                    self.logger.info(
                        "  %s: 条件模式, WHERE=%s, chunk_key=%s",
                        c.table_name, c.where_clause, chunk_hint,
                    )
                else:
                    self.logger.info(
                        "  %s: 全表，chunk_key=%s", c.table_name, chunk_hint
                    )

        # 使用迁移核心（生产模式走 Orchestrator）
        result = migrate_tables(
            src_config=src_config,
            dst_config=dst_config,
            table_names=[c.table_name for c in conditions],
            truncate_before=truncate_before,
            logger=self.logger,
            conditions=conditions,
        )

        if result.get("success"):
            if self.logger:
                self.logger.info(
                    "迁移完成: 成功 %d 张表，共 %d 行",
                    len(result["migrated_tables"]), result["total_rows"],
                )
        else:
            failed = result.get("error_tables", [])
            if self.logger:
                self.logger.error(
                    "迁移结束: 成功 %d 张，失败 %d 张",
                    len(result["migrated_tables"]), len(failed),
                )

        return result

    def validate(self):
        if not self._table_cards or all(
            not c.table_name for c in self._table_cards
        ):
            messagebox.showerror("错误", "请至少添加一个有效的表名")
            return False
        for card in self._table_cards:
            if not card.table_name:
                continue
            if card.mode_var.get() == "sql":
                sql = card.cond_entry.get().strip()
                if not sql:
                    messagebox.showerror(
                        "错误", f"表 {card.table_name} 选择了 SQL 模式，但未输入 SQL"
                    )
                    return False
                if not card.chunk_key_var.get().strip():
                    messagebox.showerror(
                        "错误",
                        f"表 {card.table_name} SQL 模式必须指定 chunk_key",
                    )
                    return False
        return True

    def on_task_success(self, result):
        self._set_buttons_state("idle")
        self.progress_bar.set(1.0)
        self._progress_label_var.set("完成")
        messagebox.showinfo(
            "完成", f"数据迁移成功！共迁移 {result['total_rows']} 行数据。"
        )

    def on_task_error(self, result):
        self._set_buttons_state("idle")
        error_tables = result.get("error_tables", [])
        if error_tables:
            detail = "\n".join(f"• {t['name']}: {t['error']}" for t in error_tables)
            messagebox.showerror("部分表迁移失败", f"以下表迁移失败：\n{detail}")
        else:
            messagebox.showerror("错误", result.get("error", "迁移过程中发生错误"))
