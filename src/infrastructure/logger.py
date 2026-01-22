# 纯技术封装：全系统复用的日志能力，无任何业务逻辑
import logging
import sys
from pathlib import Path
from config.settings import settings

# 日志目录
LOG_DIR = settings.BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "speech2db.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
