# script/init_mock_data.py
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from connectors.graph_client import Neo4jClient

def init_database():
    client = Neo4jClient()
    
    # 写入测试数据的 Cypher 语句 (对应你开题报告表1的内容)
    cypher_query = """
    // 1. 创建任务节点
    MERGE (task1:Task {name: 'Batch Correction'})
    
    // 2. 创建模态节点
    MERGE (mod1:Modality {name: 'scRNA-seq'})
    
    // 3. 创建工具 Harmony 及其关系
    MERGE (tool1:Tool {name: 'Harmony', description: '基于迭代聚类与线性校正的批次效应去除工具'})
    MERGE (tool1)-[:PERFORMS_TASK]->(task1)
    MERGE (tool1)-[:SUPPORTS_MODALITY]->(mod1)
    
    // 4. 创建工具 scVI 及其关系
    MERGE (tool2:Tool {name: 'scVI', description: '基于变分自编码器(VAE)的深度学习整合工具'})
    MERGE (tool2)-[:PERFORMS_TASK]->(task1)
    MERGE (tool2)-[:SUPPORTS_MODALITY]->(mod1)
    
    // 5. 创建长读长任务和工具 (为后续的迁移推理做准备)
    MERGE (task2:Task {name: 'DTU Analysis'})
    MERGE (mod2:Modality {name: 'Nanopore'})
    MERGE (tool3:Tool {name: 'FLAMES', description: '针对长读长单细胞的异构体定量工具'})
    MERGE (tool3)-[:PERFORMS_TASK]->(task2)
    MERGE (tool3)-[:SUPPORTS_MODALITY]->(mod2)
    """
    
    print("正在向云端 Neo4j 注入初始测试数据...")
    client.execute_query(cypher_query)
    print("✅ 数据注入完成！")
    client.close()

if __name__ == "__main__":
    init_database()