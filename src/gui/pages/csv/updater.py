"""
重构后的 CSV 加解密页面 - 使用新的基类和组件架构
"""
import tkinter as tk
import os
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import PathSelector
from gui.widgets.labels import TitleLabel, StyledLabel
from gui.widgets.buttons import PrimaryButton
from core.updater_csv import load_mapping, process_csv_files, logger as core_logger


class UpdateCsvPage(BaseToolPage):
    """
    CSV 加解密页面 - 重构版本

    使用 BaseToolPage 基类,提供:
    - 标准的左右面板布局
    - 配置管理功能
    - 日志记录功能
    - 线程执行功能
    """

    CONFIG_FILE = "~/.csv_updater_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 处理日志",
            core_logger=core_logger
        )

    def setup_left_panel_content(self, parent):
        """设置左侧面板的具体内容"""
        # 标题
        title = TitleLabel(parent, text="🔄 CSV 加解密")
        title.pack(anchor='w', pady=(0, 15))

        # 映射文件路径选择器
        self.mapping_selector = PathSelector(
            parent,
            label_text="映射文件路径（.csv）",
            mode="file",
            file_types=[("CSV文件", "*.csv"), ("所有文件", "*.*")]
        )
        self.mapping_selector.pack(fill='x', pady=(0, 15))

        # 输入文件夹路径选择器
        self.input_selector = PathSelector(
            parent,
            label_text="输入文件夹（原始CSV）",
            mode="folder"
        )
        self.input_selector.pack(fill='x', pady=(0, 15))

        # 操作模式选择
        mode_label = StyledLabel(parent, text="操作模式")
        mode_label.pack(anchor='w', pady=(0, 3))

        mode_frame = self.ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8
        )
        mode_frame.pack(anchor='w', fill='x', pady=(0, 15))

        # 内部容器，用于居中对齐单选按钮
        mode_inner_frame = self.ctk.CTkFrame(mode_frame, fg_color=self.idea_dark_colors["card_bg"])
        mode_inner_frame.pack(pady=15)

        self.mode_var = tk.StringVar(value='encrypt')
        # 加密单选按钮
        self.encrypt_radio = self.ctk.CTkRadioButton(
            mode_inner_frame,
            text="加密",
            variable=self.mode_var,
            value='encrypt',
            font=('Microsoft YaHei', 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"]
        )
        self.encrypt_radio.pack(side='left', padx=(20, 30))

        # 解密单选按钮
        self.decrypt_radio = self.ctk.CTkRadioButton(
            mode_inner_frame,
            text="解密",
            variable=self.mode_var,
            value='decrypt',
            font=('Microsoft YaHei', 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"]
        )
        self.decrypt_radio.pack(side='left')

        # 开始执行按钮
        self.execute_button = PrimaryButton(
            parent,
            text="🚀 开始执行",
            command=self.start_task
        )
        self.execute_button.pack(anchor='w', fill='x', pady=(10, 0))

    def get_config_dict(self):
        """返回要保存的配置字典"""
        return {
            'mapping_file': self.mapping_selector.get_path(),
            'input_folder': self.input_selector.get_path(),
            'mode': self.mode_var.get()
        }

    def apply_config(self, config):
        """应用加载的配置"""
        try:
            # 设置映射文件路径
            mapping_file = config.get('mapping_file', '')
            if mapping_file:
                self.mapping_selector.set_path(mapping_file)

            # 设置输入文件夹路径
            input_folder = config.get('input_folder', '')
            if input_folder:
                self.input_selector.set_path(input_folder)

            # 设置操作模式
            self.mode_var.set(config.get('mode', 'encrypt'))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {str(e)}")

    def start_task(self):
        """启动处理任务"""
        self.run_task(
            button_widget=self.execute_button,
            button_text="🚀 开始执行",
            running_text="处理中..."
        )

    def execute_task(self):
        """执行加解密任务 - 在后台线程中运行"""
        # 验证参数
        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        mapping_file = self.mapping_selector.get_path()
        input_folder = self.input_selector.get_path()
        mode = self.mode_var.get()

        if self.logger:
            mode_text = "加密" if mode == 'encrypt' else "解密"
            self.logger.info(f"开始{mode_text}处理...")
            self.logger.info(f"映射文件: {mapping_file}")
            self.logger.info(f"输入文件夹: {input_folder}")

        try:
            # 加载映射关系
            table_mapping, column_mapping = load_mapping(mapping_file, mode)
            # 处理CSV文件
            result = process_csv_files(input_folder, table_mapping, column_mapping, mode)

            if result["success"]:
                mode_text = "加密" if mode == 'encrypt' else "解密"
                if self.logger:
                    self.logger.info(f"{mode_text}处理完成")
            else:
                error_msg = result.get("error", "处理过程中发生错误")
                if self.logger:
                    self.logger.error(f"处理失败: {error_msg}")

            return result

        except Exception as e:
            error_msg = f"处理失败: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def validate(self):
        """验证输入参数"""
        mapping_file = self.mapping_selector.get_path()
        input_folder = self.input_selector.get_path()

        if not mapping_file:
            messagebox.showerror("错误", "请选择映射文件")
            return False

        if not os.path.isfile(mapping_file):
            messagebox.showerror("错误", "映射文件无效或不存在")
            return False

        if not input_folder:
            messagebox.showerror("错误", "请选择输入文件夹")
            return False

        if not os.path.isdir(input_folder):
            messagebox.showerror("错误", "输入文件夹无效或不存在")
            return False

        return True

    def on_task_success(self, result):
        """任务成功完成时的回调"""
        messagebox.showinfo("完成", "处理成功！")

    def on_task_error(self, result):
        """任务失败时的回调"""
        error_msg = result.get("error", "处理过程中发生错误")
        messagebox.showerror("错误", error_msg)


# 向后兼容别名
UpdateCsvApp = UpdateCsvPage
