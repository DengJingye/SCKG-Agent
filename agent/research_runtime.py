"""Research Chat runtime construction; credentials are never serialized here."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil

from core.settings import PROJECT_ROOT, get_settings
from engine.hybrid_retrieval import HybridRetrievalService


def runtime_configuration_status(unlocked: dict | None = None) -> dict:
    settings = get_settings()
    config = unlocked or {}
    base = config.get("api_base") or settings.openai_api_base or settings.chat_api_base
    from urllib.parse import urlsplit
    present = bool(config.get("api_key") or settings.deepseek_api_key or settings.openai_api_key)
    return {"provider": urlsplit(base).hostname or "openai_compatible",
            "model": config.get("model_name") or settings.model_name or settings.extract_model,
            "configuration_source": "unlocked_session" if config else "SCKG_ENV_FILE" if os.getenv("SCKG_ENV_FILE") else "project_environment",
            "credentials_present": present, "network_verified": False,
            "disabled": settings.offline_llm or settings.privacy_mode == "strict_offline"}


def startup_chat_consent() -> bool:
    """An explicit launcher flag, never inferred merely from finding a key."""
    status = runtime_configuration_status()
    return (os.getenv("SCKG_RESEARCH_CHAT_ENABLED", "").lower() in {"1", "true", "yes"}
            and status["credentials_present"] and not status["disabled"])


def build_chat_retrieval(cache_dir: Path | None = None):
    """Approved production lane plus the preserved, explicit Legacy KG baseline."""
    from engine.approved_scientific_kg import GovernedChatRetrieval
    source = PROJECT_ROOT / "data/indexes/retrieval_foundation_v1"
    manifest = source / "evidence_index_manifest.json"
    if not manifest.is_file():
        # Existing deployments without the qualified slice retain local retrieval.
        raise RuntimeError("legacy_baseline_snapshot_missing")
    identity = hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]
    cache = (cache_dir or PROJECT_ROOT / ".sckg_exec/research-chat-cache") / identity
    cache.mkdir(parents=True, exist_ok=True)
    fts = cache / "evidence_fts5.sqlite"
    if not fts.exists():
        try:
            with fts.open("xb") as out, (source / fts.name).open("rb") as original:
                shutil.copyfileobj(original, out)
        except FileExistsError:
            pass
    return GovernedChatRetrieval(HybridRetrievalService(
        evidence_chunks_path=source / "evidence_chunks.jsonl",
        catalog_chunks_path=source / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=fts, index_manifest_path=manifest,
        coverage_path=cache / "coverage.json",
        dense_matrix_path=source / "evidence_vectors.npy",
        dense_metadata_path=source / "evidence_vector_metadata.json"))
