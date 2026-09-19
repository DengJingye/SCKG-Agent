"""Read-only, candidate-scoped scientific evidence lookup; never data applicability.

The corrected Scanpy slice is queried, not promoted. Only byte/identity-matched
chunks already eligible in the frozen retrieval snapshot can enter retrieval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from core.scientific_knowledge_conformance_models import ConformanceBundle, OperatorRevision
from engine.scientific_kg_applicability import DEFAULT_CANDIDATE_ROOT, _verify_candidate
from core.settings import PROJECT_ROOT
from engine.scientific_subject_resolution import ScientificSubjectResolver

SNAPSHOT_ID = "retrieval-foundation-v1-ff5b4829bc5943f4"
CORPUS_DIGEST = "8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436"
MAX_GRAPH_CHUNKS = 12
OPERATORS = {
    "pca": "operator:scanpy.pp.pca",
    "neighbors": "operator:scanpy.pp.neighbors",
    "highly_variable_genes": "operator:scanpy.pp.highly_variable_genes",
    "umap": "operator:scanpy.tl.umap",
    "leiden": "operator:scanpy.tl.leiden",
    "harmony": "operator:harmony.RunHarmony",
    "scrublet": "operator:scrublet.Scrublet.scrub_doublets",
    "singler": "operator:SingleR::SingleR",
}
PREDICATES = {
    "input_requirement": {"requires_representation", "accepts_representation", "accepts_optional_representation"},
    "output": {"produces"},
    "parameter": {"key_parameter", "has_key_parameter"},
    "limitation": {"limitation", "has_limitation"},
    "method_type": {"implements_method"},
    "compatibility": {"requires_compatibility"},
    "scope": {"has_limitation", "requires_compatibility", "requires_representation"},
    "reference_artifact": {"requires_representation", "requires_compatibility"},
}
DEFAULT_GAP_PATHS = (
    PROJECT_ROOT / "data/evidence_candidates/scientific_kg_v1_core/evidence_gaps.json",
    PROJECT_ROOT / "data/evidence_candidates/scientific_kg_content_expansion_v1/evidence_gaps.json",
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parse_scientific_query(query: str, claim_types=(), *, extended: bool = False) -> dict[str, Any]:
    """Bounded operator aliases, not benchmark IDs or per-question answer rules."""
    text = query.casefold()
    api_pattern = (
        r"(?:scanpy|sc)\.(?:pp|tl)\.(pca|neighbors|highly_variable_genes|umap|leiden)\b"
        if extended else r"(?:scanpy|sc)\.pp\.(pca|neighbors|highly_variable_genes)\b"
    )
    api = re.findall(api_pattern, text)
    aliases = []
    alias_patterns = {
        "pca": r"\bpca\b|principal component analysis|主成分",
        "neighbors": r"\bneighbors\b|邻居图构建|邻域图构建",
        "highly_variable_genes": r"\bhighly_variable_genes\b|highly variable genes?|\bhvg\b|高变基因",
        "umap": r"\bumap\b",
        "leiden": r"\bleiden\b",
        "harmony": r"\bharmony\b|runharmony",
        "scrublet": r"\bscrublet\b|scrub_doublets",
        "singler": r"\bsingler\b|singler::singler",
    }
    if not extended:
        alias_patterns = {key: alias_patterns[key] for key in ("pca", "neighbors", "highly_variable_genes")}
    for key, pattern in alias_patterns.items():
        if re.search(pattern, text):
            aliases.append(key)
    operators = sorted(set(api or aliases))
    needs = set()
    if re.search(
        r"\b(inputs?|requires?|requirements?|accepts?|consumes?|supplied|provided)\b"
        r"|\bcan\b.*\buse\b|输入|需要|要求|读取|提供",
        text,
    ):
        needs.add("input_requirement")
    if re.search(
        r"\b(outputs?|returns?|produces?|stores?|stored|writes?|records?|where)\b"
        r"|\bdata products?\b|\b(?:quantity|quantities|results?)\b.*\b(?:infer|estimate|expose)\b"
        r"|\b(?:infer|estimate|expose)\b.*\b(?:quantity|quantities|results?)\b"
        r"|输出|返回|存储|保存.*位置|估计.*(?:数量|结果)",
        text,
    ):
        needs.add("output")
    if not needs and re.search(r"\b(matrix|matrices|layers?)\b", text):
        needs.add("input_requirement")
    if re.search(
        r"\bparameters?\b|\bthreshold(?:ing|s)?\b|\bseeds?\b|\badjustments?\b"
        r"|\bversion constraints?\b|\breleases?\b|参数|阈值|版本约束",
        text,
    ):
        needs.add("parameter")
    if re.search(
        r"\b(limitations?|caveats?|sensitivities|reliability|workarounds?|failures?)\b"
        r"|\b(?:must|should) be avoided\b|\bscientifically defensible\b"
        r"|\bunconditional\b|局限|限制|可靠性|规避",
        text,
    ):
        needs.add("limitation")
    if re.search(
        r"what (?:is|method)|\b(?:which|what) (?:evidence-backed )?(?:method|capability) fits\b"
        r"|什么方法|何种方法|哪种能力",
        text,
    ):
        needs.add("method_type")
    if re.search(r"compatib|reference|参考|兼容|物种", text):
        needs.add("compatibility")
    if re.search(r"reference artifact|reference model|参考模型|参考数据", text):
        needs.add("reference_artifact")
    if re.search(
        r"\b(?:benchmark|evidence|frozen) artifact\b|\bexperimentally validated\b"
        r"|\bbenchmarked\b|基准证据|冻结证据",
        text,
    ):
        needs.add("reference_artifact")
    if re.search(r"applicab|scope|scientifically defensible|适用|范围|条件", text):
        needs.add("scope")
    needs = needs or ({"limitation" if x == "failure_mode" else x for x in claim_types} & PREDICATES.keys())
    versions = re.findall(r"(?:scanpy\s+|version\s*[=:]?\s*|版本\s*[=:]?\s*|\bv)(\d+\.\d+(?:\.\d+)?)", text)
    if not versions:
        versions = re.findall(r"\b(\d+\.\d+\.\d+)\b", text)
    flavor_assignment = re.search(r"flavou?r\s*[=:]\s*['\"]?([a-z0-9_]+)", text)
    flavors = [flavor_assignment[1]] if flavor_assignment else re.findall(r"\b(seurat_v3_paper|seurat_v3|cell_ranger|seurat)\b", text)
    reason = ""
    all_apis = re.findall(r"(?:scanpy|sc)\.(?:pp|tl)\.[a-z_]+", text)
    supported_api = (
        r"(?:scanpy|sc)\.(?:pp|tl)\.(?:pca|neighbors|highly_variable_genes|umap|leiden)"
        if extended else r"(?:scanpy|sc)\.pp\.(?:pca|neighbors|highly_variable_genes)"
    )
    if all_apis and any(not re.fullmatch(supported_api, a) for a in all_apis):
        reason = "unsupported_or_historical_operator_api"
    elif not operators:
        reason = "unsupported_operator"
    elif len(operators) != 1:
        reason = "ambiguous_operator"
    elif re.search(r"scanpy\.tl\.pca", text):
        reason = "historical_operator_alias_not_resolved"
    elif not api and re.search(r"\b(seurat|sklearn|scikit-learn)\b", text) and operators != ["highly_variable_genes"]:
        reason = "non_scanpy_package"
    elif not needs:
        reason = "information_need_unknown"
    elif re.search(r"我的数据|当前数据是否|my (?:data|dataset)|does (?:my|this) (?:data|dataset)", text):
        reason = "runtime_applicability_out_of_scope"
    elif len(set(versions)) > 1 or len(set(flavors)) > 1:
        reason = "multiple_conditions_require_clause_resolution"
    elif re.search(r"\b(latest|stable|unknown)\s+version|最新版本|版本未知", text):
        reason = "requested_version_unknown"
    elif re.search(r"which (?:version|flavou?r)|specify (?:the )?(?:version|flavou?r)|哪个版本|哪种flavou?r|请指定版本", text) and not (versions or flavors):
        reason = "required_condition_missing"
    elif re.search(r"which (?:reference|organism|species)|哪(?:个|种)(?:参考|物种)|请指定(?:参考|物种)", text):
        reason = "required_reference_or_biological_scope_missing"
    ecosystems = {
        "scanpy": r"\bscanpy\b|\bsc\.(?:pp|tl)\.", "harmony": r"\bharmony\b",
        "scrublet": r"\bscrublet\b", "singler": r"\bsingler\b",
        "scanorama": r"\bscanorama\b", "scvi-tools": r"\bscvi(?:-tools)?\b|\btotalvi\b|\bmultivi\b",
        "celltypist": r"\bcelltypist\b", "scvelo": r"\bscvelo\b", "cellrank": r"\bcellrank\b",
        "doubletfinder": r"\bdoubletfinder\b", "scdblfinder": r"\bscdblfinder\b",
    }
    ecosystem = next((name for name, pattern in ecosystems.items() if re.search(pattern, text)), "")
    return {"operator": operators[0] if len(operators) == 1 else None,
            "operator_id": OPERATORS.get(operators[0]) if len(operators) == 1 else None,
            "information_needs": sorted(needs), "version": versions[0] if versions else None,
            "flavor": flavors[0] if flavors else None,
            "ecosystem": ecosystem,
            "explicit_species": sorted(set(re.findall(r"\b(?:human|mouse|murine)\b|人类|小鼠", text))),
            "explicit_modality": sorted(set(re.findall(r"\b(?:scrna-seq|snrna-seq|scatac-seq|spatial transcriptomics)\b|单细胞转录组|空间转录组", text))),
            "resolution": "qualified_api" if api else "bounded_scanpy_alias",
            "fallback_reason": reason}


class ScientificKGEvidence:
    def __init__(self, root: Path = DEFAULT_CANDIDATE_ROOT, *, evidence_gaps: list[dict[str, Any]] | None = None):
        self.root = Path(root)
        manifest = json.loads((self.root / "manifest.json").read_text())
        _verify_candidate(manifest, self.root)
        source_path = self.root / "authoritative_source_manifest.json"
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != manifest["artifacts"][source_path.name]:
            raise ValueError("scientific_source_manifest_digest_mismatch")
        self.bundle = ConformanceBundle.model_validate_json((self.root / "conformance_bundle.json").read_text())
        self.operators = [x for x in self.bundle.entities if isinstance(x, OperatorRevision)]
        self.scopes = {x.scope_id: x for x in self.bundle.scopes}
        self.constraints = {x.constraint_id: x for x in self.bundle.representation_constraints}
        self.bindings = {r["claim_revision_id"]: r for r in self._rows("exact_evidence_bindings.jsonl")}
        self.spans = {r["evidence_span_id"]: r for r in self._rows("authoritative_evidence_spans.jsonl")}
        self.sources = {r["source_revision_id"]: r for r in json.loads(source_path.read_text())["sources"]}
        if evidence_gaps is None:
            evidence_gaps = []
            for path in DEFAULT_GAP_PATHS:
                if path.exists():
                    evidence_gaps.extend(json.loads(path.read_text()).get("gaps", []))
        self.evidence_gaps = list(evidence_gaps)
        self.subject_resolver = ScientificSubjectResolver(
            entities=self.bundle.entities,
            operator_revisions=self.operators,
            evidence_gaps=self.evidence_gaps,
        )
        self.identity = {"schema": self.bundle.schema_version,
                         "path": "data/evidence_candidates/" + self.root.name,
                         "snapshot": self.root.name,
                         "manifest_sha256": hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest(),
                         "bundle_sha256": manifest["artifacts"]["conformance_bundle.json"],
                         "source_manifest_sha256": manifest["artifacts"][source_path.name]}

    def _rows(self, name):
        return [json.loads(line) for line in (self.root / name).read_text().splitlines() if line]

    def _matching_gap(self, parsed: dict[str, Any]) -> dict[str, Any] | None:
        ecosystem = parsed.get("ecosystem", "").casefold().replace("-", "_")
        if not ecosystem:
            return None
        relation_by_need = {
            "input_requirement": "requires_representation", "output": "produces",
            "parameter": "key_parameter", "limitation": "has_limitation",
            "compatibility": "requires_compatibility",
            "scope": "has_limitation",
        }
        requested = {relation_by_need[n] for n in parsed.get("information_needs", []) if n in relation_by_need}
        candidates = [g for g in self.evidence_gaps if str(g.get("ecosystem", "")).casefold().replace("-", "_") == ecosystem]
        exact = [g for g in candidates if str(g.get("missing_knowledge", "")) in requested]
        if exact:
            return sorted(exact, key=lambda g: g.get("gap_id", ""))[0]
        if "reference_artifact" in parsed.get("information_needs", []):
            reference = [
                g for g in candidates
                if "referenceartifact" in str(g.get("missing_knowledge", "")).casefold().replace(" ", "")
            ]
            if reference:
                return sorted(reference, key=lambda g: g.get("gap_id", ""))[0]
        if parsed.get("version") or parsed.get("fallback_reason") in {"requested_version_unknown", "required_condition_missing"}:
            pinned = [g for g in candidates if "version" in str(g.get("missing_knowledge", "")).casefold() or "release" in str(g.get("missing_knowledge", "")).casefold()]
            if pinned:
                return sorted(pinned, key=lambda g: g.get("gap_id", ""))[0]
        return None

    def _scope(self, scope, parsed):
        result = {"scope_id": scope.scope_id, "registered_scope": scope.model_dump(mode="json"),
                  "version_status": "unspecified_scoped_evidence_only", "condition_status": "not_required",
                  "scope_status": scope.scope_status, "data_compatibility_assessed": False}
        if scope.scope_status not in {"explicit", "partially_known"}:
            return result, "scope_unknown"
        exact = [v.expression for v in scope.version_constraints if v.status == "exact"]
        if parsed["version"]:
            result["version_status"] = "matched" if exact and parsed["version"] in exact else "unknown_or_mismatch"
            if result["version_status"] != "matched":
                return result, "version_not_supported_by_scope"
        if parsed["explicit_species"]:
            # The frozen Scanpy scopes do not certify biological species suitability.
            result["scope_status"] = "requested_species_unknown"
            return result, "explicit_biological_scope_not_resolved"
        conditions = scope.parameter_conditions
        for condition in conditions:
            if not condition.parameter_id.endswith("hvg_flavor"):
                return result, "unhandled_scope_condition"
            flavor = parsed["flavor"]
            if flavor is None:
                result["condition_status"] = "conditional_flavor_unspecified"
            elif condition.operator in {"in", "equals"} and flavor in condition.values:
                result["condition_status"] = "matched"
            else:
                result["condition_status"] = "mismatch"
                return result, "flavor_condition_mismatch"
        return result, ""

    def _span_binding(self, claim, binding, span_id):
        if not binding or binding.get("claim_content_hash") != claim.content_hash or _hash(claim.claim_text) != claim.content_hash:
            return None, "claim_binding_integrity_failure"
        if binding.get("assessment") != "supports" or not binding.get("candidate_only"):
            return None, "binding_not_supported_candidate"
        assessments = [a for a in self.bundle.evidence_assessments if a.claim_revision_id == claim.claim_revision_id]
        if not any(a.stance == "supports" and a.subject_aligned and a.predicate_aligned and a.object_aligned
                   and a.scope_alignment == "aligned" and span_id in a.evidence_span_ids for a in assessments):
            return None, "assessment_binding_missing"
        span = self.spans.get(span_id)
        if not span or not span.get("source_bound") or _hash(span["source_excerpt"]) != span["content_hash"]:
            return None, "evidence_span_unresolvable"
        i = binding["evidence_span_ids"].index(span_id)
        if any(binding[key][i] != span[value] for key, value in [("evidence_locators", "locator"),
                 ("source_file_sha256", "source_file_sha256"), ("evidence_excerpt_sha256", "content_hash")]):
            return None, "span_binding_integrity_failure"
        source = self.sources.get(span["source_revision_id"])
        if not source or not any(f["path"] == span["source_path"] and f["sha256"] == span["source_file_sha256"] for f in source["source_files"]):
            return None, "source_revision_unresolvable"
        if span.get("version_pin", {}).get("release") != source.get("release"):
            return None, "source_version_mismatch"
        return span, ""

    def query(
        self,
        request,
        chunks: dict,
        *,
        snapshot_id: str,
        corpus_digest: str,
        subject_hints: list[str] | None = None,
    ):
        parsed = parse_scientific_query(
            request.query,
            request.claim_types,
            extended=bool(getattr(request, "use_scientific_evidence", False)),
        )
        identity_wiring_enabled = bool(getattr(request, "use_scientific_evidence", False))
        subject_resolution = self.subject_resolver.resolve(
            request.query if identity_wiring_enabled else "",
            subject_hints=(subject_hints or request.tool_names) if identity_wiring_enabled else [],
            parsed_operator_id=parsed.get("operator_id") or "",
            explicit_version=parsed.get("version") or "",
            task_family=(request.canonical_tasks[0] if request.canonical_tasks else ""),
        )
        if subject_resolution.status == "RESOLVED":
            parsed["operator_id"] = subject_resolution.selected_operator_id
            parsed["operator"] = subject_resolution.selected_operator_id.split("operator:", 1)[-1]
            if parsed["fallback_reason"] in {"unsupported_operator", "operator_revision_unresolved"}:
                parsed["fallback_reason"] = ""
        elif subject_resolution.status == "OUTSIDE_SCOPE":
            parsed["ecosystem"] = subject_resolution.resolved_package.split("package:", 1)[-1]
            parsed["fallback_reason"] = "outside_current_direct_evidence_scope"
        elif subject_resolution.status == "AMBIGUOUS":
            parsed["fallback_reason"] = "ambiguous_operator"
        result = {"graph_identity": self.identity, "parsed": parsed, "knowledge_status": "candidate",
                  "recommendation_eligible": False, "execution_authorized": False,
                  "paths": [], "gaps": [], "mapped_chunk_ids": [], "fallback_reason": parsed["fallback_reason"],
                  "subject_resolution": subject_resolution.model_dump()}
        explicit_gap = self._matching_gap(parsed)
        if explicit_gap:
            result["evidence_gap"] = explicit_gap
        allowed_tool_context = {"scanpy", "pca", "neighbors", "hvg", "highly_variable_genes", "umap", "leiden", "harmony", "scrublet", "singler"}
        if parsed["operator"] == "highly_variable_genes" and parsed["flavor"] in {"seurat", "seurat_v3", "seurat_v3_paper"}:
            allowed_tool_context.add("seurat")  # A flavor token is not a different package operator.
        if request.include_catalog:
            result["fallback_reason"] = "discovery_track_out_of_scope"
        elif request.tool_names and any(t.casefold() not in allowed_tool_context for t in request.tool_names):
            result["fallback_reason"] = "different_or_multiple_tool_context"
        if result["fallback_reason"]:
            return [], result
        if snapshot_id != SNAPSHOT_ID or corpus_digest != CORPUS_DIGEST:
            result["fallback_reason"] = "snapshot_not_qualified"
            return [], result
        operators = [o for o in self.operators if o.operator_id == parsed["operator_id"]]
        if len(operators) != 1:
            result["fallback_reason"] = "operator_revision_unresolved"
            return [], result
        op = operators[0]
        result["resolved_operator_revision"] = op.entity_id
        predicates = set().union(*(PREDICATES[n] for n in parsed["information_needs"]))
        claims = [c for c in self.bundle.atomic_claims if c.subject_id == op.entity_id and c.predicate in predicates]
        if not claims:
            result["fallback_reason"] = "information_need_not_expressed_in_graph"
        for claim in claims:
            scope = self.scopes[claim.scope_id]
            condition, error = self._scope(scope, parsed)
            requirements = [r for p in op.input_ports for r in p.requirements
                            if (claim.object_id in r.representation_constraint_ids or
                                (claim.object_id is None and r.scope_id == claim.scope_id))]
            constraint_ids = sorted({c for r in requirements for c in r.representation_constraint_ids})
            path = {"operator_revision_id": op.entity_id, "claim_revision_id": claim.claim_revision_id,
                    "predicate": claim.predicate, "scope": condition, "claim_content_hash": claim.content_hash,
                    "requirement_ids": [r.requirement_id for r in requirements], "constraint_ids": constraint_ids,
                    "constraints": [self.constraints[c].model_dump(mode="json") for c in constraint_ids],
                    "requirements": [r.model_dump(mode="json") for r in requirements],
                    "output_port_ids": [p.output_port_id for p in op.output_ports if p.representation_type_id == claim.object_id],
                    "evidence": [], "status": error or "binding_pending", "knowledge_status": "candidate"}
            result["paths"].append(path)
            if error:
                result["gaps"].append({"claim_revision_id": claim.claim_revision_id, "reason": error})
                continue
            binding = self.bindings.get(claim.claim_revision_id)
            if not binding or not binding.get("evidence_span_ids"):
                path["status"] = "evidence_binding_missing"
                result["gaps"].append({"claim_revision_id": claim.claim_revision_id, "reason": path["status"]})
                continue
            for span_id in binding["evidence_span_ids"]:
                span, error = self._span_binding(claim, binding, span_id)
                if error:
                    result["gaps"].append({"evidence_span_id": span_id, "reason": error})
                    continue
                mapped = [c.chunk_id for c in chunks.values() if
                          span_id in {c.chunk_id, c.evidence_id, c.source_record_id} and
                          (c.source_document_id or c.source_id) == span["source_revision_id"] and
                          c.source_span == span["locator"] and c.content_hash == span["content_hash"] and
                          c.chunk_text == span["source_excerpt"] and c.source_bound and
                          c.retrieval_status == "retrieval_only" and str(c.recommendation_eligible).casefold() != "true"]
                path["evidence"].append({"evidence_span_id": span_id, "source_revision_id": span["source_revision_id"],
                                          "locator": span["locator"], "content_hash": span["content_hash"],
                                          "source_file_sha256": span["source_file_sha256"], "chunk_ids": sorted(mapped),
                                          "binding_verified": True, "knowledge_status": "candidate",
                                          "mapping_basis": "span_identity_source_revision_locator_hash_and_exact_excerpt"})
                if not mapped:
                    result["gaps"].append({
                        "evidence_span_id": span_id,
                        "reason": "no_exact_chunk_in_frozen_corpus",
                        "reason_code": "GRAPH_EVIDENCE_NOT_IN_CORPUS",
                    })
                result["mapped_chunk_ids"].extend(mapped)
            path["status"] = "mapped" if any(e["chunk_ids"] for e in path["evidence"]) else "no_mapped_evidence"
        all_ids = sorted(set(result["mapped_chunk_ids"]))
        result["mapped_chunk_ids"] = all_ids[:MAX_GRAPH_CHUNKS]
        result["budget_omitted_chunk_ids"] = all_ids[MAX_GRAPH_CHUNKS:]
        if not result["mapped_chunk_ids"] and not result["fallback_reason"]:
            result["fallback_reason"] = "no_supported_mapped_evidence"
        return [(cid, 1.0) for cid in result["mapped_chunk_ids"]], result

    @staticmethod
    def answerability(diagnostic: dict[str, Any]) -> dict[str, Any]:
        paths = diagnostic.get("paths", [])
        final_ids = list(diagnostic.get("final_graph_chunk_ids", []))
        span_ids = sorted({e.get("evidence_span_id", "") for p in paths for e in p.get("evidence", []) if e.get("evidence_span_id")})
        source_ids = sorted({e.get("source_revision_id", "") for p in paths for e in p.get("evidence", []) if e.get("source_revision_id")})
        claim_ids = sorted({p.get("claim_revision_id", "") for p in paths if p.get("claim_revision_id")})
        scopes = [p.get("scope", {}) for p in paths]
        gap = diagnostic.get("evidence_gap") or {}
        fallback = diagnostic.get("fallback_reason", "")
        clarification = {
            "ambiguous_operator",
            "multiple_conditions_require_clause_resolution",
            "requested_version_unknown",
            "required_condition_missing",
            "required_reference_or_biological_scope_missing",
        }
        if final_ids:
            status, reason = "SUPPORTED", "direct_source_bound_graph_evidence_resolved"
        elif fallback in clarification:
            status, reason = "CLARIFICATION_REQUIRED", fallback
        elif gap:
            status, reason = "INSUFFICIENT_EVIDENCE", "explicit_evidence_gap"
        else:
            status, reason = "UNRESOLVED", fallback or "direct_graph_evidence_unresolved"
        return {
            "status": status, "reason": reason, "scientific_kg_used": bool(final_ids),
            "operator_revision_id": diagnostic.get("resolved_operator_revision", ""),
            "claim_ids": claim_ids, "evidence_span_ids": span_ids, "source_revision_ids": source_ids,
            "scope_status": next((s.get("scope_status", "") for s in scopes if s), ""),
            "version_status": next((s.get("version_status", "") for s in scopes if s), ""),
            "evidence_gap_id": gap.get("gap_id", ""), "fallback_reason": fallback,
            "direct_evidence_chunk_ids": final_ids, "candidate_only": True,
        }
