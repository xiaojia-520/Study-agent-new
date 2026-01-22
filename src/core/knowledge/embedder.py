# 知识业务逻辑：文本向量化，只做业务调用，不关心模型加载细节
from typing import List
from src.infrastructure.model_hub import model_hub
from src.infrastructure.logger import get_logger

logger = get_logger("TextEmbedder")


class TextEmbedder:
    """文本向量化器：业务逻辑-调用向量模型生成文本向量"""

    def __init__(self):
        self.embed_model = model_hub.load_embed_model()
        logger.info("文本向量化器初始化完成")

    def embed_text(self, text: str) -> List[float]:
        """业务核心：输入清洗后的文本，输出向量列表"""
        if not text:
            return []
        # 调用向量模型生成向量（归一化处理，提升检索效果）
        vector = self.embed_model.encode(text, normalize_embeddings=True).tolist()
        logger.debug(f"文本向量化完成，文本: {text}，向量长度: {len(vector)}")
        return vector
