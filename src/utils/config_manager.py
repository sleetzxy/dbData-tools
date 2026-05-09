"""JSON 配置文件的加载、保存与键值访问。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any


class ConfigManager:
    """统一管理应用 JSON 配置文件路径与内存中的配置字典。"""

    def __init__(self, config_file: str) -> None:
        """初始化配置管理器。

        :param config_file: 配置文件路径，支持 ``~`` 表示用户主目录。
        """
        self.config_file = os.path.expanduser(config_file)
        self.config: dict[str, Any] = {}

    def load(self, logger: logging.Logger) -> dict[str, Any]:
        """从磁盘读取 JSON 配置；文件不存在时返回当前内存中的配置。

        :param logger: 用于输出提示与错误信息的记录器。
        :return: 加载成功后的配置字典；失败时返回空字典。
        """
        if not os.path.exists(self.config_file):
            logger.info(f"配置文件不存在: {self.config_file}，将使用默认配置")
            return self.config

        try:
            with open(self.config_file, encoding="utf-8") as f:
                self.config = json.load(f)
            logger.info(f"配置已从 {self.config_file} 加载")
            return self.config
        except (OSError, json.JSONDecodeError) as e:
            logger.error("加载配置失败: %s", e)
            return {}

    def save(self, config: dict[str, Any], logger: logging.Logger) -> bool:
        """将配置字典写入 JSON 文件（缩进格式化、UTF-8）。

        :param config: 要持久化的配置字典。
        :param logger: 用于输出提示与错误信息的记录器。
        :return: 写入成功为 ``True``，否则为 ``False``。
        """
        self.config = config
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            logger.info(f"配置已保存到 {self.config_file}")
            return True
        except (OSError, TypeError) as e:
            logger.error("保存配置失败: %s", e)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """按键读取配置项。

        :param key: 配置键名。
        :param default: 键不存在时返回的默认值。
        :return: 配置值或 ``default``。
        """
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """在内存中设置配置项（需调用 :meth:`save` 才会落盘）。

        :param key: 配置键名。
        :param value: 配置值。
        """
        self.config[key] = value
