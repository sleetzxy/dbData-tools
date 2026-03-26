import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    配置管理类，用于统一管理各个应用的配置文件
    """
    def __init__(self, config_file: str):
        """
        初始化配置管理器
        
        参数:
            config_file: 配置文件路径，支持使用~表示用户目录
        """
        self.config_file = os.path.expanduser(config_file)
        self.config = {}

    def load(self, logger: logging) -> Dict[str, Any]:
        """
        从文件加载配置
        
        返回:
            配置字典
        """
        if not os.path.exists(self.config_file):
            logger.info(f"配置文件不存在: {self.config_file}，将使用默认配置")
            return self.config
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            logger.info(f"配置已从 {self.config_file} 加载")
            return self.config
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            return {}
    
    def save(self, config: Dict[str, Any], logger: logging) -> bool:
        """
        保存配置到文件
        
        参数:
            config: 要保存的配置字典
            
        返回:
            保存是否成功
        """
        self.config = config
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            logger.info(f"配置已保存到 {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        参数:
            key: 配置项键名
            default: 默认值，当键不存在时返回
            
        返回:
            配置项的值
        """
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """
        设置配置项
        
        参数:
            key: 配置项键名
            value: 配置项的值
        """
        self.config[key] = value