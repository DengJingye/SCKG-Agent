# data_pipeline/neo4j_loader.py
import sys
import json
import time
import requests
import pandas as pd
from tqdm import tqdm
from pathlib import Path

# 将项目根目录加入环境变量
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from connectors.graph_client import Neo4jClient
from core.models import derived_evidence, github_evidence
from core.settings import get_settings
from data_pipeline.github_crawler import GitHubCrawler

def get_bge_embedding(text: str) -> list:
    """调用 BGE-M3 获取高维向量"""
    if not text: return []
    settings = get_settings()
    payload = {"model": settings.embedding_model, "input": text}
    headers = {
        "Authorization": f"Bearer {settings.require_embedding_api_key()}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(settings.embedding_api_base, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"\n   ⚠️ 向量化失败: {e}")
        return []

def extract_logic_with_deepseek(tool_name: str, abstract: str) -> dict:
    """调用 DeepSeek-V3 提取知识图谱硬约束"""
    settings = get_settings()
    url = f"{settings.chat_api_base}/chat/completions"
    prompt = f"""你是一个顶级的单细胞生物信息学专家。请分析工具 [{tool_name}] 的描述："{abstract}"。
请提取以下信息并严格以 JSON 格式返回：
1. "description": 工具的中文一句话简介
2. "supported_tasks": 支持的分析任务列表（如 ["Clustering", "Data Integration"]）
3. "supported_modalities": 支持的模态列表（如 ["scRNA-seq", "scATAC-seq"]）
4. "hardware_requirements": 硬件约束（如 ["CPU"] 或 ["GPU", "CPU"]）
5. "biological_resolution": 作用粒度（如 ["Cellular", "Molecular"]）
6. "algorithm_features": 底层算法与数学原理的详细摘要文本（用于计算同构性）"""
    
    payload = {
        "model": settings.extract_model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    headers = {
        "Authorization": f"Bearer {settings.require_chat_api_key()}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"\n   ⚠️ DeepSeek提取失败: {e}")
        return {}

# ==========================================
# 🌟 知识图谱收割机引擎
# ==========================================
class KnowledgeGraphLoader:
    def __init__(self):
        print("🔧 正在初始化纯血版知识收割机流水线 (DeepSeek-V3 驱动)...")
        self.settings = get_settings()
        self.db_client = Neo4jClient()
        self.crawler = GitHubCrawler()
        self.backup_path = self.settings.data_dir / "scKG_embeddings_backup.jsonl"

    def close(self):
        self.db_client.close()

    def check_tool_exists(self, tool_name: str) -> bool:
        """检查工具是否已存在，支持断点续传"""
        cypher = """
        MATCH (t:Tool {name: $tool_name})-[:IMPLEMENTS_ALGORITHM]->(a:Algorithm)
        RETURN count(t) > 0 AS exists
        """
        try:
            result = self.db_client.execute_query(cypher, {"tool_name": tool_name})
            return result[0]["exists"] if result else False
        except Exception:
            return False

    def ingest_tool(self, tool_name: str, github_url: str, abstract: str, extra_meta: dict):
        """处理单个工具的全流程入库"""
        print(f"\n========================================")
        print(f"🚀 开始收割 [{tool_name}]: {github_url}")

        if self.check_tool_exists(tool_name):
            print(f"   ⏩ 拦截: 图谱中已存在 [{tool_name}]，跳过以节省 Token。")
            return

        # 1. 获取 GitHub 数据 (增加超强异常护盾)
        stars = 10  # 默认值保底
        language = "Unknown"
        try:
            metrics = self.crawler.fetch_repo_metrics(github_url)
            if metrics:
                stars = metrics.get("github_stars", 10)
                raw_lang = metrics.get("language")
                language = raw_lang if raw_lang else "Unknown"
        except Exception as e:
            print(f"   🛡️ GitHub 爬取被拦截或失败，启动静默降级，继续处理核心逻辑...")

        # 2. DeepSeek 抽取逻辑特征
        llm_data = extract_logic_with_deepseek(tool_name, abstract)
        if not llm_data:
            print(f"   ❌ 跳过 [{tool_name}]: 核心特征提取失败。")
            return
            
        algo_features = llm_data.get("algorithm_features", abstract[:200]) # 兜底策略
        
        # 3. BGE-M3 高维向量化
        vector_embedding = get_bge_embedding(algo_features)
        
        # ==========================================
        # 🛡️ 核心保障：本地 JSONL 双重备份
        # ==========================================
        backup_record = {
            "tool_name": tool_name,
            "github_url": github_url,
            "llm_extracted_data": llm_data,
            "embedding": vector_embedding,
            "extra_meta": extra_meta,
            "kg_version": self.settings.kg_version,
            "embedding_version": self.settings.embedding_version
        }
        with open(self.backup_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(backup_record, ensure_ascii=False) + "\n")

        # 4. 终极 Cypher 写入 (带默认值保护)
        cypher_query = """
        MERGE (tool:Tool {name: $tool_name})
        SET tool.description = $desc,
            tool.github_url = $github_url,
            tool.github_stars = $stars,
            tool.license = $license,
            tool.publish_year = $publish_year,
            tool.source_url = $source_url,
            tool.source_type = $source_type,
            tool.extraction_method = $extraction_method,
            tool.extraction_model = $extraction_model,
            tool.confidence = $confidence,
            tool.trust_level = $trust_level,
            tool.graph_layer = $graph_layer,
            tool.use_for = $use_for,
            tool.review_status = $review_status,
            tool.kg_version = $kg_version
            
        MERGE (lang:Language {name: $language})
        MERGE (tool)-[:WRITTEN_IN]->(lang)
        
        WITH tool
        UNWIND $tasks AS task_name
        MERGE (task:Task {name: task_name})
        MERGE (tool)-[:PERFORMS_TASK]->(task)
        
        WITH tool
        UNWIND $modalities AS mod_name
        MERGE (mod:Modality {name: mod_name})
        MERGE (tool)-[:SUPPORTS_MODALITY]->(mod)
        
        WITH tool
        UNWIND $hardware AS hw_name
        MERGE (hw:Hardware {name: hw_name})
        MERGE (tool)-[:REQUIRES_HARDWARE]->(hw)
        
        WITH tool
        UNWIND $resolution AS res_name
        MERGE (res:Resolution {name: res_name})
        MERGE (tool)-[:OPERATES_ON]->(res)
        
        WITH tool
        MERGE (algo:Algorithm {name: $tool_name + "_Algorithm"})
        SET algo.features = $algo_features,
            algo.embedding = $embedding,
            algo.embedding_origin = $embedding_origin,
            algo.embedding_trust = $embedding_trust,
            algo.use_for = $embedding_use_for,
            algo.trust_level = $algo_trust_level,
            algo.graph_layer = $algo_graph_layer
        MERGE (tool)-[:IMPLEMENTS_ALGORITHM]->(algo)
        """
        
        params = {
            "tool_name": tool_name,
            "desc": llm_data.get("description", "No description"),
            "github_url": github_url,
            "stars": stars,
            "language": language,
            "license": extra_meta.get("license", "Unknown"),
            "publish_year": extra_meta.get("year", "Unknown"),
            "source_url": github_url,
            "source_type": "llm_extracted",
            "extraction_method": "data_pipeline/neo4j_loader.py",
            "extraction_model": self.settings.extract_model,
            "confidence": 0.65,
            "trust_level": "model_extracted",
            "graph_layer": "experimental",
            "use_for": ["retrieval"],
            "review_status": "unreviewed",
            "kg_version": self.settings.kg_version,
            "tasks": llm_data.get("supported_tasks", ["General Analysis"]),
            "modalities": llm_data.get("supported_modalities", ["Single-cell"]),
            "hardware": llm_data.get("hardware_requirements", ["Standard CPU"]),
            "resolution": llm_data.get("biological_resolution", ["Cellular"]),
            "algo_features": algo_features,
            "embedding": vector_embedding,
            "embedding_origin": "model_extracted",
            "embedding_trust": "low",
            "embedding_use_for": ["retrieval"],
            "algo_trust_level": "model_extracted",
            "algo_graph_layer": "experimental",
        }
        
        try:
            self.db_client.execute_query(cypher_query, params)
            self._write_evidence_nodes(tool_name, github_url, stars, llm_data, algo_features)
            print(f"   🎉 成功！[{tool_name}] 的多维生态已永久固化入库！")
        except Exception as e:
            print(f"   ❌ 写入数据库失败: {e}")

    def _write_evidence_nodes(
        self,
        tool_name: str,
        github_url: str,
        stars: int,
        llm_data: dict,
        algo_features: str,
    ) -> None:
        evidence_items = [
            github_evidence(
                tool_name=tool_name,
                metric_name="github_stars",
                metric_value=stars,
                source_url=github_url,
                kg_version=self.settings.kg_version,
            ),
            derived_evidence(
                evidence_id=f"llm:{tool_name}:supported_tasks",
                metric_name="supported_tasks",
                metric_value=llm_data.get("supported_tasks", []),
                extraction_method="data_pipeline/neo4j_loader.py",
                source_title=f"LLM extraction for {tool_name}",
                confidence=0.65,
                trust_level="model_extracted",
                graph_layer="experimental",
                evidence_strength="weak",
                use_for=["retrieval"],
                kg_version=self.settings.kg_version,
            ),
            derived_evidence(
                evidence_id=f"llm:{tool_name}:algorithm_features",
                metric_name="algorithm_features",
                metric_value=algo_features,
                extraction_method="data_pipeline/neo4j_loader.py",
                source_title=f"Algorithm feature extraction for {tool_name}",
                confidence=0.65,
                trust_level="model_extracted",
                graph_layer="experimental",
                evidence_strength="exploratory",
                use_for=["retrieval"],
                kg_version=self.settings.kg_version,
            ),
        ]
        for evidence in evidence_items:
            self.db_client.upsert_evidence(tool_name, evidence)

# ==========================================
# 🚀 启动全量清洗与重构
# ==========================================
if __name__ == "__main__":
    loader = KnowledgeGraphLoader()
    csv_path = get_settings().data_dir / "scrna_tools.tsv"
    
    try:
        df = pd.read_csv(csv_path, sep='\t')
        df = df[df['Code'].notna()]
        df = df[df['Code'].str.contains('github.com')]
        tools_to_ingest = df.to_dict('records')
        
        print(f"📦 共加载 {len(tools_to_ingest)} 个有效工具，准备重塑知识宇宙...")
        
        for index, row in tqdm(enumerate(tools_to_ingest), total=len(tools_to_ingest)):
            # 严格以 TSV 中的名字为准，摒弃一切不确定的抓取名
            tool_name = str(row.get('Tool', '')).strip()
            if not tool_name or tool_name.lower() == "nan" or tool_name == "Unknown":
                continue # 脏数据直接扔掉
                
            url = row.get('Code')
            abstract = str(row.get('Description', ''))
            
            extra_meta = {
                "license": str(row.get('License', 'Unknown')),
                "year": str(row.get('Added', 'Unknown'))[:4]
            }
            
            loader.ingest_tool(tool_name, url, abstract, extra_meta)
            time.sleep(0.5) # 给免费 API 留点喘息空间
            
    except Exception as e:
        print(f"🔥 全局执行出错: {e}")
    finally:
        loader.close()
