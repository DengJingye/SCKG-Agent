"""Deterministic identity bridge from discovery subjects to Scientific KG operators.

This module resolves identity only. It does not select claims, assess scope,
map evidence, authorize execution, or promote candidate knowledge.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value).casefold())
        if len(token) >= 2
    }


@dataclass(frozen=True)
class ScientificSubjectResolution:
    status: str
    subject_text: str
    resolved_subject_type: str = ""
    resolved_project: str = ""
    resolved_package: str = ""
    resolved_method: str = ""
    candidate_operator_ids: tuple[str, ...] = ()
    candidate_operator_revision_ids: tuple[str, ...] = ()
    selected_operator_id: str = ""
    selected_operator_revision_id: str = ""
    ambiguity_reason: str = ""
    coverage_status: str = ""
    provenance: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class ScientificSubjectResolver:
    """Resolve governed identities from an existing conformance bundle."""

    def __init__(
        self,
        *,
        entities: Iterable[Any],
        operator_revisions: Iterable[Any],
        evidence_gaps: Iterable[dict[str, Any]] = (),
    ) -> None:
        self.entities = [
            entity.model_dump(mode="json")
            if hasattr(entity, "model_dump")
            else dict(entity)
            for entity in entities
        ]
        self.operator_revisions = list(operator_revisions)
        self.operator_entities = {
            row["entity_id"]: row
            for row in self.entities
            if row.get("record_type") == "Operator"
        }
        self.method_entities = {
            row["entity_id"]: row
            for row in self.entities
            if row.get("record_type") == "Method"
        }
        self.gap_subjects = {
            _key(gap.get("ecosystem", "")): str(gap.get("ecosystem", ""))
            for gap in evidence_gaps
            if _key(gap.get("ecosystem", ""))
        }
        self.direct_subject_keys: set[str] = set()
        for revision in self.operator_revisions:
            operator_id = revision.operator_id
            qualified = operator_id.split("operator:", 1)[-1]
            package = revision.package_release_id.split(":")[1]
            operator = self.operator_entities.get(operator_id, {})
            self.direct_subject_keys.update(
                {
                    _key(package),
                    _key(qualified),
                    _key(qualified.split(".")[-1].split("::")[-1]),
                    _key(operator.get("qualified_name", "")),
                }
            )

    def resolve(
        self,
        subject_text: str,
        *,
        subject_hints: Iterable[str] = (),
        parsed_operator_id: str = "",
        explicit_version: str = "",
        task_family: str = "",
    ) -> ScientificSubjectResolution:
        del task_family  # Reserved for deterministic future narrowing.
        text = str(subject_text)
        folded = text.casefold()
        hint_values = [str(value) for value in subject_hints if str(value).strip()]
        hint_keys = {_key(value) for value in hint_values if _key(value)}
        provenance: list[str] = []
        candidates = list(self.operator_revisions)

        exact_revision = [
            revision
            for revision in candidates
            if revision.entity_id.casefold() in folded
        ]
        if exact_revision:
            candidates = exact_revision
            provenance.append("exact_operator_revision_id")
        else:
            exact_operator_ids = [
                revision
                for revision in candidates
                if revision.operator_id.casefold() in folded
            ]
            if exact_operator_ids:
                candidates = exact_operator_ids
                provenance.append("exact_canonical_operator_id")
            else:
                api_matches = []
                for revision in candidates:
                    operator = self.operator_entities.get(revision.operator_id, {})
                    qualified = str(
                        operator.get("qualified_name")
                        or revision.operator_id.split("operator:", 1)[-1]
                    )
                    if re.search(
                        rf"(?<![a-z0-9_]){re.escape(qualified.casefold())}(?![a-z0-9_])",
                        folded,
                    ):
                        api_matches.append(revision)
                if api_matches:
                    candidates = api_matches
                    provenance.append("registered_api_path")
                elif parsed_operator_id:
                    candidates = [
                        revision
                        for revision in candidates
                        if revision.operator_id == parsed_operator_id
                    ]
                    if candidates:
                        provenance.append("governed_existing_alias")
                else:
                    package_matches = [
                        revision
                        for revision in candidates
                        if _key(revision.package_release_id.split(":")[1]) in hint_keys
                        or _key(revision.package_release_id.split(":")[1]) in _tokens(text)
                    ]
                    method_matches = []
                    text_key = _key(text)
                    for revision in candidates:
                        for method_id in revision.implements_method_ids:
                            method = self.method_entities.get(method_id, {})
                            method_terms = {
                                _key(method_id.split("method:", 1)[-1]),
                                _key(method.get("label", "")),
                            }
                            if any(term and term in text_key for term in method_terms):
                                method_matches.append(revision)
                                break
                    operator_name_matches = [
                        revision
                        for revision in candidates
                        if _key(
                            revision.operator_id.split("operator:", 1)[-1]
                            .split(".")[-1]
                            .split("::")[-1]
                        )
                        in _tokens(text)
                    ]
                    common_name_matches = [
                        revision
                        for revision in candidates
                        if _key(
                            revision.operator_id.split("operator:", 1)[-1]
                            .split(".")[-1]
                            .split("::")[-1]
                        )
                        in hint_keys
                    ]
                    if package_matches:
                        narrowed = [
                            revision
                            for revision in package_matches
                            if revision in method_matches
                            or revision in operator_name_matches
                        ]
                        candidates = narrowed or package_matches
                        provenance.append("legacy_registry_package_identity_bridge")
                    elif common_name_matches:
                        candidates = common_name_matches
                        provenance.append("legacy_registry_operator_name_bridge")
                    elif method_matches:
                        candidates = method_matches
                        provenance.append("method_to_implementing_operator_revision")
                    else:
                        candidates = []

        if candidates and explicit_version:
            version_matches = [
                revision
                for revision in candidates
                if revision.package_release_id.endswith(f":{explicit_version}")
                or f":{explicit_version}:" in revision.entity_id
            ]
            if not version_matches:
                return self._result(
                    "UNRESOLVED",
                    text,
                    candidates,
                    provenance,
                    ambiguity_reason="explicit_version_not_addressable",
                    coverage_status="VERSION_NOT_ADDRESSABLE",
                )
            candidates = version_matches
            provenance.append("explicit_version")

        if not candidates:
            outside = next(
                (
                    self.gap_subjects[key]
                    for key in hint_keys
                    if key in self.gap_subjects and key not in self.direct_subject_keys
                ),
                "",
            )
            if outside:
                return ScientificSubjectResolution(
                    status="OUTSIDE_SCOPE",
                    subject_text=text,
                    resolved_subject_type="legacy_catalog_subject",
                    resolved_project=f"software-project:{outside.casefold()}",
                    resolved_package=f"package:{outside.casefold()}",
                    ambiguity_reason="no_operator_revision_in_current_direct_evidence_slice",
                    coverage_status="OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE",
                    provenance=("legacy_registry_exact_name", "scientific_kg_gap_inventory"),
                )
            return ScientificSubjectResolution(
                status="UNRESOLVED",
                subject_text=text,
                ambiguity_reason="subject_not_resolved",
                coverage_status="UNKNOWN_SUBJECT",
                provenance=tuple(provenance),
            )

        operator_ids = sorted({revision.operator_id for revision in candidates})
        revision_ids = sorted({revision.entity_id for revision in candidates})
        if len(operator_ids) > 1:
            return self._result(
                "AMBIGUOUS",
                text,
                candidates,
                provenance,
                ambiguity_reason="multiple_operator_candidates",
                coverage_status="AMBIGUOUS_SUBJECT",
            )
        if len(revision_ids) > 1:
            return self._result(
                "AMBIGUOUS",
                text,
                candidates,
                provenance,
                ambiguity_reason="multiple_operator_revisions_require_version",
                coverage_status="VERSION_CLARIFICATION_REQUIRED",
            )
        return self._result(
            "RESOLVED",
            text,
            candidates,
            provenance,
            coverage_status="CURRENT_DIRECT_EVIDENCE_SCOPE",
        )

    def _result(
        self,
        status: str,
        text: str,
        candidates: list[Any],
        provenance: list[str],
        *,
        ambiguity_reason: str = "",
        coverage_status: str,
    ) -> ScientificSubjectResolution:
        operator_ids = tuple(sorted({item.operator_id for item in candidates}))
        revision_ids = tuple(sorted({item.entity_id for item in candidates}))
        method_ids = sorted(
            {
                method_id
                for item in candidates
                for method_id in item.implements_method_ids
            }
        )
        package_ids = sorted(
            {
                "package:" + item.package_release_id.split(":")[1]
                for item in candidates
            }
        )
        projects = sorted(
            {
                "software-project:" + item.package_release_id.split(":")[1]
                for item in candidates
            }
        )
        return ScientificSubjectResolution(
            status=status,
            subject_text=text,
            resolved_subject_type="operator_revision" if status == "RESOLVED" else "operator_candidates",
            resolved_project=projects[0] if len(projects) == 1 else "",
            resolved_package=package_ids[0] if len(package_ids) == 1 else "",
            resolved_method=method_ids[0] if len(method_ids) == 1 else "",
            candidate_operator_ids=operator_ids,
            candidate_operator_revision_ids=revision_ids,
            selected_operator_id=operator_ids[0] if status == "RESOLVED" else "",
            selected_operator_revision_id=revision_ids[0] if status == "RESOLVED" else "",
            ambiguity_reason=ambiguity_reason,
            coverage_status=coverage_status,
            provenance=tuple(provenance),
        )
