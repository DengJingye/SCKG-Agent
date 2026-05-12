import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseModel):
    """Single configuration entry point for scKG-Atlas."""

    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    logo_path: Path = PROJECT_ROOT / "logo.png"

    neo4j_uri: Optional[str] = Field(default=None)
    neo4j_user: Optional[str] = Field(default=None)
    neo4j_password: Optional[SecretStr] = Field(default=None)

    openai_api_base: Optional[str] = Field(default=None)
    openai_api_key: Optional[SecretStr] = Field(default=None)
    deepseek_api_key: Optional[SecretStr] = Field(default=None)
    model_name: Optional[str] = Field(default=None)

    siliconflow_api_key: Optional[SecretStr] = Field(default=None)
    embedding_api_key: Optional[SecretStr] = Field(default=None)
    extract_model: str = "deepseek-v4-pro"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_base: str = "https://api.siliconflow.cn/v1/embeddings"
    chat_api_base: str = "https://api.deepseek.com"

    log_level: str = "INFO"
    kg_version: str = "v0.1"
    embedding_version: str = "bge-m3-v0.1"
    offline_graph_fallback: bool = True
    offline_llm: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            neo4j_uri=os.getenv("NEO4J_URI"),
            neo4j_user=os.getenv("NEO4J_USER"),
            neo4j_password=_secret_from_env("NEO4J_PASSWORD"),
            openai_api_base=os.getenv("OPENAI_API_BASE"),
            openai_api_key=_secret_from_env("OPENAI_API_KEY")
            or _secret_from_env("DEEPSEEK_API_KEY"),
            deepseek_api_key=_secret_from_env("DEEPSEEK_API_KEY"),
            model_name=os.getenv("MODEL_NAME"),
            siliconflow_api_key=_secret_from_env("SILICONFLOW_API_KEY"),
            embedding_api_key=_secret_from_env("EMBEDDING_API_KEY")
            or _secret_from_env("SILICONFLOW_API_KEY"),
            extract_model=os.getenv("EXTRACT_MODEL", "deepseek-v4-pro"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_api_base=os.getenv(
                "EMBEDDING_API_BASE",
                "https://api.siliconflow.cn/v1/embeddings",
            ),
            chat_api_base=os.getenv("CHAT_API_BASE", "https://api.deepseek.com"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            kg_version=os.getenv("KG_VERSION", "v0.1"),
            embedding_version=os.getenv("EMBEDDING_VERSION", "bge-m3-v0.1"),
            offline_graph_fallback=_bool_from_env("OFFLINE_GRAPH_FALLBACK", True),
            offline_llm=(
                _bool_from_env("SCKG_OFFLINE_LLM", False)
                or _bool_from_env("DISABLE_LLM_CALLS", False)
            ),
        )

    def require_neo4j(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in {
                "NEO4J_URI": self.neo4j_uri,
                "NEO4J_USER": self.neo4j_user,
                "NEO4J_PASSWORD": self.neo4j_password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required Neo4j settings: {', '.join(missing)}")
        return (
            str(self.neo4j_uri),
            str(self.neo4j_user),
            self.neo4j_password.get_secret_value(),
        )

    def require_llm(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in {
                "OPENAI_API_BASE": self.openai_api_base,
                "OPENAI_API_KEY or DEEPSEEK_API_KEY": self.openai_api_key,
                "MODEL_NAME": self.model_name,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required LLM settings: {', '.join(missing)}")
        return (
            str(self.openai_api_base),
            self.openai_api_key.get_secret_value(),
            str(self.model_name),
        )

    def require_siliconflow_api_key(self) -> str:
        if not self.siliconflow_api_key:
            raise RuntimeError("Missing required SILICONFLOW_API_KEY")
        return self.siliconflow_api_key.get_secret_value()

    def require_embedding_api_key(self) -> str:
        if not self.embedding_api_key:
            raise RuntimeError("Missing required EMBEDDING_API_KEY")
        return self.embedding_api_key.get_secret_value()

    def require_chat_api_key(self) -> str:
        api_key = self.deepseek_api_key or self.openai_api_key
        if not api_key:
            raise RuntimeError("Missing required DEEPSEEK_API_KEY or OPENAI_API_KEY")
        return api_key.get_secret_value()


def _secret_from_env(name: str) -> Optional[SecretStr]:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "" or stripped in {"change_me", "your_key", "your_password"}:
        return None
    return SecretStr(stripped)


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
