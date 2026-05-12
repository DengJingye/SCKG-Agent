# main.py
from agent.workflow import build_sckg_graph

def run_mvp_test():
    print("🚀 === scKG-Atlas Agent MVP 本地测试启动 === 🚀\n")
    
    # 1. 构建图引擎
    app = build_sckg_graph()
    
    # 2. 模拟用户的初始输入状态
    # initial_state = {
    #     "user_query": "我有一批极度稀缺的单细胞空间代谢组数据，想做一下细胞差异分析，目前根本找不到现成的处理软件，我该怎么办？",
    #     "extracted_constraints": {},
    #     "candidate_tools": [], # ⚠️ 关键点：这里为空，工作流应该会自动路由到“迁移推理”分支
    #     "scored_tools": [],
    #     "migration_paths": [],
    #     "final_report": "",
    #     "current_step": "init",
    #     "error_message": None
    # }

    # 模拟用户的初始输入状态
    # initial_state = {
    #     "user_query": "我的单细胞 RNA-seq 数据来自三个不同医院，批次效应很重，求推荐靠谱的去除工具，最好给出理由。",
    #     "extracted_constraints": {},
    #     "candidate_tools": [], 
    #     "scored_tools": [],
    #     "migration_paths": [],
    #     "final_report": "",
    #     "current_step": "init",
    #     "error_message": None
    # }

    # 模拟用户的初始输入状态 (提问一个竞争极其激烈的任务)
    initial_state = {
        "user_query": "我正在做单细胞数据整合（Data Integration），但我不知道该选 Seurat, Harmony 还是 scVI。你能根据它们的算法原理和工程可靠性给我个建议吗？",
        "extracted_constraints": {},
        "candidate_tools": [], 
        "scored_tools": [],
        "migration_paths": [],
        "final_report": "",
        "current_step": "init",
        "error_message": None
    }

    print("=== 开始执行工作流 ===")
    
    # 3. 触发工作流执行
    # app.invoke 会按照 workflow.py 里定义的节点和边，一步步处理 state
    final_state = app.invoke(initial_state)
    
    print("\n=== 工作流执行结束 ===")
    print("\n📊 最终状态 (State) 追踪:")
    print(f"原始问题: {final_state.get('user_query')}")
    print(f"最终停留在哪个节点: {final_state.get('current_step')}")

    print("\n" + "="*50)
    print("✨ scKG-Atlas Agent 最终决策报告 ✨")
    print("="*50)
    print(final_state.get('final_report'))
    print("="*50)

if __name__ == "__main__":
    run_mvp_test()