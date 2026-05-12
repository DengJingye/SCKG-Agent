# script/test_neo4j.py
import sys
import os
from pathlib import Path

# 获取当前脚本的绝对路径，并自动往上推一层，将项目根目录 (scKG_Agent) 加入到 Python 搜索路径中
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 路径配好后，再导入我们自己写的模块就没问题了
from connectors.graph_client import Neo4jClient

if __name__ == "__main__":
    print("--- 开始测试 Neo4j 客户端 ---")
    client = Neo4jClient()
    
    # 执行一个最简单的连通性查询
    res = client.execute_query("RETURN 'Hello scKG-Atlas!' AS message")
    print(f"数据库返回: {res}")
    
    # 模拟一次硬约束检索 (因为库里还没数据，所以大概率返回空列表)
    tools = client.find_candidates_by_hard_constraints(task="Batch Correction", modality="scRNA-seq")
    print(f"检索到的工具候选集: {tools}")
    
    client.close()