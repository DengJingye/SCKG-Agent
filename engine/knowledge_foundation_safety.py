from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from core.settings import PROJECT_ROOT


DEFAULT_POLICY_PATH = (
    PROJECT_ROOT / "data" / "governance" / "knowledge_foundation_p0a_policy.json"
)


@lru_cache(maxsize=4)
def load_knowledge_foundation_policy(
    path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != "knowledge-foundation-p0a-policy-v1":
        raise ValueError("unsupported knowledge-foundation safety policy")
    return value


def formal_evidence_is_quarantined(
    chunk: Any,
    *,
    policy: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a formal row lacks a resolvable source-bound object.

    A title or free-text locator is not sufficient to establish source binding.
    The rule is deliberately generic; the known-ID list is an audit assertion,
    not an allow/deny implementation list.
    """

    source_kind = str(_field(chunk, "source_kind") or "").casefold()
    source_type = str(_field(chunk, "source_type") or "").casefold()
    is_formal = source_kind in {"publication", "benchmark"} or source_type in {
        "formal_publication_tsv",
        "formal_benchmark_tsv",
    }
    return bool(is_formal and not _field(chunk, "source_bound"))


def can_feed_is_actionable(
    relation: Any,
    *,
    policy: Mapping[str, Any] | None = None,
) -> bool:
    if str(_field(relation, "relation") or "") != "CAN_FEED":
        return False
    policy = dict(policy or load_knowledge_foundation_policy())
    rule = policy["relation_actionability"]["CAN_FEED"]
    decisions = list(_field(relation, "review_decision_ids") or [])
    return bool(
        _field(relation, "review_status") == rule["required_review_status"]
        and (decisions or not rule["review_decision_required"])
    )


def version_binding_status(
    tool_name: str,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    policy = dict(policy or load_knowledge_foundation_policy())
    key = str(tool_name or "").casefold()
    return next(
        (
            dict(item)
            for item in policy.get("version_bindings", [])
            if str(item.get("tool_name", "")).casefold() == key
        ),
        None,
    )


def dense_runtime_status(
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    policy = dict(policy or load_knowledge_foundation_policy())
    dense = dict(policy["dense_retrieval"])
    relative_artifacts = [str(value) for value in dense["required_runtime_artifacts"]]
    artifacts = [root / value for value in relative_artifacts]
    present = [path.is_file() and path.stat().st_size > 0 for path in artifacts]
    loadable = all(present)
    declared_available = dense["status"] == "available"
    return {
        "declared_status": dense["status"],
        "loadable_dense_index": loadable,
        "availability_consistent": declared_available == loadable,
        "required_runtime_artifacts": relative_artifacts,
        "artifact_present": present,
        "fallback": dense["fallback"],
        "reason": dense["reason"],
    }


def candidate_scope_can_be_trusted(
    *,
    policy: Mapping[str, Any] | None = None,
) -> bool:
    policy = dict(policy or load_knowledge_foundation_policy())
    return bool(policy["candidate_scope"]["trusted_action_space_eligible"])


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
