# 核心中的核心：业务逻辑编排层，语音转写入库的「业务大脑」
# 职责：调用所有Core层的业务模块 + 调用Infrastructure层的存储接口，完成完整业务流程
# ✅ 无任何技术细节、无任何硬编码、无任何第三方API调用
import uuid
import time
from typing import Dict
from src.infrastructure.storage.file_storage import file_storage
from src.infrastructure.storage.vector_storage import vector_storage
from src.core.asr.text_postprocessor import TextPostProcessor
from src.core.knowledge.embedder import TextEmbedder
from src.infrastructure.logger import get_logger

logger = get_logger("KBManager")


class KBManager:
    """知识库管理器：业务逻辑总编排 - 文本后处理 → 生成向量 → JSONL入库 → Qdrant入库"""

    def __init__(self):
        self.text_processor = TextPostProcessor()
        self.embedder = TextEmbedder()
        logger.info("知识库管理器初始化完成，双库入库准备就绪")

    def process_and_save(self, raw_transcript: str) -> Dict[str, any]:
        """
        核心业务入口：完整的「转写文本→入库」业务流程
        :param raw_transcript: ASR转写的原始文本
        :return: 入库的完整数据记录
        """
        # 步骤1：文本后处理（业务规则）
        clean_text = self.text_processor.process(raw_transcript)
        if not clean_text:
            logger.warning("清洗后的文本为空，跳过入库")
            return {}

        # 步骤2：生成唯一标识+元数据（业务规则）
        record_id = str(uuid.uuid4())
        current_time = int(time.time())
        record_data = {
            "id": record_id,
            "raw_text": raw_transcript,
            "clean_text": clean_text,
            "create_time": current_time,
            "source": "speech_transcript"
        }

        # 步骤3：文本向量化（业务规则）
        vector = self.embedder.embed_text(clean_text)
        if not vector:
            logger.warning("向量生成失败，跳过向量入库")
            return record_data

        # 步骤4：双库入库（调用基础设施层的存储接口，无技术细节）
        file_storage.write_transcript(record_data)  # JSONL入库
        vector_storage.add_vector(vector, record_data)  # Qdrant向量入库

        logger.info(f"✅ 完整入库完成 | 清洗后文本: {clean_text}")
        return record_data
