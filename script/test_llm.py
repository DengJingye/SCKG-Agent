# script/test_llm.py
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.llm_client import get_llm

if __name__ == "__main__":
    print("--- 🧠 开始测试大模型中枢 ---")
    llm = get_llm()
    print(f"👉 正在连接到模型: {llm.model_name}")
    print(f"👉 使用的 API 节点: {llm.openai_api_base}")
    
    try:
        # 发送一个测试 Prompt
        print("\n⏳ 正在思考中...")
        response = llm.invoke("请用一句话专业地解释一下什么是单细胞测序的批次效应 (Batch Effect)。")
        
        print("\n✅ 模型返回结果:")
        print(response.content)
    except Exception as e:
        print(f"\n❌ 模型调用失败，请检查服务是否启动或网络配置。详情: {e}")