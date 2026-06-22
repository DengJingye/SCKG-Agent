# agent/states.py
from typing import TypedDict, List, Dict, Any, Optional

from pydantic import BaseModel, Field

from core.constraints import ResearchConstraints
from core.models import (
    DecisionReport,
    MigrationPath,
    RetrievalResult,
    ScoredTool,
    ToolCandidate,
    WorkflowRecommendation,
)


class ScKGAgentStateModel(BaseModel):
    user_query: str
    extracted_constraints: ResearchConstraints = Field(default_factory=ResearchConstraints)
    candidate_tools: List[str] = Field(default_factory=list)
    tool_candidates: List[ToolCandidate] = Field(default_factory=list)
    retrieval_results: List[RetrievalResult] = Field(default_factory=list)
    scored_tools: List[ScoredTool] = Field(default_factory=list)
    migration_paths: List[MigrationPath] = Field(default_factory=list)
    workflow_recommendations: List[WorkflowRecommendation] = Field(default_factory=list)
    decision_report: Optional[DecisionReport] = None
    context_pack: Dict[str, Any] = Field(default_factory=dict)
    conversation_context: List[Dict[str, Any]] = Field(default_factory=list)
    project_memory: Dict[str, Any] = Field(default_factory=dict)
    uploaded_context: Dict[str, Any] = Field(default_factory=dict)
    user_runtime_config: Dict[str, Any] = Field(default_factory=dict)
    final_report: str = ""
    hallucination_audit: Dict[str, Any] = Field(default_factory=dict)
    current_step: str = "init"
    error_message: Optional[str] = None


class ScKGAgentState(TypedDict):
    """
    scKG-Atlas Agent 的全局状态字典。
    这里存放了贯穿整个单细胞多组学分析决策流程的所有关键数据。
    """
    
    # 1. 原始输入层
    user_query: str                  # 用户的原始提问（例如："我有一批长读长的Nanopore单细胞数据，噪声比较大，该用什么聚类工具？"）
    
    # 2. 意图解析与约束层
    # 标准字段：task, modality, platform, data_object, scale, noise,
    # hardware, species, output_goal, strictness。
    extracted_constraints: Dict[str, Any]
    
    # 3. 候选集 (对应论文中的 I_cand)
    candidate_tools: List[str]       # 经过硬约束（模态、I/O等）筛选后，符合条件的候选工具列表
    tool_candidates: List[Dict[str, Any]]
    retrieval_results: List[Dict[str, Any]]
    
    # 4. 软约束打分结果
    scored_tools: List[Dict[str, Any]] # MCDM 打分后的工具列表，包含相对排名、分数及证据链
    
    # 5. 迁移推理结果（当 candidate_tools 为空时触发）
    migration_paths: List[Dict[str, Any]]  # 存放算法同构性推理出的替代路径和 Jaccard 验证系数
    context_pack: Dict[str, Any]
    conversation_context: List[Dict[str, Any]]
    project_memory: Dict[str, Any]
    uploaded_context: Dict[str, Any]
    user_runtime_config: Dict[str, Any]
    
    # 6. 最终输出层
    workflow_recommendations: List[Dict[str, Any]]
    decision_report: Dict[str, Any]
    final_report: str                # Qwen2.5 最终生成的解释性分析报告
    hallucination_audit: Dict[str, Any]
    
    # 7. 调试与路由控制
    current_step: str                # 记录当前执行到了哪个节点，方便日志调试
    error_message: Optional[str]     # 记录流程中可能出现的报错信息
