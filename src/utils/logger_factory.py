"""命名日志记录器的创建与简单控制台输出配置。"""

import logging


def get_logger(logger_name: str, level: int = logging.DEBUG) -> logging.Logger:
    """获取或创建带控制台处理器的命名日志记录器。

    若记录器已有处理器则直接返回，避免重复挂载。

    :param logger_name: 记录器名称，通常使用模块级常量。
    :param level: 记录器与控制台处理器的日志级别。
    :return: 配置好的 ``Logger`` 实例。
    """
    logger = logging.getLogger(logger_name)

    # 如果logger已经有处理器，说明已经被配置过，直接返回
    if logger.handlers:
        return logger

    # 设置日志级别
    logger.setLevel(level)

    # 创建一个控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # 设置日志格式
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)

    # 添加处理器到logger
    logger.addHandler(console_handler)

    # 设置为不传播到父日志记录器
    logger.propagate = False

    return logger
