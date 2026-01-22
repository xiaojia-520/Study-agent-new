# 纯技术封装：Qdrant向量库的读写操作，只做技术实现，无业务逻辑
# 核心：Core层只调用 add_vector/search_vector，不关心Qdrant的底层API
from typing import List, Dict, Any, Optional
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct, UpdateStatus
from src.infrastructure.logger import get_logger
from config.settings import settings

logger = get_logger("VectorStorage")


class QdrantVectorStorage:
    """向量存储：专门存储转写文本的向量数据"""

    def __init__(self):
        self.client = QdrantClient(url=settings.QDRANT_URL)
        self.collection_name = settings.QDRANT_COLLECTION
        self._init_collection()
        logger.info(f"Qdrant向量存储初始化完成，集合: {self.collection_name}")

    def _init_collection(self):
        """初始化集合：不存在则创建"""
        if not self.client.collection_exists(collection_name=self.collection_name):
            if settings.QDRANT_CREATE_IF_NOT_EXIST:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.VECTOR_DIM,
                        distance=Distance.COSINE  # 文本相似度用余弦距离最优
                    )
                )
                logger.info(f"创建新的Qdrant集合: {self.collection_name}")
            else:
                raise ValueError(f"集合 {self.collection_name} 不存在")

    def add_vector(self, vector: List[float], metadata: Dict[str, Any], vector_id: Optional[int] = None) -> None:
        """新增单条向量数据（核心写入接口）"""
        point = PointStruct(
            id=vector_id,
            vector=vector,
            payload=metadata
        )
        response = self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        if response.status == UpdateStatus.COMPLETED:
            logger.debug(f"成功写入向量，元数据: {metadata}")
        else:
            logger.error(f"向量写入失败: {response}")


# 全局单例向量存储实例
vector_storage = QdrantVectorStorage()
