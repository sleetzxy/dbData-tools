"""
数据库连接管理器 - 重构版本

支持两种模式：
- 弹窗模式（as_popup=True）：作为独立的弹窗显示
- 嵌入模式（默认）：作为页面组件嵌入到主应用中
"""
import tkinter as tk
from tkinter import messagebox
import json
from pathlib import Path
import customtkinter as ctk

from gui.styling.themes import get_idea_dark_colors
from gui.widgets.buttons import StyledButton, PrimaryButton
from gui.widgets.labels import StyledLabel, TitleLabel
from gui.widgets.entries import StyledEntry
from gui.widgets.frames import ScrollableFrame
from gui.widgets.option_menus import StyledOptionMenu
from db.connection import normalize_connection_config

CONNECTIONS_FILE = "~/.connections.json"
DB_TYPE_OPTIONS = [
    ("PostgreSQL", "postgresql"),
    ("ClickHouse", "clickhouse"),
]
DB_TYPE_LABEL_TO_VALUE = {label: value for label, value in DB_TYPE_OPTIONS}
DB_TYPE_VALUE_TO_LABEL = {value: label for label, value in DB_TYPE_OPTIONS}
DB_TYPE_DEFAULTS = {
    "postgresql": {"port": "5432", "schema": "public"},
    "clickhouse": {"port": "8123", "schema": ""},
}

