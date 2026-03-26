import logging


def get_logger(logger_name: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    获取或创建一个命名的日志记录器
    
    参数:
        logger_name: 日志记录器名称
        level: 日志级别，默认为DEBUG
        
    返回:
        配置好的logger对象
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
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # 添加处理器到logger
    logger.addHandler(console_handler)
    
    # 设置为不传播到父日志记录器
    logger.propagate = False
    
    return logger