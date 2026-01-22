# 纯技术封装：JSONL文件的读写操作，只做技术实现，无任何业务逻辑
# ✅ 核心优化：支持动态传入文件路径，不再固定死文件名
import jsonlines
from typing import Dict, List, Any
from pathlib import Path
from src.infrastructure.logger import get_logger
from config.settings import settings

logger = get_logger("FileStorage")


class JsonlFileStorage:
    """JSONL文件存储：专门存储语音转写后的文本数据【支持动态文件路径】"""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        # 确保文件的上级目录存在（比如transcripts）
        self.file_path.parent.mkdir(exist_ok=True, parents=True)
        # 确保文件存在
        if not self.file_path.exists():
            self.file_path.touch()
        logger.info(f"✅ JSONL存储初始化完成，当前文件: {self.file_path}")

    def write_transcript(self, data: Dict[str, Any]) -> None:
        """增量写入单条转写记录（核心写入接口，逻辑不变）"""
        with jsonlines.open(self.file_path, mode='a', encoding='utf-8') as writer:
            writer.write(data)
        logger.debug(f"成功写入JSONL: {data}")

    def read_all_transcripts(self) -> List[Dict[str, Any]]:
        """读取当前文件的所有转写记录（逻辑不变）"""
        data_list = []
        with jsonlines.open(self.file_path, mode='r', encoding='utf-8') as reader:
            for obj in reader:
                data_list.append(obj)
        return data_list
