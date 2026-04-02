import tkinter as tk
from tkinter import messagebox
import logging

# 顶部导入区域 - 使用重构后的页面
from gui.pages.csv.exporter import ExportCsvApp
from gui.pages.csv.importer import ImportCsvApp
from gui.pages.csv.updater import UpdateCsvApp
from gui.pages.database.exporter import ExportDbApp
from gui.pages.database.migrator import MigratorPage
from gui.pages.database.migrator import MigratorPage
from gui.pages.management.connection import ConnectionManager
from gui.pages.csv.importer_type import ImportCsvTypeApp
# 新增：引入公共主题与滚动条样式方法
from gui.styling.themes import get_idea_dark_colors, init_theme

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ToolTipManager:
    """管理工具提示的类"""
    def __init__(self, root):
        self.root = root
        self.current_tip = None
        self.tip_windows = {}  # 存储每个按钮的提示窗口
        self.tip_ids = {}      # 存储延迟显示的ID
        # 新增：点击后的抑制目标（在鼠标离开该按钮之前不再显示提示）
        self.suppressed_widget = None
        
    def bind_tooltip(self, widget, text):
        """为控件绑定工具提示"""
        # 改为鼠标移动时显示提示
        widget.bind('<Motion>', lambda e, w=widget, t=text: self.show_tip(w, t))
        # 离开控件时，隐藏并解除抑制
        widget.bind('<Leave>', lambda e, w=widget: self._on_leave(w))
        # 点击控件时，隐藏并对该控件设置抑制（使用更具体的左键事件）
        widget.bind('<Button-1>', lambda e, w=widget: self._on_click(w))
        
    def show_tip(self, widget, text):
        """显示工具提示"""
        # 如果该控件处于点击后的抑制状态，则不显示
        if self.suppressed_widget is widget:
            return
        # 先隐藏当前的提示
        self.hide_tip()
        # 设置延迟显示
        tip_id = self.root.after(100, lambda: self._create_tip(widget, text))
        self.tip_ids[widget] = tip_id
        
    def _draw_rounded_rect(self, canvas, x1, y1, x2, y2, r, fill, outline):
        # 使用矩形+四个圆角扇形拼出圆角矩形
        local_outline = "" if outline in (None, "", "transparent") else outline
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=local_outline)
        canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=local_outline)
        canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style=tk.PIESLICE, fill=fill, outline=local_outline)
        canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style=tk.PIESLICE, fill=fill, outline=local_outline)
        canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style=tk.PIESLICE, fill=fill, outline=local_outline)
        canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style=tk.PIESLICE, fill=fill, outline=local_outline)
    def _create_tip(self, widget, text):
        """创建工具提示窗口（聊天气泡样式，白色背景，尾巴指向按钮）"""
        if widget not in self.tip_ids:
            return

        # 计算位置（优先显示在右侧）
        right_x = widget.winfo_rootx() + widget.winfo_width() + 8
        center_y = widget.winfo_rooty() + (widget.winfo_height() // 2)

        try:
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)
            tip.wm_attributes('-toolwindow', True)
            tip.wm_attributes('-topmost', True)

            # 透明色用于绘制尾巴（支持则使用）
            trans_color = "#00ffff"
            try:
                tip.wm_attributes('-transparentcolor', trans_color)
            except Exception:
                trans_color = None  # 不支持透明则回退

            # 气泡样式（白色背景）
            colors = get_idea_dark_colors()
            bubble_bg = "#ffffff"
            border = "#d0d0d0"
            text_color = "#333333"
            font_cfg = ('Microsoft YaHei', 9)

            # 先测量文本尺寸
            canvas = tk.Canvas(tip, bg=trans_color or "#e0e0e0", highlightthickness=0, bd=0)
            tmp_id = canvas.create_text(0, 0, text=text, font=font_cfg, anchor='nw')
            bbox = canvas.bbox(tmp_id) or (0, 0, 80, 20)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            canvas.delete(tmp_id)

            pad_x, pad_y = 12, 6
            bubble_w = text_w + pad_x * 2
            bubble_h = text_h + pad_y * 2
            # 增大圆角半径，并根据气泡尺寸自适应，让边角更圆润
            radius = max(10, min(bubble_h, bubble_w) // 6)
            tail_size = 8 if trans_color else 0  # 无透明不绘制尾巴
            bubble_w = text_w + pad_x * 2
            bubble_h = text_h + pad_y * 2

            # 是否能放在按钮右侧
            screen_width = self.root.winfo_screenwidth()
            show_on_right = (right_x + bubble_w + tail_size) <= screen_width

            total_w = bubble_w + tail_size
            total_h = bubble_h
            canvas.configure(width=total_w, height=total_h)
            canvas.pack()

            # 根据方向给圆角矩形留尾巴的空间
            rect_x1 = tail_size if show_on_right else 0
            rect_x2 = rect_x1 + bubble_w
            rect_y1 = 0
            rect_y2 = bubble_h

            # 圆角矩形（把 outline 设为 "" 取消边框绘制）
            self._draw_rounded_rect(canvas, rect_x1, rect_y1, rect_x2, rect_y2, radius, bubble_bg, "")

            # 尾巴（三角）指向按钮：右侧显示=>左边尾巴；左侧显示=>右边尾巴
            if tail_size > 0:
                mid_y = (rect_y1 + rect_y2) // 2
                if show_on_right:
                    points = [rect_x1, mid_y - 6, rect_x1 - tail_size, mid_y, rect_x1, mid_y + 6]
                else:
                    points = [rect_x2, mid_y - 6, rect_x2 + tail_size, mid_y, rect_x2, mid_y + 6]
                # 取消尾巴边框
                canvas.create_polygon(points, fill=bubble_bg, outline="")

            # 文本
            canvas.create_text(rect_x1 + pad_x, rect_y1 + pad_y, text=text, font=font_cfg, fill=text_color, anchor='nw')

            # 位置
            tip.update_idletasks()
            if show_on_right:
                x = right_x  # 尾巴尖端贴近按钮右边+8px
            else:
                x = widget.winfo_rootx() - (bubble_w + tail_size) - 8
            y = center_y - (total_h // 2)
            tip.wm_geometry(f'+{x}+{y}')

            self.current_tip = tip
            self.tip_windows[widget] = tip
            try:
                tip.attributes('-alpha', 0.98)
            except Exception:
                pass

            tip.bind('<Enter>', lambda e: self._keep_tip())
            tip.bind('<Leave>', lambda e: self.hide_tip())
            # 新增：点击提示气泡本身也隐藏
            tip.bind('<ButtonPress>', lambda e: self.hide_tip())

        except Exception as e:
            logger.error(f"创建工具提示失败: {e}")
    def _keep_tip(self):
        """保持提示显示"""
        pass  # 当鼠标进入提示框时，不隐藏
        
    def hide_tip(self):
        """隐藏所有工具提示"""
        # 取消所有延迟显示
        for widget, tip_id in list(self.tip_ids.items()):
            if tip_id:
                self.root.after_cancel(tip_id)
        self.tip_ids.clear()
        
        # 销毁所有提示窗口
        if self.current_tip:
            try:
                self.current_tip.destroy()
            except:
                pass
            self.current_tip = None
            
        for widget, tip in list(self.tip_windows.items()):
            if tip:
                try:
                    tip.destroy()
                except:
                    pass
        self.tip_windows.clear()
        
    def cleanup(self):
        """清理资源"""
        self.hide_tip()

    def _on_click(self, widget):
        """点击控件时隐藏提示，并在离开前不再显示"""
        self.suppressed_widget = widget
        self.hide_tip()

    def _on_leave(self, widget):
        """离开控件时隐藏提示并解除抑制"""
        self.hide_tip()
        if self.suppressed_widget is widget:
            self.suppressed_widget = None

class MainApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("DB 数据工具集")
        
        # 设置窗口大小和最小尺寸
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        window_width = min(1200, screen_width * 0.85)
        window_height = min(800, screen_height * 0.85)
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(1000, 700)
        
        # 创建工具提示管理器
        self.tooltip_manager = ToolTipManager(root)
        
        # 使用IDEA风格的深色主题
        self._setup_idea_dark_theme()
        
        # 初始化UI
        self._setup_ui()
        
        # 初始化页面缓存，用于持久化各工具页和欢迎页
        self.pages = {}
        self.current_page = None
        # 默认显示欢迎页（持久化）
        self.show_welcome()

    def _setup_idea_dark_theme(self):
        """设置IDEA风格深色主题"""
        import customtkinter as ctk
        
        # 使用公共方法获取统一主题色
        self.idea_dark_colors = get_idea_dark_colors()
        
        # 使用公共方法初始化CTk主题
        init_theme(ctk)
    
        
    def _setup_ui(self):
        """初始化用户界面"""
        import customtkinter as ctk
        
        # 主容器
        self.main_container = ctk.CTkFrame(
            self.root, 
            corner_radius=0,
            fg_color=self.idea_dark_colors["bg"]
        )
        self.main_container.pack(fill='both', expand=True)
        
        # 创建左侧图标菜单栏
        self._create_simple_sidebar()
        
        # 右侧面板（包含内容区和底部版权栏）
        self.right_panel = ctk.CTkFrame(
            self.main_container,
            corner_radius=0,
            fg_color=self.idea_dark_colors["bg"]
        )
        self.right_panel.pack(side='left', fill='both', expand=True, padx=(2, 0), pady=0)
        
        # 主内容区域（页容器）
        self.content_frame = ctk.CTkFrame(
            self.right_panel,
            corner_radius=0,
            fg_color=self.idea_dark_colors["bg_secondary"],
            border_width=1,
            border_color=self.idea_dark_colors["border"]
        )
        self.content_frame.pack(side='top', fill='both', expand=True,pady=(0,1))
        
        # 底部固定版权信息栏（始终可见）
        self.footer_bar = ctk.CTkFrame(
            self.right_panel,
            height=26,
            corner_radius=0,
            fg_color=self.idea_dark_colors["sidebar_bg"]
        )
        self.footer_bar.pack(side='bottom', fill='x',pady=(1,0))
        ctk.CTkLabel(
            self.footer_bar,
            text="© 2025 zhangxueyu - DB Data Tools",
            anchor='center',
            font=('Microsoft YaHei', 9),
            text_color=self.idea_dark_colors["text_secondary"]
        ).pack(pady=0)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        """窗口关闭时的清理"""
        self.tooltip_manager.cleanup()
        self.root.quit()

    def _create_simple_sidebar(self):
        """创建简单的左侧图标菜单栏"""
        import customtkinter as ctk
        
        # 主菜单容器
        self.sidebar = ctk.CTkFrame(
            self.main_container,
            width=40,
            corner_radius=0,
            fg_color=self.idea_dark_colors["sidebar_bg"]
        )
        self.sidebar.pack(side='left', fill='y', padx=0, pady=0)
        self.sidebar.pack_propagate(False)
        
        # 按钮容器 - 使用垂直布局
        buttons_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        buttons_frame.pack(fill='both', expand=True, padx=0, pady=10)
        
        # 工具按钮列表
        self.tools_data = [
            ("📥", "CSV导入", self.load_importer),
            ("📝", "CSV导入（指定类型）", self.load_importer_type),
            ("📤", "CSV导出", self.load_exporter),
            ("📦", "数据库导出", self.load_db_exporter),
            ("🔀", "数据迁移", self.load_migrator),
            ("🔄", "CSV加解密", self.load_updater),
        ]
        
        # 创建工具按钮
        self.tool_buttons = []
        # 建立命令到按钮的映射，避免因顺序变化导致高亮错位
        self.command_to_button = {}
        for icon, text, command in self.tools_data:
            btn = self._create_menu_button(buttons_frame, icon, text, command)
            self.tool_buttons.append(btn)
            self.command_to_button[command.__name__] = btn
        
        # 分隔线
        separator = ctk.CTkFrame(
            buttons_frame,
            height=2,
            fg_color=self.idea_dark_colors["border"]
        )
        separator.pack(fill='x', pady=10, padx=8)
        
        # 连接管理按钮
        self.conn_btn = self._create_menu_button(
            buttons_frame, 
            "🔗", 
            "数据库连接管理", 
            self._show_connection_manager
        )
        
        # 首页按钮
        self.home_btn = self._create_menu_button(
            buttons_frame, 
            "🏠", 
            "首页", 
            self.show_welcome,
            highlighted=True
        )
        
        # 弹簧空间
        ctk.CTkFrame(buttons_frame, fg_color="transparent", height=0).pack(fill='x', expand=True)
        
        # 退出按钮
        self.exit_btn = self._create_menu_button(
            buttons_frame, 
            "✕", 
            "退出应用", 
            self.root.quit,
            color=self.idea_dark_colors["error"]
        )

    def _create_menu_button(self, parent, icon, text, command, highlighted=False, color=None):
        """创建菜单按钮"""
        import customtkinter as ctk
        
        # 先定义包装的点击处理：隐藏提示 + 设置抑制，再执行原始命令
        def _wrapped_command(btn_widget, original_cmd):
            try:
                # 设置抑制并隐藏（确保点击后不再立即显示）
                self.tooltip_manager._on_click(btn_widget)
            except Exception:
                # 兜底：至少隐藏提示
                self.tooltip_manager.hide_tip()
            # 执行原始命令
            try:
                original_cmd()
            except Exception as e:
                logger.error(f"执行菜单命令失败: {e}", exc_info=True)

        btn = ctk.CTkButton(
            parent,
            text=icon,
            # 使用包装后的 command，可靠隐藏提示
            command=lambda b=None, cmd=command: _wrapped_command(btn if b is None else b, cmd),
            width=34,
            height=34,
            corner_radius=4,
            font=('Segoe UI', 13),
            fg_color=self.idea_dark_colors["button_hover"] if highlighted else "transparent",
            hover_color=color if color else self.idea_dark_colors["button_hover"],
            border_width=0,
            anchor='center'
        )
        
        if icon == "✕":  # 退出按钮特殊样式
            btn.configure(font=('Segoe UI', 14, 'bold'))
            
        btn.pack(pady=4)
        
        # 绑定美观的工具提示
        self.tooltip_manager.bind_tooltip(btn, text)
        
        # 绑定鼠标移动事件，确保鼠标在按钮间移动时提示能正确更新
        btn.bind('<Motion>', lambda e, b=btn, t=text: self._on_button_motion(b, t))
        
        return btn
    
    def _on_button_motion(self, button, text):
        """处理按钮上的鼠标移动"""
        # 确保鼠标在当前按钮上时显示正确的提示
        if self.tooltip_manager.current_tip:
            # 如果已经有提示显示，先隐藏它，然后重新显示当前按钮的提示
            self.tooltip_manager.hide_tip()
            self.tooltip_manager.show_tip(button, text)

    def _show_connection_manager(self):
        """显示连接管理（页面模式，持久化切换，统一主题）"""
        self._reset_menu_buttons()
        self.conn_btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        # 以页面形式显示，并传入统一主题和更新回调
        self._show_page('connections', builder=lambda parent: ConnectionManager(
            parent,
            on_connections_updated=self._on_connections_updated,
            theme=self.idea_dark_colors
        ))

    def _on_connections_updated(self):
        """连接更新后的回调 - 刷新所有已打开页面的连接列表"""
        # 遍历所有已创建的页面，如果有 load_connections_and_update 方法就调用
        for page_name, page in self.pages.items():
            if page_name != 'connections' and page_name != 'welcome':
                if hasattr(page, 'load_connections_and_update'):
                    try:
                        page.load_connections_and_update()
                    except Exception as e:
                        print(f"刷新页面 {page_name} 的连接列表失败: {e}")

    def get_changelog_data(self):
        """获取更新日志数据"""
        return [
            {
                "version": "1.4.0",
                "date": "2026-04-02",
                "changes": [
                    "新增数据迁移功能，支持指定多表从源库迁移到目标库",
                    "支持 PostgreSQL 与 ClickHouse 同构及异构迁移",
                    "可选迁移前清空目标表（TRUNCATE）"
                ],
                "color": self.idea_dark_colors["accent"]
            },
            {
                "version": "1.3.0",
                "date": "2026-03-26",
                "changes": [
                    "新增 ClickHouse 数据库支持（CSV 导入、CSV 导出、SQL 导出）",
                    "数据库连接管理支持多类型（PostgreSQL / ClickHouse）",
                    "工具集更名为 DB 数据工具集，兼容多种数据库"
                ],
                "color": self.idea_dark_colors["accent"]
            },
            {
                "version": "1.2.2", 
                "date": "2025-12-23", 
                "changes": ["支持常见压缩算法的zip解压"],
                "color": self.idea_dark_colors["text_secondary"]
            },
            {
                "version": "1.2.1", 
                "date": "2025-12-08", 
                "changes": ["修复数据库连接缺失模式字段bug"],
                "color": self.idea_dark_colors["text_secondary"]
            },
            {
                "version": "1.2.0", 
                "date": "2025-12-01", 
                "changes": ["新增CSV按指定数据类型导入功能", "优化UI布局"],

                "color": self.idea_dark_colors["text_secondary"]
            },
            {
                "version": "1.1.0", 
                "date": "2025-09-09", 
                "changes": [
                    "新增ZIP压缩文件导入功能",
                    "支持基本的数据库连接管理",
                    "增强数据验证和错误处理机制"
                ],
                "color": self.idea_dark_colors["text_secondary"]
            },
            {
                "version": "1.0.0", 
                "date": "2025-04-01", 
                "changes": [
                    "初始版本正式发布", 
                    "实现基础数据导入导出功能"
                ],
                "color": self.idea_dark_colors["text_secondary"]
            }
        ]

    def _show_page(self, name, builder=None):
        """显示指定名称的页面，页面不存在时按需创建"""
        import customtkinter as ctk

        # 如果页面不存在且提供了构建器，创建并缓存
        if name not in self.pages and builder is not None:
            # 直接调用构建器，让它返回页面对象
            page = builder(self.content_frame)
            self.pages[name] = page

        # 隐藏当前内容区域中的所有子组件（不销毁）
        for child in self.content_frame.winfo_children():
            try:
                child.pack_forget()
            except Exception:
                try:
                    child.grid_remove()
                except Exception:
                    pass

        # 显示目标页面
        target = self.pages.get(name)
        if target:
            # 首页需要外边距，其他页面不需要
            if name == 'welcome':
                target.pack(fill='both', expand=True, padx=20, pady=20)
            else:
                target.pack(fill='both', expand=True)
            self.current_page = name

    def _build_welcome_page(self, parent):
        """在给定父容器上构建欢迎页内容（仅一次）"""
        import customtkinter as ctk
        import tkinter as tk

        # 主容器（不在这里 pack，让 _show_page 统一处理）
        main_container = ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["bg_secondary"]
        )

        # 欢迎标题
        welcome_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        welcome_frame.pack(pady=(30, 20))

        ctk.CTkLabel(
            welcome_frame,
            text="DB 数据工具集",
            font=('Microsoft YaHei', 22, 'bold'),
            text_color=self.idea_dark_colors["text_primary"]
        ).pack()

        logs = self.get_changelog_data()
        latest_version = logs[0]['version'] if logs else "未知"
        ctk.CTkLabel(
            welcome_frame,
            text=f"版本 {latest_version}",
            font=('Microsoft YaHei', 13),
            text_color=self.idea_dark_colors["text_secondary"]
        ).pack(pady=(5, 0))


        # 更新日志标题
        changelog_header = ctk.CTkFrame(main_container, fg_color="transparent")
        changelog_header.pack(fill='x', pady=(10, 10))

        ctk.CTkLabel(
            changelog_header,
            text="📝 更新日志",
            font=('Microsoft YaHei', 16, 'bold'),
            anchor='w',
            text_color=self.idea_dark_colors["text_primary"]
        ).pack(side='left')

        # 更新日志容器
        changelog_container = ctk.CTkFrame(
            main_container,
            corner_radius=6,
            fg_color=self.idea_dark_colors["card_bg"]
        )
        changelog_container.pack(fill='both', expand=True)

        # 创建滚动区域
        canvas = tk.Canvas(
            changelog_container,
            highlightthickness=0,
            bg=self.idea_dark_colors["card_bg"]
        )
        scrollbar = ctk.CTkScrollbar(
            changelog_container,
            orientation="vertical",
            command=canvas.yview
        )
        # 统一CTkScrollbar样式
        

        scrollable_frame = ctk.CTkFrame(canvas, fg_color=self.idea_dark_colors["card_bg"])

        def configure_canvas(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        scrollable_frame.bind("<Configure>", configure_canvas)
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 添加更新日志内容
        for log in self.get_changelog_data():
            self._create_changelog_entry(scrollable_frame, log)

        canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        scrollbar.pack(side="right", fill="y")

        # 返回主容器
        return main_container


    def _create_changelog_entry(self, parent, log_data):
        """创建更新日志条目"""
        import customtkinter as ctk
        
        entry_frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry_frame.pack(fill='x', pady=6)
        
        # 版本和日期
        header_frame = ctk.CTkFrame(entry_frame, fg_color="transparent")
        header_frame.pack(fill='x')
        
        version_label = ctk.CTkLabel(
            header_frame,
            text=f"版本 {log_data['version']}",
            font=('Microsoft YaHei', 11, 'bold'),
            text_color=log_data['color']
        )
        version_label.pack(side='left')
        
        date_label = ctk.CTkLabel(
            header_frame,
            text=f"发布于 {log_data['date']}",
            font=('Microsoft YaHei', 9),
            text_color=self.idea_dark_colors["text_secondary"]
        )
        date_label.pack(side='left', padx=(8, 0))
        
        # 更新内容
        content_frame = ctk.CTkFrame(entry_frame, fg_color="transparent")
        content_frame.pack(fill='x', padx=(12, 0), pady=(3, 0))
        
        for change in log_data['changes']:
            ctk.CTkLabel(
                content_frame,
                text=f"• {change}",
                font=('Microsoft YaHei', 10),
                text_color=self.idea_dark_colors["text_primary"],
                anchor='w'
            ).pack(anchor='w')

    def _reset_menu_buttons(self):
        """重置菜单按钮样式"""
        # 重置所有工具按钮
        for btn in self.tool_buttons:
            btn.configure(fg_color="transparent")
        
        # 重置其他按钮
        self.conn_btn.configure(fg_color="transparent")
        self.home_btn.configure(fg_color="transparent")

    def show_welcome(self):
        """兼容旧调用，转发到持久化欢迎页加载方法"""
        self.load_welcome()

    def load_welcome(self):
        """显示欢迎界面（持久化页面切换）"""
        self._reset_menu_buttons()
        self.home_btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        # 切换到持久化的欢迎页
        self._show_page('welcome', builder=self._build_welcome_page)

    def load_importer(self):
        """加载CSV导入工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_importer')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('importer', builder=lambda parent: ImportCsvApp(parent))

    def load_importer_type(self):
        """加载CSV指定类型导入工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_importer_type')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('importer_type', builder=lambda parent: ImportCsvTypeApp(parent))

    def load_exporter(self):
        """加载CSV导出工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_exporter')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('exporter_csv', builder=lambda parent: ExportCsvApp(parent))

    def load_updater(self):
        """加载CSV加解密工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_updater')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('updater', builder=lambda parent: UpdateCsvApp(parent))

    def load_db_exporter(self):
        """加载数据库导出工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_db_exporter')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('exporter_db', builder=lambda parent: ExportDbApp(parent))

    def load_migrator(self):
        """加载数据迁移工具（持久化页面切换）"""
        self._reset_menu_buttons()
        btn = self.command_to_button.get('load_migrator')
        if btn:
            btn.configure(fg_color=self.idea_dark_colors["button_hover"])
        self._show_page('migrator', builder=lambda parent: MigratorPage(parent))

    def clear_content(self):
        """清空内容区域（不销毁，仅隐藏以避免Tk命令失效）"""
        for widget in self.content_frame.winfo_children():
            try:
                widget.pack_forget()
            except Exception:
                try:
                    widget.grid_remove()
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        import customtkinter as ctk
        
        
        root = ctk.CTk()
        app = MainApplication(root)
        
        # 设置窗口图标（如果有的话）
        try:
            root.iconbitmap("icon.ico")
        except:
            pass
        
        root.mainloop()
    except Exception as e:
        logger.error(f"应用程序错误: {e}", exc_info=True)
        messagebox.showerror(
            "应用程序错误",
            f"程序遇到错误:\n{str(e)}\n\n详细信息请查看日志文件"
        )