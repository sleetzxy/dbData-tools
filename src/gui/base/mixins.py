"""
混入类模块 - 提供可复用的功能混入
"""
import tkinter as tk
import json
from pathlib import Path
from typing import Optional, List, Dict
from gui.utils.gui_utils import safe_configure


class ConnectionMixin:
    """数据库连接管理混入类"""

    CONNECTIONS_FILE = "~/.connections.json"

    def __init__(self):
        self.connections: List[Dict] = []
        self.connection_names: List[str] = []

    def load_connections_and_update(self):
        """加载连接并更新下拉框"""
        try:
            connections_file = Path(self.CONNECTIONS_FILE).expanduser()
            if connections_file.exists():
                with open(connections_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 处理不同格式
                    if isinstance(data, dict):
                        self.connections = data.get('connections', [])
                    elif isinstance(data, list):
                        self.connections = data
                    else:
                        self.connections = []
            else:
                # 文件不存在时创建默认连接
                self.connections = [{
                    'name': '默认连接',
                    'host': 'localhost',
                    'port': '5432',
                    'user': 'postgres',
                    'password': 'postgres',
                    'database': 'postgres',
                    'schema': 'public'
                }]
                # 确保目录存在
                connections_file.parent.mkdir(parents=True, exist_ok=True)
                with open(connections_file, 'w', encoding='utf-8') as f:
                    json.dump(self.connections, f, indent=4)

            # 更新下拉框
            self.update_connections_combobox()
        except Exception as e:
            self.connections = []
            if hasattr(self, 'connection_menu'):
                try:
                    safe_configure(self.connection_menu, values=["加载连接失败"])
                    self.connection_menu.set("加载连接失败")
                except tk.TclError:
                    pass
            if hasattr(self, 'logger') and self.logger:
                self.logger.error(f"加载连接失败: {str(e)}")

    def update_connections_combobox(self):
        """更新连接下拉框内容"""
        try:
            if not hasattr(self, 'connection_menu') or not self.connection_menu or not self.connection_menu.winfo_exists():
                return

            if not self.connections:
                try:
                    safe_configure(self.connection_menu, values=["无可用连接"])
                    self.connection_menu.set("无可用连接")
                    self.connection_var.set("无可用连接")
                except tk.TclError:
                    pass
                self.connection_names = []
                return

            names = [
                f"{c.get('name', '未命名连接')} ({c.get('host', '')}:{c.get('port', '')})"
                for c in self.connections
            ]
            self.connection_names = names
            safe_configure(self.connection_menu, values=names)

            # 如果当前选择已在新列表中,保持不变;否则按配置或首项回退
            current_value = self.connection_var.get()
            if current_value in names:
                try:
                    self.connection_menu.set(current_value)
                except tk.TclError:
                    pass
            else:
                # 尝试使用已加载的配置中的连接名恢复
                saved_name = None
                try:
                    saved_name = self.config_manager.get('selected_connection_name')
                except Exception:
                    saved_name = None

                if saved_name:
                    idx = self._find_connection_index_by_name(saved_name)
                    if idx is not None and 0 <= idx < len(names):
                        try:
                            self.connection_menu.set(names[idx])
                            self.connection_var.set(names[idx])
                            return
                        except tk.TclError:
                            pass

                # 最后回退到第一项
                try:
                    self.connection_menu.set(names[0])
                    self.connection_var.set(names[0])
                except tk.TclError:
                    pass
        except Exception as e:
            if hasattr(self, 'logger') and self.logger:
                self.logger.error(f"更新连接下拉框失败: {str(e)}")

    def get_selected_connection_name(self) -> Optional[str]:
        """获取当前选中连接的名称"""
        try:
            current_value = self.connection_var.get()
            if current_value:
                name = current_value.split(" (", 1)[0]
                return name if name else None
        except Exception:
            pass
        return None

    def find_connection_index_by_name(self, name: str) -> Optional[int]:
        """通过连接名称查找索引"""
        if not name:
            return None
        for i, c in enumerate(self.connections):
            if c.get('name') == name:
                return i
        return None

    def get_selected_connection(self) -> Optional[Dict]:
        """获取当前选中的连接配置"""
        selected_name = self.get_selected_connection_name()
        selected_index = self.find_connection_index_by_name(selected_name)
        if selected_index is None or selected_index < 0 or selected_index >= len(self.connections):
            return None
        return self.connections[selected_index]


class ConfigMixin:
    """配置管理混入类"""

    def __init__(self, config_file: str):
        from utils.config_manager import ConfigManager
        self.config_manager = ConfigManager(config_file)

    def save_config(self, config: Dict) -> bool:
        """保存配置"""
        from core.importer_csv import logger as core_logger
        success = self.config_manager.save(config, core_logger)
        if not success and hasattr(self, 'logger') and self.logger:
            self.logger.warning("配置保存失败")
        return success

    def load_config(self) -> Optional[Dict]:
        """加载配置"""
        from core.importer_csv import logger as core_logger
        config = self.config_manager.load(core_logger)
        if not config:
            if hasattr(self, 'logger') and self.logger:
                self.logger.info("未找到配置文件,使用默认设置")
        return config
