import sys
import numpy as np
import requests
from pathlib import Path

# 确保能够导入图谱连接器
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from connectors.graph_client import Neo4jClient
from core.logging_config import get_logger
from core.settings import get_settings

logger = get_logger(__name__)

class IsomorphismAnalyzer:
    """
    全量图谱驱动的算法同构性分析引擎
    利用 NumPy 矩阵运算在本地极速完成 1700+ 高维向量的比对。
    """
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.require_embedding_api_key()
        self.api_base = settings.embedding_api_base
        self.model_name = settings.embedding_model
        self.db_client = Neo4jClient() # 实例化数据库连接

    def get_embedding(self, text: str) -> np.ndarray:
        """调用 BGE-M3 获取用户意图的高维稠密向量"""
        if not text:
            return np.zeros(1024)
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": self.model_name, "input": text}
        
        try:
            response = requests.post(self.api_base, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            embedding = response.json()["data"][0]["embedding"]
            return np.array(embedding)
        except Exception as e:
            logger.warning("Intent embedding failed: %s", e)
            return np.zeros(1024)

    def search_isomorphic_tools(self, requirement_text: str, top_k: int = 3) -> list:
        """
        核心检索引擎：去 Neo4j 拉取所有算法特征，与用户需求进行相似度碰撞。
        """
        # 1. 将用户的需求转化为向量
        target_vec = self.get_embedding(requirement_text)
        if np.all(target_vec == 0):
            return []

        # 2. 从图谱中全量拉取算法向量
        cypher = """
        MATCH (t:Tool)-[:IMPLEMENTS_ALGORITHM]->(a:Algorithm)
        WHERE a.embedding IS NOT NULL
        RETURN t.name AS tool_name, a.features AS features, a.embedding AS embedding
        """
        try:
            results = self.db_client.execute_query(cypher)
        except Exception as e:
            logger.exception("Failed to query graph algorithm library")
            return []

        if not results:
            return []

        # 3. 极速矩阵运算：计算余弦相似度
        tools_scored = []
        target_norm = np.linalg.norm(target_vec)
        
        if target_norm == 0:
            return []

        for row in results:
            vec = np.array(row["embedding"])
            vec_norm = np.linalg.norm(vec)
            
            if vec_norm == 0:
                continue
                
            # Cosine Similarity 公式
            cos_sim = np.dot(target_vec, vec) / (target_norm * vec_norm)
            
            tools_scored.append({
                "tool_name": row["tool_name"],
                "features": row["features"],
                "similarity": float(cos_sim)
            })

        # 4. 按相似度倒序排列，返回 Top K
        tools_scored.sort(key=lambda x: x["similarity"], reverse=True)
        return tools_scored[:top_k]

    def close(self):
        self.db_client.close()