class ConnectionManager(ctk.CTkFrame):
    _instance = None

    def __new__(cls, parent, *args, **kwargs):
        """支持两种模式：
        - as_popup=True: 保留旧的弹窗模式（单例）
        - 默认嵌入模式：每次创建为页面组件（风格统一）
        """
        as_popup = kwargs.get("as_popup", False)
        if as_popup:
            has_valid_instance = False
            if cls._instance is not None and hasattr(cls._instance, "window"):
                try:
                    has_valid_instance = bool(cls._instance.window.winfo_exists())
                except Exception:
                    has_valid_instance = False

            if not has_valid_instance:
                cls._instance = super().__new__(cls)
                import customtkinter as ctk
                cls._instance.window = ctk.CTkToplevel(parent)
                cls._instance.window.withdraw()
                cls._instance.window.title("数据库连接管理")
                try:
                    cls._instance.window.transient(parent)
                except Exception:
                    pass
                cls._instance.window.lift()
            return cls._instance
        else:
            return super().__new__(cls)

    def __init__(self, parent, on_connections_updated=None, logger=None, as_popup=False, theme=None):
        """初始化逻辑：根据模式分别构建
        - 弹窗模式：兼容旧逻辑
        - 嵌入模式：在父容器中创建页面，并应用统一主题
        """
        import customtkinter as ctk
        if as_popup and hasattr(self, '_window_initialized'):
            self._show_existing_window()
            return

        self.on_connections_updated = on_connections_updated
        self.logger = logger
        self.connections = []
        self._editing_original_name = None
        self.parent = parent


        base_theme = get_idea_dark_colors()
        # 将传入的 theme 覆盖默认颜色，不存在的键使用默认值兜底，避免 KeyError
        self.colors = {**base_theme, **(theme or {})}

        if as_popup:
            self._window_initialized = True
            self.window.geometry("880x560")
            self.window.minsize(720, 460)
            self.window.resizable(True, True)
            self.window.protocol("WM_DELETE_WINDOW", self._on_close)
            self._root_container = self.window
            super().__init__(self.window, corner_radius=0)
            self._setup_ui()
            self.window.after(10, self._safe_show_window)
        else:
            # 嵌入模式：直接初始化CTkFrame
            super().__init__(parent, corner_radius=0)
            self._root_container = self
            self._setup_ui()

    def _safe_show_window(self):
        """安全显示窗口：居中于父窗口、顶置显示并获取焦点（仅弹窗模式）"""
        if not hasattr(self, 'window'):
            return
        try:
            self.parent.update_idletasks()
            pw, ph = self.parent.winfo_width(), self.parent.winfo_height()
            px, py = self.parent.winfo_x(), self.parent.winfo_y()
            ww = self.window.winfo_reqwidth()
            wh = self.window.winfo_reqheight()
            x = px + max((pw - ww) // 2, 0)
            y = py + max((ph - wh) // 2, 0)
            self.window.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.window.deiconify()
        try:
            self.window.transient(self.parent)
        except Exception:
            pass
        self.window.lift()
        self.window.focus_force()
        self.window.attributes("-topmost", True)
        self.window.after(250, lambda: self.window.attributes("-topmost", False))

    def _show_existing_window(self):
        """显示已存在的窗口（仅弹窗模式）"""
        if not hasattr(self, 'window'):
            return
        if self.window.winfo_exists():
            try:
                self.window.state("normal")
            except Exception:
                pass
            try:
                self.window.deiconify()
            except Exception:
                pass
            self.window.lift()
            self.window.focus_force()
            self.window.attributes("-topmost", True)
            self.window.after(
                250,
                lambda w=self.window: (
                    w.winfo_exists() and w.attributes("-topmost", False)
                ),
            )
        else:
            ConnectionManager._instance = None

    def _on_close(self):
        """关闭窗口时清理单例（仅弹窗模式）"""
        if hasattr(self, 'window'):
            ConnectionManager._instance = None
            self.window.destroy()

    def _setup_ui(self):
        """初始化UI组件"""
        self.create_widgets()
        self.load_connections()
        # 确保在嵌入模式下正确显示
        if not hasattr(self, 'window'):
            self.pack(fill=tk.BOTH, expand=True)

    def log(self, message, level='info'):
        """统一的日志记录方法"""
        if self.logger:
            if level == 'info':
                self.logger.info(message)
            elif level == 'error':
                self.logger.error(message)
        else:
            print(f"[{level.upper()}] {message}")  # 备用输出

    def create_widgets(self):
        """创建界面组件（统一深色风格，自绘行列表，行内操作）"""
        import customtkinter as ctk
        import tkinter as tk
        
        # 设置背景色
        self._root_container.configure(fg_color=self.colors["bg"])
        
        # 主容器
        main_container = ctk.CTkFrame(self._root_container, fg_color="transparent")
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # 标题（单独一行）
        title_bar = ctk.CTkFrame(main_container, fg_color="transparent")
        title_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        TitleLabel(
            title_bar,
            text="🔗 数据库连接管理",
        ).pack(anchor="w", padx=8, pady=4)

        # 操作栏
        action_bar = ctk.CTkFrame(main_container, fg_color="transparent")
        action_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 15))
        PrimaryButton(
            action_bar,
            text="新增连接",
            command=self.add_connection,
            width=120
        ).pack(anchor="e", padx=8, pady=4)

        # 列表区域（统一深色风格）
        list_card = ctk.CTkFrame(main_container, fg_color=self.colors["card_bg"], corner_radius=8)
        list_card.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 表头（居中显示）
        header_row = ctk.CTkFrame(list_card, fg_color=self.colors["card_bg"])
        header_row.pack(fill='x', padx=20, pady=(15, 8))
        
        def add_header(text, col, weight=1):
            StyledLabel(
                header_row,
                text=text
            ).grid(row=0, column=col, sticky="nsew", padx=(0, 20))
            header_row.grid_columnconfigure(col, weight=weight, minsize=100)
        
        # 表头居中显示
        add_header("名称", 0, weight=2)
        add_header("类型", 1, weight=1)
        add_header("主机", 2, weight=2)
        add_header("端口", 3, weight=1)
        add_header("用户名", 4, weight=2)
        add_header("操作", 5, weight=1)
        
        # 分割线
        separator = ctk.CTkFrame(list_card, fg_color=self.colors["border"], height=1)
        separator.pack(fill='x', padx=20, pady=(0, 10))

        # 可滚动的行容器（使用灰色滚动条）
        self.list_rows_container = ScrollableFrame(
            list_card, 
            fg_color=self.colors["card_bg"], 
            corner_radius=0,
        )
        self.list_rows_container.pack(fill='both', expand=True, padx=20, pady=(0, 10))
        
        # 分页控件
        self.page_size = 7
        self.current_page = 1
        self.total_pages = 1
        
        self.pagination_frame = ctk.CTkFrame(list_card, fg_color="transparent")
        self.pagination_frame.pack(fill='x', padx=20, pady=(0, 10), side='right')
        
        self.prev_btn = StyledButton(
            self.pagination_frame,
            text="上一页",
            command=lambda: self._change_page(-1),
            width=80,
            state="disabled"
        )
        self.prev_btn.pack(side='left', padx=(0, 10))
        
        self.page_label = ctk.CTkLabel(
            self.pagination_frame,
            text="1/1",
            font=('Microsoft YaHei', 11),
            text_color=self.colors["text_primary"]
        )
        self.page_label.pack(side='left')
        
        self.next_btn = StyledButton(
            self.pagination_frame,
            text="下一页",
            command=lambda: self._change_page(1),
            width=80,
            state="disabled"
        )
        self.next_btn.pack(side='left', padx=(10, 0))

        # 当前选中索引
        self.selected_index = None

    def _render_connection_rows(self):
        """根据 self.connections 绘制列表行（居中显示数据）"""
        import customtkinter as ctk

        if not hasattr(self, "list_rows_container") or self.list_rows_container is None:
            return

        rows_container = getattr(self.list_rows_container, "inner_content", self.list_rows_container)

        # 清空旧内容
        for child in rows_container.winfo_children():
            child.destroy()

        # 空态提示
        if not getattr(self, "connections", []):
            self.current_page = 1
            self.total_pages = 1
            self.selected_index = None
            empty_frame = ctk.CTkFrame(rows_container, fg_color="transparent")
            empty_frame.pack(expand=True, fill=tk.BOTH, pady=50)
            
            empty_label = ctk.CTkLabel(
                empty_frame, 
                text="暂无数据库连接",
                font=('Microsoft YaHei', 14),
                text_color=self.colors["text_secondary"]
            )
            empty_label.pack(pady=(0, 10))
            
            sub_label = ctk.CTkLabel(
                empty_frame,
                text="点击右上方的'新增连接'按钮来添加您的第一个连接",
                font=('Microsoft YaHei', 11),
                text_color=self.colors["text_secondary"]
            )
            sub_label.pack()
            
            # 更新分页状态
            self._update_pagination()
            return

        # 计算分页
        self.total_pages = max(1, (len(self.connections) + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, self.total_pages)
        # 确保current_page不会小于1
        self.current_page = max(1, self.current_page)
        
        # 获取当前页数据
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, len(self.connections))
        page_connections = self.connections[start_idx:end_idx]
        
        # 更新分页状态
        self._update_pagination()
        
        # 渲染每一行
        for idx, conn in enumerate(page_connections):
            row_frame = ctk.CTkFrame(rows_container, fg_color="transparent", height=50)
            row_frame.pack(fill='x', padx=0, pady=2)
            
            # 添加悬停效果
            def on_enter(e, frame):
                frame.configure(fg_color=self.colors["bg_secondary"])
            def on_leave(e, frame):
                frame.configure(fg_color="transparent")
            
            row_frame.bind("<Enter>", lambda e, f=row_frame: on_enter(e, f))
            row_frame.bind("<Leave>", lambda e, f=row_frame: on_leave(e, f))

            # 创建行内容框架
            content_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            content_frame.pack(fill='x', padx=20, pady=8)
            
            # 配置列权重（与表头一致）
            for col in range(6):
                if col == 5:  # 操作列
                    content_frame.grid_columnconfigure(col, weight=1, minsize=100)
                elif col == 3:  # 端口列
                    content_frame.grid_columnconfigure(col, weight=1, minsize=80)
                elif col == 1:  # 类型列
                    content_frame.grid_columnconfigure(col, weight=1, minsize=120)
                else:
                    content_frame.grid_columnconfigure(col, weight=2, minsize=150)
            
            # 添加单元格（居中显示）
            def add_cell(parent, text, col):
                cell = ctk.CTkLabel(
                    parent,
                    text=str(text) if text is not None else "",
                    font=('Microsoft YaHei', 11),
                    text_color=self.colors["text_primary"],
                    anchor="center"  # 修改为居中
                )
                cell.grid(row=0, column=col, sticky="nsew", padx=(0, 20), pady=4)
                return cell

            # 添加数据单元格
            add_cell(content_frame, conn.get("name", ""), 0)
            db_type_value = str(conn.get("db_type", "postgresql")).strip().lower()
            db_type_label = DB_TYPE_VALUE_TO_LABEL.get(db_type_value, db_type_value or "postgresql")
            add_cell(content_frame, db_type_label, 1)
            add_cell(content_frame, conn.get("host", ""), 2)
            add_cell(content_frame, str(conn.get("port", "")), 3)
            add_cell(content_frame, conn.get("user", ""), 4)

            # 操作图标（使用灰色按钮）
            ops_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            ops_frame.grid(row=0, column=5, sticky="nsew")
            ops_frame.grid_columnconfigure(0, weight=1)
            ops_frame.grid_columnconfigure(1, weight=1)

            # 编辑图标按钮（灰色）
            edit_btn = StyledButton(
                ops_frame,
                text="✎",
                width=32,
                height=32,
                fg_color=self.colors["button_bg"],
                hover_color=self.colors["button_hover_gray"],
                text_color=self.colors["text_primary"],
                font=('Microsoft YaHei', 14),
                corner_radius=6,
                command=lambda i=idx, start=start_idx: self._open_form_dialog(initial_data=self.connections[start + i], is_edit=True)
            )
            edit_btn.grid(row=0, column=0, padx=(0, 4), sticky="e")

            # 删除图标按钮（灰色）
            delete_btn = StyledButton(
                ops_frame,
                text="🗑",
                width=32,
                height=32,
                fg_color=self.colors["button_bg"],
                hover_color=self.colors["button_hover_gray"],
                text_color=self.colors["text_primary"],
                font=('Microsoft YaHei', 14),
                corner_radius=6,
                command=lambda i=idx, start=start_idx: self.delete_connection(index=start + i)
            )
            delete_btn.grid(row=0, column=1, sticky="w")

            # 行点击选择
            row_frame.bind("<Button-1>", lambda e, i=idx: self._on_row_click(i))
            content_frame.bind("<Button-1>", lambda e, i=idx: self._on_row_click(i))

    def _on_row_click(self, index):
        """选择某行（仅记录索引，不展示右侧详情）"""
        # 计算全局索引
        global_idx = (self.current_page - 1) * self.page_size + index
        self.selected_index = global_idx
        # 可以在这里添加高亮效果
        conn = self.connections[global_idx]
        
    def _change_page(self, delta):
        """切换页码"""
        new_page = self.current_page + delta
        # 确保页码在有效范围内
        new_page = max(1, min(new_page, self.total_pages))
        if new_page != self.current_page:
            self.current_page = new_page
            self._render_connection_rows()
            self._update_pagination()
        # 强制刷新界面
        self._root_container.update()
            
    def _update_pagination(self):
        """更新分页控件状态"""
        if not hasattr(self, "pagination_frame"):
            return
            
        self.page_label.configure(text=f"{self.current_page}/{self.total_pages}")
        self.prev_btn.configure(state="normal" if self.current_page > 1 else "disabled")
        self.next_btn.configure(state="normal" if self.current_page < self.total_pages else "disabled")

    def load_connections(self):
        """加载连接列表并绘制"""
        self.connections = self._read_connections()
        self._render_connection_rows()
        # 自动选中第一项
        if self.connections:
            self._on_row_click(0)

    def _read_connections(self):
        """加载连接配置列表并做规范化校验。"""
        try:
            connections_path = Path(CONNECTIONS_FILE).expanduser()
            if connections_path.exists():
                with open(connections_path, "r", encoding="utf-8") as f:
                    loaded_connections = json.load(f)
                    if isinstance(loaded_connections, dict):
                        legacy_connections = loaded_connections.get("connections")
                        if isinstance(legacy_connections, list):
                            loaded_connections = legacy_connections

                    if not isinstance(loaded_connections, list):
                        error_msg = (
                            f"连接配置文件格式错误：根节点必须是列表(list)，"
                            f"当前类型为 {type(loaded_connections).__name__}。"
                        )
                        self.log(f"{error_msg} 文件：{connections_path}", level="error")
                        messagebox.showerror("连接配置错误", error_msg)
                        return []

                    normalized_connections = []
                    skipped_records = []
                    for index, item in enumerate(loaded_connections):
                        if not isinstance(item, dict):
                            skipped_records.append(f"index={index}, reason=record_not_object")
                            continue
                        try:
                            normalized_connections.append(normalize_connection_config(item))
                        except Exception as item_error:
                            name = item.get("name", "<unknown>")
                            db_type = item.get("db_type", "<missing>")
                            skipped_records.append(
                                f"index={index}, name={name}, db_type={db_type}, reason={item_error}"
                            )

                    if skipped_records:
                        for detail in skipped_records:
                            self.log(f"跳过无效连接记录: {detail}", level="error")

                    return normalized_connections
        except Exception as e:
            messagebox.showerror("连接加载失败", f"读取连接配置失败：{str(e)}")
        return []

    def _save_connections(self):
        """保存连接配置列表（写入前会做规范化）。"""
        try:
            connections_path = Path(CONNECTIONS_FILE).expanduser()
            connections_path.parent.mkdir(parents=True, exist_ok=True)

            normalized_connections = []
            for item in self.connections:
                if isinstance(item, dict):
                    normalized_connections.append(normalize_connection_config(item))
            self.connections = normalized_connections

            with open(connections_path, "w", encoding="utf-8") as f:
                json.dump(self.connections, f, indent=4, ensure_ascii=False)

            if self.on_connections_updated:
                self.on_connections_updated()

            return True
        except Exception as e:
            messagebox.showerror("连接保存失败", f"保存连接配置失败：{str(e)}")
            return False

    def add_connection(self):
        """添加新连接（弹窗表单）"""
        self._open_form_dialog(initial_data=None, is_edit=False)

    def edit_connection(self):
        """编辑当前选中的连接（弹窗表单）"""
        if self.selected_index is None:
            messagebox.showwarning("警告", "请先选择一个连接")
            return
        target = self.connections[self.selected_index]
        self._open_form_dialog(initial_data=target, is_edit=True)

    def delete_connection(self, index=None):
        """删除连接（支持从行内按钮传入 index）"""
        if index is None:
            if self.selected_index is None:
                messagebox.showwarning("警告", "请先选择一个连接")
                return
            index = self.selected_index

        conn_name = self.connections[index].get("name")
        if not messagebox.askyesno("确认", f"确定要删除连接 '{conn_name}' 吗？"):
            return

        # 删除并保存
        del self.connections[index]
        if self._save_connections():
            self._render_connection_rows()
            # 仅更新选中索引
            if self.connections:
                self.selected_index = min(index, len(self.connections) - 1)
            else:
                self.selected_index = None

    def _open_form_dialog(self, initial_data=None, is_edit=False):
        """打开连接表单对话框（新增或编辑）"""
        import customtkinter as ctk
        
        dlg = ctk.CTkToplevel(self._root_container)
        dlg.title("新增连接" if not is_edit else "编辑连接")
        dlg.resizable(False, False)
        
        try:
            dlg.transient(self._root_container.winfo_toplevel())
            dlg.grab_set()
        except Exception:
            pass
    

        # 设置对话框背景色
        dlg.configure(fg_color=self.colors["bg"])

        container = ctk.CTkFrame(dlg, fg_color=self.colors["bg"])
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # 修改为 grid 布局以对齐 label
        container.grid_columnconfigure(1, weight=1)  # entry 列扩展

        initial_type_value = str((initial_data or {}).get("db_type", "postgresql")).strip().lower() or "postgresql"
        if initial_type_value not in DB_TYPE_VALUE_TO_LABEL:
            initial_type_value = "postgresql"

        def make_row(parent, row_idx, label_text, placeholder="", initial="", is_password=False):
            lbl = StyledLabel(parent, text=label_text, width=30, anchor="e")  # 固定宽度并右对齐
            lbl.grid(row=row_idx, column=0, sticky="e", padx=(0, 10), pady=8)
            
            entry = StyledEntry(parent, placeholder_text=placeholder, show="●" if is_password else None)
            if initial:
                entry.insert(0, initial)
            entry.grid(row=row_idx, column=1, sticky="ew", pady=8)
            return entry

        def set_entry_text(entry, value):
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            if value is not None:
                entry.insert(0, str(value))

        # 使用行索引调用
        name_e = make_row(container, 0, "名称", "例如：生产库", (initial_data or {}).get("name", ""))
        db_type_label = StyledLabel(container, text="类型", width=30, anchor="e")
        db_type_label.grid(row=1, column=0, sticky="e", padx=(0, 10), pady=8)
        db_type_var = tk.StringVar(value=DB_TYPE_VALUE_TO_LABEL[initial_type_value])
        db_type_menu = StyledOptionMenu(
            container,
            values=[label for label, _ in DB_TYPE_OPTIONS],
            variable=db_type_var,
        )
        db_type_menu.grid(row=1, column=1, sticky="ew", pady=8)

        host_e = make_row(container, 2, "主机", "例如：127.0.0.1", (initial_data or {}).get("host", ""))
        port_e = make_row(
            container,
            3,
            "端口",
            "默认：5432/8123",
            str((initial_data or {}).get("port", DB_TYPE_DEFAULTS[initial_type_value]["port"])),
        )
        db_e   = make_row(container, 4, "数据库", "例如：postgres", (initial_data or {}).get("database", ""))
        schema_e = make_row(
            container,
            5,
            "模式",
            "public",
            str((initial_data or {}).get("schema", DB_TYPE_DEFAULTS[initial_type_value]["schema"])),
        )
        user_e = make_row(container, 6, "用户", "例如：postgres", (initial_data or {}).get("user", ""))
        pwd_e  = make_row(container, 7, "密码", "可留空", (initial_data or {}).get("password", ""), is_password=True)

        # “是否自定义”仅跟踪本次对话框会话内的用户输入行为，
        # 不根据编辑模式下的预加载值推断。
        port_customized = False
        schema_customized = False

        def mark_port_customized(_event=None):
            nonlocal port_customized
            port_customized = True

        def mark_schema_customized(_event=None):
            nonlocal schema_customized
            schema_customized = True

        port_e.bind("<KeyRelease>", mark_port_customized)
        schema_e.bind("<KeyRelease>", mark_schema_customized)

        def apply_type_defaults(db_type_value):
            nonlocal port_customized, schema_customized
            defaults = DB_TYPE_DEFAULTS.get(db_type_value, DB_TYPE_DEFAULTS["postgresql"])

            if not port_customized:
                set_entry_text(port_e, defaults["port"])

            if db_type_value == "clickhouse":
                if not schema_customized:
                    set_entry_text(schema_e, "")
                schema_e.configure(state="disabled")
            else:
                schema_e.configure(state="normal")
                if not schema_customized:
                    set_entry_text(schema_e, defaults["schema"])

        def on_db_type_changed(selected_label):
            db_type_value = DB_TYPE_LABEL_TO_VALUE.get(selected_label, "postgresql")
            apply_type_defaults(db_type_value)

        db_type_menu.configure(command=on_db_type_changed)
        if is_edit and initial_data is not None:
            if initial_type_value == "clickhouse":
                schema_e.configure(state="disabled")
            else:
                schema_e.configure(state="normal")
        else:
            apply_type_defaults(initial_type_value)

        # 按钮区域（使用灰色按钮）
        btn_bar = ctk.CTkFrame(container, fg_color="transparent")
        btn_bar.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(20, 0))

        def on_save():
            name = name_e.get().strip()
            host = host_e.get().strip()
            db_type = DB_TYPE_LABEL_TO_VALUE.get(db_type_var.get(), "postgresql")
            default_port = DB_TYPE_DEFAULTS.get(db_type, DB_TYPE_DEFAULTS["postgresql"])["port"]
            port_txt = port_e.get().strip() or str(default_port)
            dbn  = db_e.get().strip()
            user = user_e.get().strip()
            pwd  = pwd_e.get()
            schema = schema_e.get().strip() if db_type != "clickhouse" else ""


            if not name or not host or not dbn or not user:
                messagebox.showerror("错误", "请填写名称/主机/数据库/用户")
                return
            try:
                port = int(port_txt)
            except ValueError:
                messagebox.showerror("错误", "端口必须为数字")
                return

            new_data = {
                "name": name,
                "host": host,
                "port": port,
                "database": dbn,
                "user": user,
                "password": pwd,
                "schema": schema,
                "db_type": db_type
            }


            edit_index = None
            if is_edit and initial_data is not None:
                try:
                    edit_index = self.connections.index(initial_data)
                except ValueError:
                    edit_index = None

            # 检查名称重复
            for i, c in enumerate(self.connections):
                if edit_index is not None and i == edit_index:
                    continue
                if c.get("name") == new_data["name"]:
                    messagebox.showerror("错误", f"连接名称'{new_data['name']}'已存在")
                    return

            if is_edit and edit_index is not None:
                self.connections[edit_index] = new_data
            else:
                self.connections.append(new_data)

            if self._save_connections():
                # 选中新添加或编辑的项（按全局索引定位，再转换为页内索引）
                target_index = None
                for i, c in enumerate(self.connections):
                    if c.get("name") == new_data["name"]:
                        target_index = i
                        break

                if target_index is not None:
                    self.current_page = (target_index // self.page_size) + 1
                    self._render_connection_rows()
                    page_start = (self.current_page - 1) * self.page_size
                    self._on_row_click(target_index - page_start)
                else:
                    self._render_connection_rows()
                dlg.destroy()

        # 保存按钮
        save_btn = StyledButton(
            btn_bar, 
            text="保存",
            command=on_save, 
            width=100,
            height=32,
            fg_color=self.colors["button_bg"],
            hover_color=self.colors["button_hover_gray"],
            text_color=self.colors["text_primary"],
            font=('Microsoft YaHei', 12),
            corner_radius=6
        )
        save_btn.pack(side="right")
        
        # 取消按钮
        cancel_btn = StyledButton(
            btn_bar, 
            text="取消", 
            command=dlg.destroy, 
            width=100,
            height=32,
            fg_color=self.colors["button_bg"],
            hover_color=self.colors["button_hover_gray"],
            text_color=self.colors["text_primary"],
            font=('Microsoft YaHei', 12),
            corner_radius=6
        )
        cancel_btn.pack(side="right", padx=(10, 0))

        dlg.geometry(self._center_geometry(380, 480))
        dlg.focus()

    def _center_geometry(self, width: int, height: int) -> str:
        """将弹窗居中到父窗口"""
        try:
            root = self._root_container.winfo_toplevel()
            root.update_idletasks()
            x = root.winfo_x() + (root.winfo_width() - width) // 2
            y = root.winfo_y() + (root.winfo_height() - height) // 2
            return f"{width}x{height}+{x}+{y}"
        except Exception:
            return f"{width}x{height}+100+100"

# 测试函数
def test_connection_manager():
    """测试连接管理器"""
    import customtkinter as ctk
    
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    
    root = ctk.CTk()
    root.title("连接管理器测试")
    root.geometry("900x600")
    
    def on_connections_updated():
        print("连接已更新")
    
    # 创建连接管理器实例（嵌入模式）
    connection_manager = ConnectionManager(root, on_connections_updated, as_popup=False)
    connection_manager.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
    
    root.mainloop()

if __name__ == "__main__":
    test_connection_manager()
