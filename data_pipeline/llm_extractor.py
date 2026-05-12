# data_pipeline/llm_extractor.py
import sys
import json
from pathlib import Path

# 将项目根目录加入环境变量，方便导入 core 模块
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.llm_client import get_llm

class LLMExtractor:
    """
    基于大语言模型的生物信息学文献抽取器。
    读取工具的摘要或说明文档，自动提取图谱所需的节点和关系信息。
    """
    def __init__(self):
        self.llm = get_llm()
        
        self.system_prompt = """
        你是一个严谨的生物信息学知识图谱构建专家。
        你的任务是深层次阅读给定的单细胞多组学分析工具摘要，提取其算法原理与生态依赖，并输出结构化 JSON。
        
        严格按照以下 JSON 格式输出，不要有任何 Markdown 标记：
        {
            "tool_name": "工具名称",
            "description": "一句话概括功能",
            "supported_tasks": ["如 Batch Correction, Data Integration 等"],
            "supported_modalities": ["如 scRNA-seq, Spatial Transcriptomics 等"],
            "hardware_requirements": ["如 GPU, CPU, High-RAM。若未提及填 Not specified"],
            "biological_resolution": ["工具作用的生物学粒度，如 Gene, Isoform, Cell, Spatial Spot, Peak 等"],
            "data_objects": ["依赖的底层数据结构，如 AnnData, SeuratObject, SingleCellExperiment 等。若未提及填 Not specified"],
            "algorithm_features": "模型假设：xxx；距离度量：xxx；优化目标：xxx；输入特征：xxx"
        }
        """

    def extract_from_text(self, text: str) -> dict:
        """从纯文本中抽取工具信息字典"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"请分析以下文献摘要：\n{text}"}
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content.strip()
            
            # 清洗可能带有的 Markdown 标记
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
                
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败，模型可能未按规定格式输出。原始内容:\n{content}")
            return {}
        except Exception as e:
            print(f"❌ 抽取过程发生异常: {e}")
            return {}

# ==========================================
# 本地测试逻辑
# ==========================================
if __name__ == "__main__":
    extractor = LLMExtractor()
    
    print("📖 启动 LLM 文献抽取引擎...\n")
    
    # 模拟我们用爬虫从 PubMed 或 bioRxiv 抓下来的摘要 (以著名的 Seurat 核心算法为例)
    mock_abstract = """
    We present a computational strategy, implemented in the Seurat software package, for the integration of single-cell transcriptomic data across different conditions, technologies, and species. The approach is based on the identification of 'anchors'—pairs of cells in different datasets that represent similar biological states. We use a mutual nearest neighbors (MNN) approach in a canonical correlation analysis (CCA) reduced dimensional space to identify these anchors, which are then used to harmonize the datasets. We demonstrate the utility of this approach by integrating multiple scRNA-seq datasets.
    """
    
    print("⏳ 正在阅读摘要并提取图谱结构化数据...\n")
    result = extractor.extract_from_text(mock_abstract)
    
    print("✅ 提取完成，即将入库的数据格式如下：")
    print(json.dumps(result, indent=4, ensure_ascii=False))