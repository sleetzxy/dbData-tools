"""邮件附件监控核心包。"""

from core.email_monitor.models import MonitorConfig, validate_monitor_config
from core.email_monitor.service import EmailMonitorService

__all__ = [
    "EmailMonitorService",
    "MonitorConfig",
    "validate_monitor_config",
]
