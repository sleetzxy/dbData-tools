"""
数据迁移页面 - 支持 PostgreSQL / ClickHouse 同构及异构迁移

支持条件迁移（WHERE/SQL 双模）、分块迁移、断点续传。
"""

import re
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core.migration.config_compat import (
    apply_split_to_condition,
    split_config_from_dict,
    split_config_to_dict,
)
from core.migration.models import BindType, MigrationCondition, SplitMode, TransferMode
from core.migration.resume_manager import ResumeManager
from core.migration.split_strategy import compute_split_chunks
from core.migrator import logger as core_logger
from core.migrator import migrate_tables
from gui.base import BaseToolPage
from gui.components import ConnectionSelector
from gui.widgets.buttons import PrimaryButton, StyledButton
from gui.widgets.labels import StyledLabel, TitleLabel

_VALUE_FORMATS = ("yyyy-MM-dd", "yyyyMMdd", "yyyyMM", "yyyy")
_SPLIT_MODE_OPTIONS = (
    (SplitMode.CALENDAR.value, "日历"),
    (SplitMode.PARTITION_VALUE.value, "分区值"),
    (SplitMode.PHYSICAL_PARTITION.value, "物理分区"),
    (SplitMode.KEY_RANGE.value, "主键-高级"),
)
_BIND_TYPE_OPTIONS = (
    (BindType.COLUMN.value, "列名"),
    (BindType.EXPRESSION.value, "表达式"),
    (BindType.NAME_TEMPLATE.value, "名称模板"),
    (BindType.METADATA_LIST.value, "元数据列表"),
)


