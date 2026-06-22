from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI

from core.settings import get_settings


def get_llm(runtime_config: Optional[Dict[str, Any]] = None):
    """
    获取大语言模型实例。
    所有配置从 core.settings 读取，避免环境变量散落在各模块。
    runtime_config 可由前端传入用户解锁后的 OpenAI-compatible key。
    """
    settings = get_settings()
    if settings.offline_llm:
        raise RuntimeError(
            "LLM calls are disabled by SCKG_OFFLINE_LLM=true or DISABLE_LLM_CALLS=true."
        )
    runtime_config = runtime_config or {}
    if runtime_config.get("api_key"):
        base_url = str(runtime_config.get("api_base") or settings.chat_api_base)
        api_key = str(runtime_config["api_key"])
        model_name = str(runtime_config.get("model_name") or settings.model_name or "deepseek-chat")
    else:
        base_url, api_key, model_name = settings.require_llm()
    
    # 初始化 LangChain 的 ChatOpenAI 客户端
    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0.1,  # 温度设低一点(0.1)，保证 Agent 输出的逻辑性和科学严谨性
        max_retries=2
    )
    
    return llm
