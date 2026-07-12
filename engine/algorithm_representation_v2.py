from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from core.settings import get_settings
from engine.evidence_discovery_index import EvidenceChunk, load_chunks, load_vectors


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPRESENTATIONS_PATH = PROJECT_ROOT / "data" / "indexes" / "tool_representations_v2.jsonl"
DEFAULT_AUDIT_TSV = PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_representation_v2_audit.tsv"
DEFAULT_SUMMARY_JSON = PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_representation_v2_summary.json"
DEFAULT_TOOL_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "tool_algorithm_profiles.tsv"
DEFAULT_LEGACY_AUDIT_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_vector_audit.tsv"
REPRESENTATION_VERSION = "tool-representation-v2.0"

TOOLKIT_MODULE_REQUIRED = {"seurat", "scanpy", "scvi-tools"}


@dataclass(frozen=True)
class ToolRepresentationV2:
    representation_id: str
    representation_version: str
    tool_name: str
    identity: Dict[str, Any]
    evidence_text_view: Dict[str, Any]
    structured_profile_view: Dict[str, Any]
    graph_view: Dict[str, Any]
    empirical_view: Dict[str, Any]
    operational_view: Dict[str, Any]
    confidence: Dict[str, Any]
    legacy_embedding: Dict[str, Any]
    migration_policy: Dict[str, Any]
    source_terms: List[str] = field(default_factory=list)
    method_terms: List[str] = field(default_factory=list)


def build_representations(
    *,
    catalog_rows: Sequence[Dict[str, str]],
    chunks: Sequence[EvidenceChunk],
    vector_by_chunk: Dict[str, List[float]] | None = None,
    profile_rows: Sequence[Dict[str, str]] = (),
    legacy_audit_rows: Sequence[Dict[str, str]] = (),
) -> List[ToolRepresentationV2]:
    vector_by_chunk = vector_by_chunk or {}
    chunks_by_tool: Dict[str, List[EvidenceChunk]] = defaultdict(list)
    for chunk in chunks:
        if chunk.tool_name:
            chunks_by_tool[norm_name(chunk.tool_name)].append(chunk)
    profiles = {norm_name(row.get("tool_name")): row for row in profile_rows if row.get("tool_name")}
    legacy = {norm_name(row.get("tool_name")): row for row in legacy_audit_rows if row.get("tool_name")}

    reps: List[ToolRepresentationV2] = []
    seen: set[str] = set()
    for row in catalog_rows:
        tool_name = clean(row.get("Tool"))
        if not tool_name:
            continue
        key = norm_name(tool_name)
        if key in seen:
            continue
        seen.add(key)
        reps.append(
            build_single_representation(
                tool_name=tool_name,
                catalog_row=row,
                chunks=chunks_by_tool.get(key, []),
                vector_by_chunk=vector_by_chunk,
                profile=profiles.get(key, {}),
                legacy=legacy.get(key, {}),
            )
        )
    return reps