def _granularity_from_format(fmt: str) -> str:
    if fmt == "yyyy":
        return "year"
    if fmt == "yyyyMM":
        return "month"
    return "day"


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

        # 源表名输入
        self.name_var = tk.StringVar(value=table_name)
        self.name_entry = ctk.CTkEntry(
            self.header,
            textvariable=self.name_var,
            placeholder_text=f"源表名 #{index + 1}",
            font=("Microsoft YaHei", 11),
            height=30,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)

        # 目标表名输入
        self.target_var = tk.StringVar()
        self.target_entry = ctk.CTkEntry(
            self.header,
            textvariable=self.target_var,
            placeholder_text="目标表名（空=同源）",
            font=("Microsoft YaHei", 11),
            height=30,
            width=140,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.target_entry.pack(side="left", padx=(0, 4), pady=4)

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

        # 模式选择（WHERE / 自定义 SQL）
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

        self.cond_label = ctk.CTkLabel(
            self.panel,
            text="WHERE 子句（可选）",
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

        self._add_step_label("① 范围")
        range_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        range_frame.pack(fill="x", padx=12, pady=(2, 4))
        self.range_start_var = tk.StringVar()
        self.range_end_var = tk.StringVar()
        ctk.CTkLabel(
            range_frame,
            text="起",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 4))
        self.range_start_entry = ctk.CTkEntry(
            range_frame,
            textvariable=self.range_start_var,
            placeholder_text="20240101",
            font=("Consolas", 10),
            height=28,
            width=100,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.range_start_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            range_frame,
            text="止",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 4))
        self.range_end_entry = ctk.CTkEntry(
            range_frame,
            textvariable=self.range_end_var,
            placeholder_text="20240131",
            font=("Consolas", 10),
            height=28,
            width=100,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.range_end_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            range_frame,
            text="格式",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 4))
        self.value_format_var = tk.StringVar(value="yyyyMMdd")
        self.value_format_menu = ctk.CTkComboBox(
            range_frame,
            variable=self.value_format_var,
            values=list(_VALUE_FORMATS),
            font=("Consolas", 10),
            height=28,
            width=110,
            fg_color=colors["bg"],
            border_color=colors["border"],
            button_color=colors["accent"],
            button_hover_color=colors["accent_hover"],
            dropdown_fg_color=colors["card_bg"],
            command=lambda _v: self._schedule_preview(),
        )
        self.value_format_menu.pack(side="left")

        self._add_step_label("② 分块模式")
        split_mode_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        split_mode_frame.pack(fill="x", padx=12, pady=(2, 4))
        self.split_mode_var = tk.StringVar(value=SplitMode.PARTITION_VALUE.value)
        for idx, (mode_value, label) in enumerate(_SPLIT_MODE_OPTIONS):
            ctk.CTkRadioButton(
                split_mode_frame,
                text=label,
                variable=self.split_mode_var,
                value=mode_value,
                font=("Microsoft YaHei", 10),
                text_color=colors["text_primary"],
                fg_color=colors["accent"],
                hover_color=colors["accent_hover"],
                border_color=colors["border"],
                command=self._on_split_mode_change,
            ).pack(
                side="left",
                padx=(0, 10 if idx < len(_SPLIT_MODE_OPTIONS) - 1 else 0),
            )

        self._add_step_label("③ 绑定")
        self.binding_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        self.binding_frame.pack(fill="x", padx=12, pady=(2, 4))

        bind_type_row = ctk.CTkFrame(self.binding_frame, fg_color="transparent")
        bind_type_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            bind_type_row,
            text="类型",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 6))
        self.bind_type_var = tk.StringVar(value=BindType.COLUMN.value)
        self.bind_type_menu = ctk.CTkComboBox(
            bind_type_row,
            values=[label for _, label in _BIND_TYPE_OPTIONS[:3]],
            font=("Microsoft YaHei", 10),
            height=28,
            width=120,
            fg_color=colors["bg"],
            border_color=colors["border"],
            button_color=colors["accent"],
            button_hover_color=colors["accent_hover"],
            dropdown_fg_color=colors["card_bg"],
            command=self._on_bind_type_menu_change,
        )
        self.bind_type_menu.set(self._bind_type_value_to_label(BindType.COLUMN.value))
        self.bind_type_menu.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            bind_type_row,
            text="目标",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 6))
        self.bind_target_var = tk.StringVar()
        self.bind_target_entry = ctk.CTkEntry(
            bind_type_row,
            textvariable=self.bind_target_var,
            placeholder_text="列名 / 表达式 / 模板 orders_{yyyyMMdd}",
            font=("Consolas", 10),
            height=28,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.bind_target_entry.pack(side="left", fill="x", expand=True)

        self.key_range_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        ctk.CTkLabel(
            self.key_range_frame,
            text="分块键",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 8))
        self.chunk_key_var = tk.StringVar()
        self.chunk_key_entry = ctk.CTkEntry(
            self.key_range_frame,
            textvariable=self.chunk_key_var,
            placeholder_text="空=自动检测主键",
            font=("Consolas", 10),
            height=28,
            width=120,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.chunk_key_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            self.key_range_frame,
            text="块行数",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(10, 4))
        self.chunk_size_var = tk.StringVar()
        self.chunk_size_entry = ctk.CTkEntry(
            self.key_range_frame,
            textvariable=self.chunk_size_var,
            placeholder_text="100000",
            font=("Consolas", 10),
            height=28,
            width=70,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.chunk_size_entry.pack(side="left")

        self._add_step_label("④ 批量")
        batch_frame = ctk.CTkFrame(self.panel, fg_color="transparent")
        batch_frame.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(
            batch_frame,
            text="每批分区/天/月数",
            font=("Microsoft YaHei", 10),
            text_color=colors["text_secondary"],
        ).pack(side="left", padx=(0, 6))
        self.batch_size_var = tk.StringVar(value="1")
        self.batch_size_entry = ctk.CTkEntry(
            batch_frame,
            textvariable=self.batch_size_var,
            placeholder_text="1",
            font=("Consolas", 10),
            height=28,
            width=60,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.batch_size_entry.pack(side="left")
        self.preview_label = ctk.CTkLabel(
            self.panel,
            text="预览：填写范围后可查看分块",
            font=("Microsoft YaHei", 9),
            text_color=colors["text_secondary"],
            anchor="w",
            justify="left",
            wraplength=420,
        )
        self.preview_label.pack(fill="x", padx=12, pady=(0, 4))

        self._add_step_label("⑤ 额外过滤（可选）")
        self.extra_where_var = tk.StringVar()
        self.extra_where_entry = ctk.CTkEntry(
            self.panel,
            textvariable=self.extra_where_var,
            placeholder_text="例: dt >= '2024-01-01' AND dt < '2024-02-01'",
            font=("Consolas", 10),
            height=28,
            fg_color=colors["bg"],
            border_color=colors["border"],
        )
        self.extra_where_entry.pack(fill="x", padx=12, pady=(2, 8))

        self._preview_job: str | None = None
        self._bind_preview_traces()
        self._on_split_mode_change()
        self._on_mode_change()

    def _add_step_label(self, text: str) -> None:
        ctk.CTkLabel(
            self.panel,
            text=text,
            font=("Microsoft YaHei", 10, "bold"),
            text_color=self.colors["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 2))

    def _bind_type_label_to_value(self, label: str) -> str:
        for value, display in _BIND_TYPE_OPTIONS:
            if display == label:
                return value
        return label

    def _bind_type_value_to_label(self, value: str) -> str:
        for bind_value, display in _BIND_TYPE_OPTIONS:
            if bind_value == value:
                return display
        return value

    def _on_bind_type_menu_change(self, _choice: str) -> None:
        self.bind_type_var.set(self._bind_type_label_to_value(_choice))
        self._schedule_preview()

    def _bind_preview_traces(self) -> None:
        for var in (
            self.range_start_var,
            self.range_end_var,
            self.bind_target_var,
            self.batch_size_var,
            self.extra_where_var,
            self.chunk_key_var,
            self.chunk_size_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_preview())
        self.cond_entry.bind("<KeyRelease>", lambda _e: self._schedule_preview())

    def _schedule_preview(self) -> None:
        if self._preview_job is not None:
            try:
                self.panel.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.panel.after(300, self._update_preview)

    def _on_split_mode_change(self) -> None:
        mode = self.split_mode_var.get()
        is_key_range = mode == SplitMode.KEY_RANGE.value
        is_physical = mode == SplitMode.PHYSICAL_PARTITION.value

        if is_key_range:
            self.binding_frame.pack_forget()
            self.key_range_frame.pack(fill="x", padx=12, pady=(2, 4))
        else:
            self.key_range_frame.pack_forget()
            self.binding_frame.pack(fill="x", padx=12, pady=(2, 4))
            bind_labels = (
                [label for _, label in _BIND_TYPE_OPTIONS]
                if is_physical
                else [label for _, label in _BIND_TYPE_OPTIONS[:3]]
            )
            current = self._bind_type_value_to_label(self.bind_type_var.get())
            if current not in bind_labels:
                self.bind_type_var.set(BindType.COLUMN.value)
                current = self._bind_type_value_to_label(BindType.COLUMN.value)
            self.bind_type_menu.configure(values=bind_labels)
            self.bind_type_menu.set(current)

        self._update_chunk_key_hint()
        self._schedule_preview()

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
            self.cond_label.configure(text="WHERE 子句（可选）")
            self.cond_entry.configure(
                placeholder_text="例: status = 'active' AND amount > 100", height=28
            )
        else:
            self.cond_label.configure(text="自定义 SQL（完整 SELECT 语句）")
            self.cond_entry.configure(
                placeholder_text="例: SELECT * FROM orders WHERE status = 'paid'",
                height=60,
            )
        self._update_chunk_key_hint()

    def _update_chunk_key_hint(self) -> None:
        """SQL + 主键分块模式下 chunk_key 为空时红色提示。"""
        needs_key = (
            self.mode_var.get() == "sql"
            and self.split_mode_var.get() == SplitMode.KEY_RANGE.value
            and not self.chunk_key_var.get().strip()
        )
        border = self.colors["error"] if needs_key else self.colors["border"]
        self.chunk_key_entry.configure(border_color=border)

    def bind_chunk_key_trace(self) -> None:
        self.chunk_key_var.trace_add("write", lambda *_: self._update_chunk_key_hint())

    def _build_split_dict(self) -> dict[str, object]:
        fmt = self.value_format_var.get()
        batch_raw = self.batch_size_var.get().strip()
        batch_size = int(batch_raw) if batch_raw.isdigit() else 1
        return {
            "mode": self.split_mode_var.get(),
            "range_start": self.range_start_var.get().strip(),
            "range_end": self.range_end_var.get().strip(),
            "value_format": fmt,
            "granularity": _granularity_from_format(fmt),
            "bind_type": self._bind_type_label_to_value(self.bind_type_menu.get()),
            "bind_target": self.bind_target_var.get().strip(),
            "batch_size": batch_size,
            "extra_where": self.extra_where_var.get().strip(),
        }

    def _update_preview(self) -> None:
        self._preview_job = None
        mode = self.split_mode_var.get()
        if mode == SplitMode.KEY_RANGE.value:
            self.preview_label.configure(
                text="预览：主键分块模式，运行时按块行数拆分"
            )
            return

        split = split_config_from_dict(self._build_split_dict())
        if not split.range_start.strip() or not split.range_end.strip():
            self.preview_label.configure(text="预览：填写起止范围后可查看分块")
            return

        try:
            chunks = compute_split_chunks(split)
        except NotImplementedError:
            self.preview_label.configure(
                text="预览：物理分区（元数据列表）需连接数据库后才能预览"
            )
            return
        except ValueError as exc:
            self.preview_label.configure(text=f"预览：{exc}")
            return

        labels = [chunk.label or f"#{chunk.chunk_index}" for chunk in chunks[:3]]
        preview_text = "、".join(labels)
        if len(chunks) > 3:
            preview_text = f"{preview_text} …"
        self.preview_label.configure(
            text=f"预览：共 {len(chunks)} 个任务 — {preview_text}"
        )

    def to_condition(self) -> MigrationCondition | None:
        name = self.name_var.get().strip()
        if not name or not self._TABLE_NAME_RE.match(name):
            return None
        mode = self.mode_var.get()
        chunk_size_str = self.chunk_size_var.get().strip()
        chunk_size = int(chunk_size_str) if chunk_size_str.isdigit() else 100_000
        extra_where = self.extra_where_var.get().strip()
        where_text = self.cond_entry.get().strip() if mode == "where" else ""

        base = MigrationCondition(
            table_name=name,
            target_table=self.target_var.get().strip(),
            mode=mode,  # type: ignore[arg-type]
            where_clause=where_text,
            custom_sql=self.cond_entry.get().strip() if mode == "sql" else "",
            chunk_key=self.chunk_key_var.get().strip(),
            chunk_size=chunk_size,
            enabled=True,
        )
        cond = apply_split_to_condition(base, self._build_split_dict())
        if extra_where and mode == "where" and not where_text:
            cond = MigrationCondition(
                table_name=cond.table_name,
                target_table=cond.target_table,
                mode=cond.mode,
                where_clause=extra_where,
                custom_sql=cond.custom_sql,
                chunk_key=cond.chunk_key,
                chunk_size=cond.chunk_size,
                enabled=cond.enabled,
                split=cond.split,
            )
        return cond

    def _load_split_fields(self, split_dict: dict) -> None:
        split = split_config_from_dict(split_dict)
        self.range_start_var.set(split.range_start)
        self.range_end_var.set(split.range_end)
        self.value_format_var.set(split.value_format)
        self.split_mode_var.set(split.mode.value)
        self.bind_type_var.set(split.bind_type.value)
        self.bind_type_menu.set(self._bind_type_value_to_label(split.bind_type.value))
        self.bind_target_var.set(split.bind_target)
        self.batch_size_var.set(str(split.batch_size))
        self.extra_where_var.set(split.extra_where)

    def configure(self, cond: MigrationCondition) -> None:
        self.name_var.set(cond.table_name)
        self.target_var.set(cond.target_table)
        self.mode_var.set(cond.mode)
        self.cond_entry.delete(0, "end")
        cond_text = cond.custom_sql if cond.mode == "sql" else cond.where_clause
        if cond.mode == "where" and cond.split.extra_where:
            if cond_text == cond.split.extra_where:
                cond_text = ""
            elif cond.split.extra_where in cond_text:
                cond_text = cond_text.replace(cond.split.extra_where, "").strip()
        self.cond_entry.insert(0, cond_text)
        self.chunk_key_var.set(cond.chunk_key)
        if cond.chunk_size != 100_000:
            self.chunk_size_var.set(str(cond.chunk_size))
        self._load_split_fields(split_config_to_dict(cond.split))
        self._on_split_mode_change()
        self._on_mode_change()
        self._update_preview()

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
        # 先初始化 setup_left_panel_content 中引用的属性
        self._table_cards: list[_TableCard] = []
        self._running = False
        self._paused = False
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_label_var = tk.StringVar(value="")

        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 迁移日志",
            core_logger=core_logger,
        )

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

        # 传输模式
        mode_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=(0, 8))
        StyledLabel(mode_row, text="传输模式").pack(side="left", padx=(0, 8))
        self.transfer_mode_var = tk.StringVar(value="stream")
        ctk.CTkRadioButton(
            mode_row, text="流式", variable=self.transfer_mode_var, value="stream",
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["accent"],
            hover_color=self.idea_dark_colors["accent_hover"],
            border_color=self.idea_dark_colors["border"],
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            mode_row, text="CSV", variable=self.transfer_mode_var, value="csv",
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["accent"],
            hover_color=self.idea_dark_colors["accent_hover"],
            border_color=self.idea_dark_colors["border"],
        ).pack(side="left")

        # 流式内存上限
        memory_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        memory_row.pack(fill="x", padx=10, pady=(0, 8))
        StyledLabel(memory_row, text="内存上限 (MB)").pack(side="left", padx=(0, 6))
        self.memory_limit_var = tk.StringVar(value="512")
        self.ctk.CTkEntry(
            memory_row,
            textvariable=self.memory_limit_var,
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
            card.name_entry.configure(placeholder_text=f"源表名 #{i + 1}")

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
            if (
                cond.split.mode == SplitMode.KEY_RANGE
                and (not cond.chunk_size or cond.chunk_size <= 0)
            ):
                chunk_str = self.default_chunk_var.get().strip()
                cond.chunk_size = int(chunk_str) if chunk_str.isdigit() else 100_000
            conditions.append(cond)
        return conditions

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------

    def get_config_dict(self):
        memory_raw = self.memory_limit_var.get().strip()
        memory_limit_mb = int(memory_raw) if memory_raw.isdigit() else 512
        return {
            "src_connection_name": self.src_selector.connection_var.get(),
            "dst_connection_name": self.dst_selector.connection_var.get(),
            "truncate_before": self.truncate_var.get(),
            "default_chunk_size": self.default_chunk_var.get(),
            "memory_limit_mb": memory_limit_mb,
            "transfer_mode": self.transfer_mode_var.get()
            if hasattr(self, "transfer_mode_var")
            else "stream",
            "table_configs": [
                {
                    "table_name": c.table_name,
                    "target_table": c.target_var.get().strip(),
                    "mode": c.mode_var.get(),
                    "where_clause": c.cond_entry.get().strip()
                    if c.mode_var.get() == "where"
                    else "",
                    "custom_sql": c.cond_entry.get().strip()
                    if c.mode_var.get() == "sql"
                    else "",
                    "chunk_key": c.chunk_key_var.get().strip(),
                    "chunk_size": c.chunk_size_var.get().strip(),
                    "split": split_config_to_dict(
                        split_config_from_dict(c._build_split_dict())
                    ),
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
            if hasattr(self, "transfer_mode_var"):
                self.transfer_mode_var.set(config.get("transfer_mode", "stream"))
            chunk_size = config.get("default_chunk_size", "100000")
            if chunk_size:
                self.default_chunk_var.set(str(chunk_size))
            memory_limit = config.get("memory_limit_mb", 512)
            if hasattr(self, "memory_limit_var"):
                self.memory_limit_var.set(str(memory_limit))

            table_configs = config.get("table_configs", [])
            if table_configs:
                # 清除默认卡片
                for card in list(self._table_cards):
                    self._remove_table_row(card)
                for tc in table_configs:
                    card = self._add_table_row()
                    card.name_var.set(tc.get("table_name", ""))
                    card.target_var.set(tc.get("target_table", ""))
                    card.mode_var.set(tc.get("mode", "where"))
                    card.cond_entry.delete(0, "end")
                    card.cond_entry.insert(
                        0,
                        tc.get("custom_sql")
                        if tc.get("mode") == "sql"
                        else tc.get("where_clause", ""),
                    )
                    card.chunk_key_var.set(tc.get("chunk_key", ""))
                    chunk_size_value = tc.get("chunk_size", "")
                    if chunk_size_value:
                        card.chunk_size_var.set(str(chunk_size_value))
                    if "split" in tc:
                        card._load_split_fields(tc["split"])
                    elif tc.get("chunk_key"):
                        card.split_mode_var.set(SplitMode.KEY_RANGE.value)
                    card._on_split_mode_change()
                    card._on_mode_change()
                    card._update_preview()

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
        mode = TransferMode.STREAM if self.transfer_mode_var.get() == "stream" else TransferMode.CSV
        memory_raw = self.memory_limit_var.get().strip()
        limit_mb = int(memory_raw) if memory_raw.isdigit() else 512
        result = migrate_tables(
            src_config=src_config,
            dst_config=dst_config,
            table_names=[c.table_name for c in conditions],
            truncate_before=truncate_before,
            logger=self.logger,
            conditions=conditions,
            transfer_mode=mode,
            limit_mb=limit_mb,
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
            if (
                card.mode_var.get() == "sql"
                and card.split_mode_var.get() == SplitMode.KEY_RANGE.value
                and not card.chunk_key_var.get().strip()
            ):
                messagebox.showerror(
                    "错误",
                    f"表 {card.table_name} SQL + 主键分块模式必须指定 chunk_key",
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
