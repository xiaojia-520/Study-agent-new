# 转写业务逻辑：文本后处理，纯业务规则，无任何技术细节
import re
from src.infrastructure.logger import get_logger

logger = get_logger("TextPostProcessor")


class TextPostProcessor:
    """文本后处理器：业务规则-清洗转写文本，提升文本质量"""

    def __init__(self):
        # 业务规则：需要清洗的口语化无意义词汇
        self.useless_words = ["嗯", "啊", "呃", "哦", "哎", "嘛", "呢", "吧"]
        self.useless_pattern = re.compile(r"|".join(self.useless_words))
        logger.info("文本后处理器初始化完成")

    def process(self, raw_text: str) -> str:
        """业务核心：清洗文本的完整规则链"""
        if not raw_text:
            return ""

        # 规则1：去除无意义口语词
        clean_text = self.useless_pattern.sub("", raw_text)
        # 规则2：去除多余空格和连续标点
        clean_text = re.sub(r"\s+", "", clean_text)
        clean_text = re.sub(r"([，。！？；：])\1+", r"\1", clean_text)
        # 规则3：首尾去空
        clean_text = clean_text.strip()

        if clean_text != raw_text:
            logger.debug(f"文本清洗完成: {raw_text} -> {clean_text}")
        return clean_text