def build_single_representation(
    *,
    tool_name: str,
    catalog_row: Dict[str, str],
    chunks: Sequence[EvidenceChunk],
    vector_by_chunk: Dict[str, List[float]],
    profile: Dict[str, str],
    legacy: Dict[str, str],
) -> ToolRepresentationV2:
    settings = get_settings()
    source_chunks = [chunk for chunk in chunks if chunk.source_kind.startswith("source_") or chunk.source_kind == "document"]
    source_bound_chunk_count = len(source_chunks)
    dense_vector_chunk_count = sum(1 for chunk in source_chunks if chunk.chunk_id in vector_by_chunk)
    benchmark_chunks = [chunk for chunk in chunks if "benchmark" in chunk.source_kind]
    publication_chunks = [chunk for chunk in chunks if "publication" in chunk.source_kind]
    tasks = uniq(
        split_values(profile.get("supported_task"))
        + split_values(legacy.get("supported_tasks"))
        + [chunk.task for chunk in chunks if chunk.task]
    )
    modalities = uniq(
        split_values(profile.get("supported_modality"))
        + split_values(legacy.get("supported_modalities"))
        + [chunk.modality for chunk in chunks if chunk.modality]
    )
    method_text = " ".join(
        [
            profile.get("algorithm_family", ""),
            profile.get("model_assumption", ""),
            profile.get("distance_metric", ""),
            profile.get("optimization_objective", ""),
            profile.get("transferable_mechanism", ""),
            legacy.get("supported_tasks", ""),
            legacy.get("supported_modalities", ""),
        ]
    )
    source_text = " ".join(chunk.chunk_text for chunk in source_chunks)
    method_terms = top_terms(method_text, limit=80)
    source_terms = top_terms(source_text, limit=160)
    graph_terms = uniq(top_terms(" ".join(tasks + modalities + method_terms), limit=120))
    source_coverage_score = min(1.0, source_bound_chunk_count / 5.0)
    empirical_support_score = min(1.0, len(benchmark_chunks) / 2.0)
    quality_flags = quality_flags_for_representation(
        tool_name=tool_name,
        source_bound_chunk_count=source_bound_chunk_count,
        dense_vector_chunk_count=dense_vector_chunk_count,
        legacy=legacy,
        profile=profile,
    )
    review_status = "source_bound_profile" if source_bound_chunk_count else "low_source_coverage"
    return ToolRepresentationV2(
        representation_id=f"toolrepv2:{safe_id(tool_name)}",
        representation_version=REPRESENTATION_VERSION,
        tool_name=tool_name,
        identity={
            "tool_name": tool_name,
            "aliases": [],
            "repository": clean(catalog_row.get("Code")),
            "license": clean(catalog_row.get("License")),
            "catalog_added": clean(catalog_row.get("Added")),
            "catalog_updated": clean(catalog_row.get("Updated")),
        },
        evidence_text_view={
            "chunk_ids": [chunk.chunk_id for chunk in source_chunks[:100]],
            "chunk_id_count": source_bound_chunk_count,
            "source_span_ids": [chunk.source_span or chunk.source_record_id for chunk in source_chunks[:100]],
            "source_ids": uniq([chunk.source_id for chunk in source_chunks if chunk.source_id]),
            "source_types": uniq([chunk.source_type or chunk.source_kind for chunk in source_chunks]),
            "embedding_model": settings.embedding_model,
            "embedding_version": settings.embedding_version,
            "dense_vector_chunk_count": dense_vector_chunk_count,
            "claim_boundary": "Source chunks are evidence discovery only and cannot promote formal evidence.",
        },
        structured_profile_view={
            "tasks": tasks,
            "modalities": modalities,
            "inputs": split_values(profile.get("input_object")),
            "outputs": split_values(profile.get("output_object")),
            "algorithm_family": clean(profile.get("algorithm_family")),
            "model_class": clean(profile.get("model_assumption")),
            "learning_paradigm": infer_learning_paradigm(method_text),
            "toolkit_module_required": norm_name(tool_name) in TOOLKIT_MODULE_REQUIRED,
        },
        graph_view={
            "typed_neighborhood_terms": graph_terms,
            "metapath_policy": "typed KG neighborhood recall; not recommendation evidence",
            "graph_embedding_policy": "future recall signal only",
        },
        empirical_view={
            "benchmark_chunk_count": len(benchmark_chunks),
            "publication_chunk_count": len(publication_chunks),
            "empirical_support_score": round(empirical_support_score, 4),
            "rank_scope_status": "source_bound_or_formal_only" if benchmark_chunks else "missing_benchmark_scope",
        },
        operational_view={
            "platform": clean(catalog_row.get("Platform")),
            "language_or_platform": clean(catalog_row.get("Platform")),
            "license": clean(catalog_row.get("License")),
            "installability_source": "scrna_tools_catalog",
            "maintenance_updated": clean(catalog_row.get("Updated")),
        },
        confidence={
            "source_coverage_score": round(source_coverage_score, 4),
            "review_status": review_status,
            "quality_flags": quality_flags,
            "can_support_recommendation": False,
            "can_promote_formal_evidence": False,
        },
        legacy_embedding={
            "status": "legacy_algorithm_embedding",
            "has_embedding": clean(legacy.get("has_embedding")) == "true",
            "embedding_dim": to_int(legacy.get("embedding_dim")),
            "quality_flag": clean(legacy.get("vector_quality_flag")),
            "allowed_use": ["candidate_recall", "visualization", "clustering_exploration"],
            "forbidden_use": ["recommendation", "formal_evidence_promotion", "migration_validity_claim"],
        },
        migration_policy={
            "output_context": "migration_context",
            "recommendation_grade": False,
            "can_rank_mcdm": False,
            "required_label": "exploratory",
            "claim_boundary": "Algorithm representation similarity is an exploratory migration signal only.",
        },
        source_terms=source_terms,
        method_terms=method_terms,
    )


