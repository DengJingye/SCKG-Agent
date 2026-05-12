import json
import sys
from pathlib import Path

# 自动处理路径
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from connectors.graph_client import Neo4jClient
from core.models import derived_evidence
from core.settings import get_settings

def restore_from_backup():
    client = Neo4jClient()
    settings = get_settings()
    jsonl_path = get_settings().data_dir / "scKG_embeddings_backup.jsonl"
    
    if not jsonl_path.exists():
        print(f"❌ 错误：没找到备份文件 {jsonl_path}")
        return

    print("🚀 开始从本地备份恢复图谱灵魂...")
    count = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line.strip())
            tool_name = data["tool_name"]
            llm_data = data["llm_extracted_data"]
            embedding = data["embedding"]
            
            # 极简 Cypher，只负责把存好的东西写进去
            cypher = """
            MERGE (t:Tool {name: $name})
            SET t.github_url = $url,
                t.description = $desc
            
            WITH t
            MERGE (a:Algorithm {name: $name + "_Algorithm"})
            SET a.features = $features,
                a.embedding = $embedding
            MERGE (t)-[:IMPLEMENTS_ALGORITHM]->(a)
            """
            params = {
                "name": tool_name,
                "url": data["github_url"],
                "desc": llm_data.get("algorithm_features", ""),
                "features": llm_data.get("algorithm_features", ""),
                "embedding": embedding
            }
            client.execute_query(cypher, params)
            evidence = derived_evidence(
                evidence_id=f"backup:{tool_name}:algorithm_features",
                metric_name="algorithm_features",
                metric_value=llm_data.get("algorithm_features", ""),
                extraction_method="data_pipeline/hybrid_loader.py",
                source_title=f"Local JSONL backup for {tool_name}",
                confidence=0.6,
                kg_version=settings.kg_version,
            )
            client.upsert_evidence(tool_name, evidence)
            count += 1
            print(f"✅ 已恢复: {tool_name}")

    print(f"\n🎉 大功告成！成功恢复 {count} 个核心工具到新数据库。")
    client.close()

if __name__ == "__main__":
    restore_from_backup()
