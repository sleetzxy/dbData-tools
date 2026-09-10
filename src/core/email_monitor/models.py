"""邮件附件监控配置模型与校验。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MonitorConfig:
    """IMAP 邮件附件监控配置。

    :param host: IMAP 主机。
    :param port: IMAP 端口。
    :param use_ssl: 是否使用 SSL。
    :param account: 邮箱账号。
    :param password: 密码或授权码。
    :param senders: 发件人白名单列表。
    :param download_dir: 附件下载目录。
    :param extensions: 扩展名白名单（如 ``.csv``）。
    :param lookback_days: 检索最近 N 天邮件。
    :param interval_seconds: 轮询间隔（秒）。
    """

    host: str = "imap.exmail.qq.com"
    port: int = 993
    use_ssl: bool = True
    account: str = ""
    password: str = ""
    senders: list[str] = field(default_factory=list)
    download_dir: str = ""
    extensions: list[str] = field(default_factory=list)
    lookback_days: int = 7
    interval_seconds: int = 60


def validate_monitor_config(cfg: MonitorConfig) -> list[str]:
    """校验监控配置，返回错误文案列表（空列表表示通过）。

    :param cfg: 待校验配置。
    :return: 错误信息列表；空表示可启动监控。
    """
    errors: list[str] = []

    if not str(cfg.host).strip():
        errors.append("IMAP 主机不能为空")

    try:
        port = int(cfg.port)
    except (TypeError, ValueError):
        port = 0
    if port < 1:
        errors.append("端口无效")

    if not str(cfg.account).strip():
        errors.append("账号不能为空")

    if not cfg.password:
        errors.append("密码不能为空")

    if not any(str(s).strip() for s in cfg.senders):
        errors.append("至少需要一个发件人")

    download_dir = str(cfg.download_dir).strip()
    if not download_dir:
        errors.append("下载目录不能为空")
    else:
        path = Path(download_dir)
        if not path.exists() or not path.is_dir():
            errors.append("下载目录不存在或不是目录")
        elif not os.access(path, os.W_OK):
            errors.append("下载目录不可写")

    if not any(str(ext).strip() for ext in cfg.extensions):
        errors.append("扩展名白名单不能为空")

    if int(cfg.lookback_days) < 1:
        errors.append("最近 N 天必须 ≥ 1")

    if int(cfg.interval_seconds) < 1:
        errors.append("轮询间隔必须 ≥ 1 秒")

    return errors