def score_representation_for_migration(
    representation: ToolRepresentationV2 | Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    rep = representation_to_dict(representation)
    query_terms = set(top_terms(query_text(constraints), limit=120))
    task_terms = set(top_terms(str(constraints.get("task", "")), limit=40))
    modality_terms = set(top_terms(str(constraints.get("modality", "")), limit=40))
    profile = rep.get("structured_profile_view") or {}
    graph = rep.get("graph_view") or {}
    empirical = rep.get("empirical_view") or {}
    confidence = rep.get("confidence") or {}
    method_terms = set(rep.get("method_terms") or [])
    source_terms = set(rep.get("source_terms") or [])
    graph_terms = set(graph.get("typed_neighborhood_terms") or [])
    task_overlap = jaccard(task_terms, set(top_terms(" ".join(profile.get("tasks") or []), limit=80)))
    modality_compatibility = jaccard(
        modality_terms,
        set(top_terms(" ".join(profile.get("modalities") or []), limit=80)),
    )
    algorithm_mechanism_similarity = jaccard(query_terms, method_terms)
    input_output_compatibility = jaccard(
        query_terms,
        set(top_terms(" ".join((profile.get("inputs") or []) + (profile.get("outputs") or [])), limit=80)),
    )
    graph_neighborhood_overlap = jaccard(query_terms, graph_terms)
    evidence_text_similarity = jaccard(query_terms, source_terms)
    empirical_support = float(empirical.get("empirical_support_score") or 0.0)
    source_coverage_score = float(confidence.get("source_coverage_score") or 0.0)
    blocker_penalty = known_blocker_penalty(confidence.get("quality_flags") or [])
    score = (
        0.18 * task_overlap
        + 0.14 * modality_compatibility
        + 0.20 * algorithm_mechanism_similarity
        + 0.12 * input_output_compatibility
        + 0.14 * graph_neighborhood_overlap
        + 0.14 * evidence_text_similarity
        + 0.08 * empirical_support
        + 0.08 * source_coverage_score
        - blocker_penalty
    )
    return {
        "tool_name": rep.get("tool_name", ""),
        "migration_similarity": round(clamp(score), 6),
        "task_overlap": round(task_overlap, 6),
        "modality_compatibility": round(modality_compatibility, 6),
        "algorithm_mechanism_similarity": round(algorithm_mechanism_similarity, 6),
        "input_output_compatibility": round(input_output_compatibility, 6),
        "graph_neighborhood_overlap": round(graph_neighborhood_overlap, 6),
        "evidence_text_similarity": round(evidence_text_similarity, 6),
        "empirical_support": round(empirical_support, 6),
        "source_coverage_score": round(source_coverage_score, 6),
        "known_blocker_penalty": round(blocker_penalty, 6),
        "quality_flags": list(confidence.get("quality_flags") or []),
        "claim_boundary": "Exploratory migration signal only; cannot support recommendation or formal evidence.",
    }


def load_tool_representations(path: Path = DEFAULT_REPRESENTATIONS_PATH) -> Dict[str, ToolRepresentationV2]:
    if not path.exists():
        return {}
    reps: Dict[str, ToolRepresentationV2] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            rep = ToolRepresentationV2(**data)
            reps[norm_name(rep.tool_name)] = rep
    return reps


def write_representations(representations: Sequence[ToolRepresentationV2], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for rep in representations:
            handle.write(json.dumps(asdict(rep), ensure_ascii=False, sort_keys=True) + "\n")


def write_representation_audit(representations: Sequence[ToolRepresentationV2], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "tool_name",
        "source_chunk_count",
        "dense_vector_chunk_count",
        "source_coverage_score",
        "review_status",
        "has_legacy_embedding",
        "legacy_quality_flag",
        "benchmark_chunk_count",
        "publication_chunk_count",
        "toolkit_module_required",
        "quality_flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        for rep in representations:
            writer.writerow(audit_row(rep))


def build_summary(
    representations: Sequence[ToolRepresentationV2],
    *,
    output_path: Path,
    audit_path: Path,
    chunks_path: Path,
    vectors_path: Path,
) -> Dict[str, Any]:
    quality = Counter(flag for rep in representations for flag in rep.confidence.get("quality_flags", []))
    with_source = [rep for rep in representations if rep.evidence_text_view["chunk_id_count"] > 0]
    with_vectors = [rep for rep in representations if rep.evidence_text_view["dense_vector_chunk_count"] > 0]
    toolkit_module_required = [
        rep.tool_name for rep in representations
        if rep.structured_profile_view.get("toolkit_module_required")
    ]
    return {
        "representation_version": REPRESENTATION_VERSION,
        "representation_count": len(representations),
        "tools_with_source_chunks": len(with_source),
        "tools_without_source_chunks": len(representations) - len(with_source),
        "tools_with_dense_vectors": len(with_vectors),
        "source_chunk_count": sum(rep.evidence_text_view["chunk_id_count"] for rep in representations),
        "dense_vector_chunk_count": sum(rep.evidence_text_view["dense_vector_chunk_count"] for rep in representations),
        "legacy_embedding_count": sum(1 for rep in representations if rep.legacy_embedding.get("has_embedding")),
        "toolkit_module_required": toolkit_module_required,
        "quality_flag_counts": dict(quality),
        "output_path": rel(output_path),
        "audit_path": rel(audit_path),
        "chunks_path": rel(chunks_path),
        "vectors_path": rel(vectors_path),
        "policy": [
            "ToolRepresentationV2 is for migration_context and retrieval only.",
            "Source chunks cannot promote formal TSV evidence automatically.",
            "Legacy embeddings are candidate recall signals only.",
        ],
    }


def audit_row(rep: ToolRepresentationV2) -> Dict[str, Any]:
    return {
        "tool_name": rep.tool_name,
        "source_chunk_count": rep.evidence_text_view["chunk_id_count"],
        "dense_vector_chunk_count": rep.evidence_text_view["dense_vector_chunk_count"],
        "source_coverage_score": rep.confidence["source_coverage_score"],
        "review_status": rep.confidence["review_status"],
        "has_legacy_embedding": str(bool(rep.legacy_embedding.get("has_embedding"))).lower(),
        "legacy_quality_flag": rep.legacy_embedding.get("quality_flag", ""),
        "benchmark_chunk_count": rep.empirical_view["benchmark_chunk_count"],
        "publication_chunk_count": rep.empirical_view["publication_chunk_count"],
        "toolkit_module_required": str(bool(rep.structured_profile_view.get("toolkit_module_required"))).lower(),
        "quality_flags": ",".join(rep.confidence.get("quality_flags") or []),
    }


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_chunks_if_exists(path: Path) -> List[EvidenceChunk]:
    return load_chunks(path) if path.exists() else []


def load_vectors_if_exists(path: Path) -> Dict[str, List[float]]:
    return load_vectors(path) if path.exists() else {}


def representation_to_dict(representation: ToolRepresentationV2 | Dict[str, Any]) -> Dict[str, Any]:
    return asdict(representation) if isinstance(representation, ToolRepresentationV2) else representation


def quality_flags_for_representation(
    *,
    tool_name: str,
    source_bound_chunk_count: int,
    dense_vector_chunk_count: int,
    legacy: Dict[str, str],
    profile: Dict[str, str],
) -> List[str]:
    flags: List[str] = []
    if source_bound_chunk_count == 0:
        flags.append("low_source_coverage")
    if dense_vector_chunk_count == 0:
        flags.append("dense_embedding_missing")
    if clean(legacy.get("has_embedding")) == "true":
        flags.append("legacy_embedding_present_recall_only")
    else:
        flags.append("legacy_embedding_missing")
    if not profile:
        flags.append("structured_profile_missing")
    if norm_name(tool_name) in TOOLKIT_MODULE_REQUIRED:
        flags.append("toolkit_requires_module_split")
    return flags


def known_blocker_penalty(flags: Sequence[str]) -> float:
    penalty = 0.0
    if "low_source_coverage" in flags:
        penalty += 0.18
    if "dense_embedding_missing" in flags:
        penalty += 0.05
    if "structured_profile_missing" in flags:
        penalty += 0.12
    if "toolkit_requires_module_split" in flags:
        penalty += 0.04
    return min(0.35, penalty)


def query_text(constraints: Dict[str, Any]) -> str:
    values: List[str] = []
    for key in (
        "migration_query_text",
        "task",
        "task_family",
        "modality",
        "data_object",
        "output_goal",
        "platform",
    ):
        value = constraints.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    values.extend(str(item) for item in constraints.get("migration_intent_reasons", []) or [])
    return " ".join(values)


def infer_learning_paradigm(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("supervised", "classifier", "classification")):
        return "supervised"
    if any(term in lowered for term in ("vae", "autoencoder", "latent", "neural")):
        return "deep_latent_model"
    if any(term in lowered for term in ("graph", "network", "neighbor")):
        return "graph_based"
    if any(term in lowered for term in ("regression", "gam", "spline")):
        return "statistical_regression"
    if any(term in lowered for term in ("optimal transport", "wasserstein", "transport")):
        return "optimal_transport"
    return "unknown"


def split_values(value: Any) -> List[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[;|,]+", text) if part.strip()]


def top_terms(text: str, limit: int) -> List[str]:
    counts = Counter(term for term in terms(text) if len(term) >= 3)
    return [term for term, _ in counts.most_common(limit)]


def terms(text: str) -> List[str]:
    lowered = (text or "").lower()
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}", lowered)
        if token not in {"unknown", "none", "null", "nan", "with", "using", "from", "this", "that"}
    ]


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        value = clean(value)
        key = norm_name(value)
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def to_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return 0


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value or "").strip("_") or "unknown"


def norm_name(value: Any) -> str:
    return clean(value).casefold()


def clean(value: Any) -> str:
    return str(value or "").strip()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
