"""气泡式工具提示管理器。

从 ``main_gui.py`` 抽出，便于复用与单独维护。
仅依赖 Tkinter，不引入新依赖。
"""

from __future__ import annotations

import logging
import tkinter as tk

logger = logging.getLogger(__name__)


class ToolTipManager:
    """管理工具提示的类"""

    def __init__(self, root):
        self.root = root
        self.current_tip = None
        self.tip_windows = {}  # 存储每个按钮的提示窗口
        self.tip_ids = {}  # 存储延迟显示的ID
        # 新增：点击后的抑制目标（在鼠标离开该按钮之前不再显示提示）
        self.suppressed_widget = None

    def bind_tooltip(self, widget, text):
        """为控件绑定工具提示"""
        # 改为鼠标移动时显示提示
        widget.bind("<Motion>", lambda e, w=widget, t=text: self.show_tip(w, t))
        # 离开控件时，隐藏并解除抑制
        widget.bind("<Leave>", lambda e, w=widget: self._on_leave(w))
        # 点击控件时，隐藏并对该控件设置抑制（使用更具体的左键事件）
        widget.bind("<Button-1>", lambda e, w=widget: self._on_click(w))

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
        canvas.create_rectangle(
            x1 + r, y1, x2 - r, y2, fill=fill, outline=local_outline
        )
        canvas.create_rectangle(
            x1, y1 + r, x2, y2 - r, fill=fill, outline=local_outline
        )
        canvas.create_arc(
            x1,
            y1,
            x1 + 2 * r,
            y1 + 2 * r,
            start=90,
            extent=90,
            style=tk.PIESLICE,
            fill=fill,
            outline=local_outline,
        )
        canvas.create_arc(
            x2 - 2 * r,
            y1,
            x2,
            y1 + 2 * r,
            start=0,
            extent=90,
            style=tk.PIESLICE,
            fill=fill,
            outline=local_outline,
        )
        canvas.create_arc(
            x2 - 2 * r,
            y2 - 2 * r,
            x2,
            y2,
            start=270,
            extent=90,
            style=tk.PIESLICE,
            fill=fill,
            outline=local_outline,
        )
        canvas.create_arc(
            x1,
            y2 - 2 * r,
            x1 + 2 * r,
            y2,
            start=180,
            extent=90,
            style=tk.PIESLICE,
            fill=fill,
            outline=local_outline,
        )

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
            tip.wm_attributes("-toolwindow", True)
            tip.wm_attributes("-topmost", True)

            # 透明色用于绘制尾巴（支持则使用）
            trans_color = "#00ffff"
            try:
                tip.wm_attributes("-transparentcolor", trans_color)
            except Exception:
                trans_color = None  # 不支持透明则回退

            # 气泡样式（白色背景）
            bubble_bg = "#ffffff"
            text_color = "#333333"
            font_cfg = ("Microsoft YaHei", 9)

            # 先测量文本尺寸
            canvas = tk.Canvas(
                tip, bg=trans_color or "#e0e0e0", highlightthickness=0, bd=0
            )
            tmp_id = canvas.create_text(0, 0, text=text, font=font_cfg, anchor="nw")
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
            self._draw_rounded_rect(
                canvas, rect_x1, rect_y1, rect_x2, rect_y2, radius, bubble_bg, ""
            )

            # 尾巴（三角）指向按钮：右侧显示=>左边尾巴；左侧显示=>右边尾巴
            if tail_size > 0:
                mid_y = (rect_y1 + rect_y2) // 2
                if show_on_right:
                    points = [
                        rect_x1,
                        mid_y - 6,
                        rect_x1 - tail_size,
                        mid_y,
                        rect_x1,
                        mid_y + 6,
                    ]
                else:
                    points = [
                        rect_x2,
                        mid_y - 6,
                        rect_x2 + tail_size,
                        mid_y,
                        rect_x2,
                        mid_y + 6,
                    ]
                # 取消尾巴边框
                canvas.create_polygon(points, fill=bubble_bg, outline="")

            # 文本
            canvas.create_text(
                rect_x1 + pad_x,
                rect_y1 + pad_y,
                text=text,
                font=font_cfg,
                fill=text_color,
                anchor="nw",
            )

            # 位置
            tip.update_idletasks()
            if show_on_right:
                x = right_x  # 尾巴尖端贴近按钮右边+8px
            else:
                x = widget.winfo_rootx() - (bubble_w + tail_size) - 8
            y = center_y - (total_h // 2)
            tip.wm_geometry(f"+{x}+{y}")

            self.current_tip = tip
            self.tip_windows[widget] = tip
            try:
                tip.attributes("-alpha", 0.98)
            except Exception:
                pass

            tip.bind("<Enter>", lambda e: self._keep_tip())
            tip.bind("<Leave>", lambda e: self.hide_tip())
            # 新增：点击提示气泡本身也隐藏
            tip.bind("<ButtonPress>", lambda e: self.hide_tip())

        except Exception as e:
            logger.error(f"创建工具提示失败: {e}")

    def _keep_tip(self):
        """保持提示显示"""
        pass  # 当鼠标进入提示框时，不隐藏

    def hide_tip(self):
        """隐藏所有工具提示"""
        # 取消所有延迟显示
        for _widget, tip_id in list(self.tip_ids.items()):
            if tip_id:
                self.root.after_cancel(tip_id)
        self.tip_ids.clear()

        # 销毁所有提示窗口
        if self.current_tip:
            try:
                self.current_tip.destroy()
            except Exception:
                pass
            self.current_tip = None

        for _widget, tip in list(self.tip_windows.items()):
            if tip:
                try:
                    tip.destroy()
                except Exception:
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
