import time
from urllib.parse import urlparse, urlunparse

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
        self.active_uri = None
        self.driver = None
        self.offline_store = None
        self.connect()

    def connect(self):
        """建立数据库连接"""
        attempts = 3
        last_error = None
        total_attempts = 0
        uri_candidates = _connection_uri_candidates(self.uri)
        try:
            for uri_index, candidate_uri in enumerate(uri_candidates):
                for attempt in range(1, attempts + 1):
                    total_attempts += 1
                    try:
                        self.driver = GraphDatabase.driver(candidate_uri, auth=(self.user, self.password))
                        # 测试连接
                        self.driver.verify_connectivity()
                        self.active_uri = candidate_uri
                        if candidate_uri != self.uri:
                            logger.warning(
                                "Connected to Neo4j through direct Bolt fallback at %s after routing URI failed.",
                                _safe_uri_label(candidate_uri),
                            )
                        else:
                            logger.info(
                                "Connected to Neo4j graph database at %s",
                                _safe_uri_label(candidate_uri),
                            )
                        return
                    except Exception as exc:
                        last_error = exc
                        if self.driver:
                            self.driver.close()
                            self.driver = None
                        if attempt < attempts:
                            logger.warning(
                                "Neo4j connection attempt %s/%s failed for %s; retrying: %s",
                                attempt,
                                attempts,
                                _safe_uri_label(candidate_uri),
                                exc,
                            )
                            time.sleep(1.5 * attempt)
                        elif uri_index + 1 < len(uri_candidates):
                            logger.warning(
                                "Neo4j connection failed for %s; trying %s: %s",
                                _safe_uri_label(candidate_uri),
                                _safe_uri_label(uri_candidates[uri_index + 1]),
                                exc,
                            )
                        else:
                            raise
        except Exception as e:
            if get_settings().offline_graph_fallback:
                logger.warning(
                    "Neo4j connection failed after %s attempt(s), falling back to offline graph store: %s",
                    total_attempts,
                    last_error or e,
                )
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


def _safe_uri_label(uri: str) -> str:
    parsed = urlparse(uri)
    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _connection_uri_candidates(uri: str) -> list[str]:
    parsed = urlparse(uri)
    direct_scheme_by_routing_scheme = {
        "neo4j": "bolt",
        "neo4j+s": "bolt+s",
        "neo4j+ssc": "bolt+ssc",
    }
    direct_scheme = direct_scheme_by_routing_scheme.get(parsed.scheme)
    if not direct_scheme:
        return [uri]
    direct_uri = urlunparse(
        (
            direct_scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    if direct_uri == uri:
        return [uri]
    return [uri, direct_uri]
