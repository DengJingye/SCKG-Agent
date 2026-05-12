from neo4j import GraphDatabase

from core.logging_config import get_logger
from core.models import Evidence
from core.settings import get_settings
from connectors.offline_graph import OfflineGraphStore


logger = get_logger(__name__)

class Neo4jClient:
    """
    scKG-Atlas 图数据库交互客户端。
    负责执行硬约束查询、特征检索以及路径验证。
    """
    def __init__(self):
        self.uri, self.user, self.password = get_settings().require_neo4j()
        self.driver = None
        self.offline_store = None
        self.connect()

    def connect(self):
        """建立数据库连接"""
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # 测试连接
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j graph database at %s", self.uri)
        except Exception as e:
            if get_settings().offline_graph_fallback:
                logger.warning("Neo4j connection failed, falling back to offline graph store: %s", e)
                self.offline_store = OfflineGraphStore()
                self.driver = None
            else:
                logger.exception("Neo4j connection failed")
                raise RuntimeError(f"Neo4j connection failed: {e}") from e

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def execute_query(self, query: str, parameters: dict = None) -> list:
        """
        通用的 Cypher 查询执行接口
        :param query: Cypher 语句
        :param parameters: 查询参数字典
        :return: 包含查询结果的列表字典
        """
        if parameters is None:
            parameters = {}
        if self.driver is None and self.offline_store is None:
            raise RuntimeError("Neo4j driver is not initialized")

        if self.offline_store is not None:
            return self._execute_offline_query(query, parameters)
            
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record.data() for record in result]

    # ==========================================
    # 以下为 LangGraph 节点准备的具体业务查询接口
    # ==========================================

    def find_candidates_by_hard_constraints(self, task: str, modality: str) -> list:
        """
        对应开题报告 4.2.2：基于集合论的硬约束筛选 (Feasibility Reasoning)
        这里暂时写一个简单的模板查询，后续我们有了真实节点再丰富它。
        """
        # 假设图谱里的逻辑是：(t:Tool)-[:IMPLEMENTS]->(Task) AND (t:Tool)-[:SUPPORTS]->(Modality)
        query = """
        MATCH (tool:Tool)-[:PERFORMS_TASK]->(task:Task {name: $task})
        MATCH (tool)-[:SUPPORTS_MODALITY]->(mod:Modality {name: $modality})
        RETURN tool.name AS tool_name, tool.description AS desc
        """
        return self.execute_query(query, {"task": task, "modality": modality})

    def _execute_offline_query(self, query: str, parameters: dict) -> list:
        if "RETURN 'Hello scKG-Atlas!' AS message" in query:
            return [{"message": "Hello scKG-Atlas!"}]

        if "MATCH (tool:Tool)-[:PERFORMS_TASK]->(task:Task {name: $task})" in query:
            return self.offline_store.find_candidates(
                task=parameters.get("task", "Unknown"),
                modality=parameters.get("modality", "Unknown"),
            )

        if "MATCH (t:Tool)" in query and "github_stars" in query and "WHERE t.name IN $candidates" in query:
            return self.offline_store.get_tool_rows(parameters.get("candidates", []))

        if "MATCH (t:Tool)-[:IMPLEMENTS_ALGORITHM]->(a:Algorithm)" in query:
            return self.offline_store.get_algorithm_rows()

        if "MATCH (tool:Tool)-[:SUPPORTED_BY]->(e:Evidence)" in query:
            return [
                {
                    "tool_name": tool_name,
                    "evidence": evidence.model_dump(mode="json"),
                }
                for tool_name, evidences in self.offline_store.get_tool_evidence(parameters.get("tool_names", [])).items()
                for evidence in evidences
            ]

        if "MERGE (e:Evidence" in query:
            tool_name = parameters.get("tool_name")
            evidence_data = parameters.get("props", {})
            if tool_name and evidence_data:
                self.offline_store.upsert_evidence(tool_name, Evidence.model_validate(evidence_data))
            return []

        if "MERGE (tool:Tool" in query:
            # Offline ingest/update is best-effort; no-op if not a query we explicitly model.
            return []

        return []

    def fetch_tool_evidence(self, tool_names: list[str]) -> dict[str, list[Evidence]]:
        """Fetch Evidence nodes connected to tools."""
        if not tool_names:
            return {}
        query = """
        MATCH (tool:Tool)-[:SUPPORTED_BY]->(e:Evidence)
        WHERE tool.name IN $tool_names
        RETURN tool.name AS tool_name, properties(e) AS evidence
        """
        rows = self.execute_query(query, {"tool_names": tool_names})
        grouped: dict[str, list[Evidence]] = {}
        for row in rows:
            try:
                evidence = Evidence.model_validate(row["evidence"])
            except Exception as exc:
                logger.warning("Skipping invalid evidence for %s: %s", row["tool_name"], exc)
                continue
            grouped.setdefault(row["tool_name"], []).append(evidence)
        return grouped

    def upsert_evidence(self, tool_name: str, evidence: Evidence) -> None:
        """Create or update an Evidence node and bind it to a Tool."""
        query = """
        MATCH (tool:Tool {name: $tool_name})
        MERGE (e:Evidence {evidence_id: $evidence_id})
        SET e += $props
        MERGE (tool)-[:SUPPORTED_BY]->(e)
        """
        props = evidence.model_dump(mode="json")
        self.execute_query(
            query,
            {
                "tool_name": tool_name,
                "evidence_id": evidence.evidence_id,
                "props": props,
            },
        )
