"""Read-only Research Chat projection of the human-approved v2 package.

Git objects in THIS repository are the immutable package store. No checkout,
source-corpus reconstruction, candidate promotion, or execution authority occurs.
The evidence index contains the package's exact excerpts, not invented documents.
"""
from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from core.knowledge_intelligence_models import EvidenceAnswerability, HybridRetrievalHit, HybridRetrievalResult
from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import EvidenceChunk

APPROVED_COMMIT = "6018699092d979a2da0dda45a19c920018ed9eda"
SNAPSHOT_ID = "approved-scientific-kg-v2-01"
APPROVED_SHA256 = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
PACKAGE_PATH = "reconstruction/promotion_v2/snapshots/approved-v2-01"
HELD_ID = "statement-revision:d0d887b96b7a1cf45e2c47bf:1"
CAUTION_POLICY = dict(scientific_assertion=False, trusted=False, production_retrieval_eligible=False,
                      execution_gate=False, execution_authorized=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def user_scope(text: str) -> dict:
    """Only explicit user values; multiple alternatives remain unknown.

    This extracts context, not applicability. Neither model rewrite nor API
    defaults supplies missing values. Unknown qualifier names are not guessed.
    """
    result = {}
    for key in ("flavor", "chunked", "zero_center", "assay", "modality"):
        values = re.findall(r"\b" + key + r"\s*[=:]\s*['\"]?([a-z0-9_.-]+)", text, re.I)
        if key == "flavor" and not values:
            values = re.findall(r"(?<![a-z0-9_])(?:seurat_v3_paper|seurat_v3|cell_ranger|seurat)(?![a-z0-9_])", text, re.I)
        if values:
            vals = sorted(set(v.casefold() for v in values))
            result[key] = (vals[0] == "true" if vals[0] in {"true", "false"} else vals[0]) if len(vals) == 1 else None
    versions = set(re.findall(r"\b(?:Scanpy|scVelo|Scrublet|CellRank|Harmony|version)\s*[=:v ]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", text, re.I))
    if versions:
        result["software_version"] = next(iter(versions)) if len(versions) == 1 else None
    if re.search(r"版本.{0,4}(未知|不清楚|不知道)|不知道.{0,4}版本|version\s*[=:]\s*unknown", text, re.I):
        result["software_version"] = None
    if re.search(r"scrna[- ]?seq|单细胞RNA", text, re.I):
        result.setdefault("modality", "scrna-seq")
    if re.search(r"scatac[- ]?seq", text, re.I):
        result["modality"] = "scatac-seq"
    return result


def condition_status(condition: dict, context: dict) -> str:
    key = condition.get("parameter_id", "").rsplit(":", 1)[-1]
    value = context.get(key)
    if value is None:
        return "unknown"
    if condition.get("operator") not in {"equals", "in"}:
        return "unknown"
    norm = lambda v: v.casefold() if isinstance(v, str) else v
    return "matched" if norm(value) in [norm(v) for v in condition.get("values", [])] else "mismatch"


def scope_result(statement: dict, context: dict) -> dict:
    dimensions = {}
    for key, expected in statement.get("qualifiers", {}).items():
        value = context.get(key)
        if key == "parameter_condition":
            dimensions[key] = condition_status(expected, context)
        elif key == "software_version":
            dimensions[key] = ("unknown" if value is None or expected.get("status") != "exact"
                               else "matched" if value == expected.get("expression") else "mismatch")
        else:
            dimensions[key] = ("unknown" if value is None else
                               "matched" if str(value).casefold() == str(expected).casefold() else "mismatch")
    status = ("exclude" if "mismatch" in dimensions.values() else
              "unknown" if statement.get("scope_status") != "explicit" or "unknown" in dimensions.values() else "applicable")
    return {"status": status, "dimensions": dimensions, "scope_status": statement["scope_status"],
            "qualifiers": deepcopy(statement.get("qualifiers", {})), "approval_implies_applicability": False}


class ApprovedScientificKG:
    """Fail-closed loader and in-memory evidence/descriptor joins."""

    def __init__(self, repository: Path = PROJECT_ROOT):
        self.repository = Path(repository)
        def blob(name):
            return subprocess.check_output(["git", "-C", str(self.repository), "show",
                                            f"{APPROVED_COMMIT}:{PACKAGE_PATH}/{name}"], stderr=subprocess.PIPE)
        self.manifest = json.loads(blob("promotion_manifest.json"))
        if self.manifest.get("snapshot_id") != SNAPSHOT_ID or self.manifest.get("approved_kg_sha256") != APPROVED_SHA256:
            raise ValueError("approved_snapshot_identity_mismatch")
        payloads = {}
        for name, expected in self.manifest["output_sha256"].items():
            raw = blob(name)
            if _sha(raw) != expected:
                raise ValueError("approved_package_hash_mismatch:" + name)
            payloads[name] = raw
        self.package = json.loads(payloads["approved_kg.json"])
        if _sha(payloads["approved_kg.json"]) != APPROVED_SHA256:
            raise ValueError("approved_kg_hash_mismatch")
        self.allowlist = frozenset(self.manifest["production_retrieval_statement_revision_ids"])
        self.statements = {s["statement_revision_id"]: s for s in self.package["statements"]}
        if len(self.allowlist) != 121 or set(self.statements) != self.allowlist or HELD_ID in self.allowlist:
            raise ValueError("approved_allowlist_mismatch")
        gov = {r["record_id"]: r for r in self.package["governance"]}
        if any(not gov[s].get("trusted") or not gov[s].get("production_retrieval_eligible")
               or gov[s].get("execution_authorized") or gov[s].get("knowledge_status") != "approved" for s in self.allowlist):
            raise ValueError("approved_governance_mismatch")
        self.entities = {e["id"]: e for e in self.package["entities"]}
        self.links = defaultdict(list)
        for link in self.package["links"]:
            self.links[link["subject_id"]].append(link)
        self.spans = {e["evidence_span_id"]: e for e in self.package["evidence_spans"]}
        self.sources = {}
        self.artifact_sources = {}
        for p in self.package["provenance"]:
            if "source" in p and "source_revision_id" in p:
                src = p["source"]
                metadata = {"source_revision_id": p["source_revision_id"], "source_artifact_id": p["source_artifact_id"],
                    "source_work_id": p["source_work_id"], "version": src.get("version"),
                    "source_url": src.get("source_work_identifier", ""), "source_type": src.get("source_type"),
                    "title": src.get("source_key", ""), "artifact_hash": src.get("sha256"),
                    "text_hash": src.get("text_sha256")}
                self.artifact_sources[p["source_artifact_id"]] = metadata
                self.sources.setdefault(p["source_revision_id"], {k: metadata[k] for k in
                    ("source_revision_id", "source_work_id", "version")})
        for span in self.spans.values():
            if _sha(span["exact_text"].encode()) != span["content_hash"]:
                raise ValueError("approved_excerpt_hash_mismatch")
            if span["source_revision_id"] not in self.sources or span["source_artifact_id"] not in self.entities:
                raise ValueError("approved_source_chain_missing")
            metadata = self.source_for_span(span)
            if metadata["source_revision_id"] != span["source_revision_id"] or metadata["text_hash"] not in span["locator"]["value"]:
                raise ValueError("approved_artifact_metadata_mismatch")
            if not any(l["predicate"] == "artifact_of" and l["object_id"] == span["source_revision_id"]
                       for l in self.links[span["source_artifact_id"]]):
                raise ValueError("approved_artifact_revision_mismatch")
        self.assessments = defaultdict(list)
        for a in self.package["evidence_assessments"]:
            if a["statement_revision_id"] in self.allowlist:
                self.assessments[a["statement_revision_id"]].append(a)
        self.utility = defaultdict(list)
        for u in self.package["utility"]:
            if u.get("statement_revision_id") in self.allowlist:
                self.utility[u["statement_revision_id"]].append(u.get("interpretation", ""))
        self.cautions = json.loads(payloads["caution_context_index.json"])
        for caution in self.cautions:
            for span in caution["evidence"]:
                if self.spans.get(span["evidence_span_id"]) != span:
                    raise ValueError("caution_span_mismatch")
        self.chunks, self.fact_by_chunk = {}, {}
        for sid, statement in self.statements.items():
            direct = [a for a in self.assessments[sid] if a["support_type"] == "DIRECT_SUPPORT"
                      and all(a.get(k) is True for k in ("subject_aligned", "predicate_aligned", "object_aligned"))]
            if not direct:
                raise ValueError("approved_direct_support_missing:" + sid)
            for assessment in direct:
                span = self.spans[assessment["evidence_span_id"]]
                cid = "approved-v2:" + _sha((sid + span["evidence_span_id"]).encode())[:24]
                self.chunks[cid] = self._chunk(cid, statement, span)
                self.fact_by_chunk[cid] = (sid, assessment["assessment_id"], span["evidence_span_id"])
        self.query_count = 0

    def source_for_span(self, span):
        # A release may own several source files; never let the last artifact's
        # title/hash overwrite the identity of every excerpt in that release.
        return deepcopy(self.artifact_sources[span["source_artifact_id"]])

    def _chunk(self, cid, statement, span):
        source = self.source_for_span(span)
        return EvidenceChunk(chunk_id=cid, evidence_id=span["evidence_span_id"],
            source_kind=source["source_type"] or "approved_package_excerpt", source_table="approved_scientific_kg_v2",
            source_record_id=statement["statement_revision_id"], source_id=span["source_revision_id"],
            source_span=span["locator"]["value"], tool_name=self.tool_name(statement["subject_id"]),
            title=source["title"], claim_text=span["exact_text"], chunk_text=span["exact_text"],
            claim_type={"has_requirement": "input_requirement", "has_parameter": "parameter"}.get(statement["predicate"], "method"),
            content_hash=span["content_hash"], source_bound=True, review_status="approved",
            recommendation_eligible="false", kg_version=SNAPSHOT_ID)

    @staticmethod
    def tool_name(subject):
        if subject.startswith("operator-revision:"):
            return subject.split(":")[2]
        return subject.split(":")[-1]

    def subjects(self, query):
        q = query.casefold()
        subjects = {s["subject_id"] for s in self.statements.values()}
        found = {s for s in subjects if re.search(r"(?<![a-z0-9_])" + re.escape(self.tool_name(s)) + r"(?![a-z0-9_])", q)}
        if re.search(r"flavor\s*[=:]", q):
            found = {s for s in found if self.tool_name(s) != "seurat"}
        operators = {"highly_variable_genes": r"highly.variable|\bhvg\b|高变", "pca": r"\bpca\b|主成分",
                     "neighbors": r"\bneighbors\b", "leiden": r"\bleiden\b", "umap": r"\bumap\b"}
        named = {name for name, pattern in operators.items() if re.search(pattern, q)}
        if named:
            found = {s for s in found if ":scanpy:" not in s} | {s for s in subjects if any("scanpy.pp." + n + ":" in s or "scanpy.tl." + n + ":" in s for n in named)}
        if not found and re.search(r"doublet|双细胞", q):
            found = {s["subject_id"] for s in self.statements.values() if s["object_id"] == "task:doublet-detection"}
        return found

    def _descriptors(self, statement, context):
        req = self.entities.get(statement["object_id"], {}) if statement["predicate"] == "has_requirement" else {}
        constraints = [self.entities[l["object_id"]] for l in self.links.get(req.get("id"), []) if l["predicate"] == "requires_constraint"]
        outputs = []
        for link in self.links[statement["subject_id"]]:
            if link["predicate"] != "has_output_port":
                continue
            port = deepcopy(self.entities[link["object_id"]])
            statuses = [condition_status(c, context) for c in port.get("production_conditions", [])]
            port["condition_combination"] = "ALL_OF"
            port["applicability"] = "exclude" if "mismatch" in statuses else "unknown" if "unknown" in statuses else "applicable"
            port["source_context"] = [{"evidence_span_id": p["evidence_span_id"], "rationale": p.get("rationale", ""),
                                       "exact_excerpt": self.spans[p["evidence_span_id"]]["exact_text"]}
                for p in self.package["provenance"] if p.get("record_ref") == port["id"] and p.get("evidence_span_id") in self.spans]
            outputs.append(port)
        return ([deepcopy(req)] if req else []), deepcopy(constraints), outputs

    def fact(self, cid, context):
        sid, aid, eid = self.fact_by_chunk[cid]
        s, span = self.statements[sid], self.spans[eid]
        requirements, constraints, outputs = self._descriptors(s, context)
        scope = scope_result(s, context)
        return {"statement_id": sid, "statement": " ; ".join(self.utility[sid]) or f"{s['subject_id']} {s['predicate']} {s['object_id']}",
            "registered_statement": deepcopy(s), "predicate": s["predicate"], "scope": scope,
            "requirements": requirements, "constraints": constraints, "output_ports": outputs,
            "knowledge_status": "approved", "snapshot_id": SNAPSHOT_ID, "trusted": True,
            "production_retrieval_eligible": True, "recommendation_eligible": False,
            "execution_gate": False, "execution_authorized": False,
            "assessment_ids": [aid], "evidence_span_id": eid, "source_revision_id": span["source_revision_id"],
            "source_artifact_id": span["source_artifact_id"],
            "assessments": [deepcopy(a) for a in self.assessments[sid] if a["assessment_id"] == aid],
            "locator": span["locator"]["value"], "binding_verified": True,
            "binding_basis": "immutable_package_and_exact_excerpt_hash",
            "original_source_file_reverified": False}

    def search(self, request, context=None, subject_query=None):
        started = time.perf_counter()
        self.query_count += 1
        context = user_scope(request.query) if context is None else context
        subjects = self.subjects(subject_query or request.query)
        q = (request.query + " " + (subject_query or "")).casefold()
        # Bilingual retrieval aliases affect ranking only, never scientific values.
        for needle, terms in [("输入", "input requirement counts"), ("因果", "causal lineage driver correlation"),
                              ("singlet", "parent singlet detectability"), ("亲本", "parent singlet detectability")]:
            if needle in q:
                q += " " + terms
        tokens = set(re.findall(r"[a-z_]{3,}", q))
        score = lambda text: sum(t in text.casefold() for t in tokens)
        matches, excluded = [], []
        for cid, (sid, _, _) in self.fact_by_chunk.items():
            s = self.statements[sid]
            if s["subject_id"] not in subjects:
                continue
            scope = scope_result(s, context)
            if scope["status"] == "exclude":
                excluded.append(sid)
                continue
            chunk = self.chunks[cid]
            rank = score(" ".join(self.utility[sid]) + str(s) + chunk.chunk_text)
            matches.append((rank, cid, self.fact(cid, context)))
        matches.sort(key=lambda row: (-row[0], row[1]))
        selected = matches[:min(request.top_k, 12)]
        cautions = sorted([dict(deepcopy(c), **CAUTION_POLICY) for c in self.cautions
                           if subjects.intersection(c["subject_ids"])], key=lambda c: (-score(c["description"]), c["caution_id"]))[:4]
        hits, paths = [], []
        for rank, cid, fact in selected:
            chunk = self.chunks[cid]
            hits.append(HybridRetrievalHit(chunk_id=cid, source_id=chunk.source_id, tool_name=chunk.tool_name,
                source_span=chunk.source_span, title=chunk.title, text=chunk.chunk_text, claim_type=chunk.claim_type,
                score=float(rank + 1), source_bound=True, recommendation_eligible=False, governance_status="approved_scientific_assertion"))
            paths.append({"status": "mapped", "claim_revision_id": fact["statement_id"], "fact": fact,
                "evidence": [{"evidence_span_id": fact["evidence_span_id"], "source_revision_id": fact["source_revision_id"],
                              "locator": fact["locator"], "chunk_ids": [cid], "binding_verified": True}]})
        ids = [h.chunk_id for h in hits]
        diag = {"adapter": "ApprovedScientificKG", "snapshot_id": SNAPSHOT_ID, "approved_kg_sha256": APPROVED_SHA256,
            "package_commit": APPROVED_COMMIT, "hash_verified": True, "query_count": self.query_count,
            "approved_statements_visible": len(self.allowlist), "held_statements_visible": 0,
            "legacy_kg_consulted": False, "scope_policy_active": True, "scope_context": context,
            "subjects": sorted(subjects), "paths": paths, "cautions": cautions, "caution_policy": CAUTION_POLICY,
            "excluded_statement_ids": sorted(set(excluded)), "eligible_chunk_ids": ids, "final_graph_chunk_ids": ids,
            "execution_authorized": False, "fallback_reason": "" if hits else "approved_kg_no_matching_statement"}
        unknown = any(f[2]["scope"]["status"] == "unknown" for f in selected)
        return HybridRetrievalResult(query=request.query, mode="kg_bm25", hits=hits,
            latency_ms=(time.perf_counter()-started)*1000, index_build_id=SNAPSHOT_ID,
            pipeline=["approved_manifest_allowlist", "scope_policy", "approved_exact_evidence_index"], scientific_evidence=diag,
            answerability=EvidenceAnswerability(status="CLARIFICATION_REQUIRED" if unknown else "SUPPORTED" if hits else "INSUFFICIENT_EVIDENCE",
                reason="conditional_knowledge_scope_unknown" if unknown else "approved_exact_evidence" if hits else "approved_kg_no_matching_statement",
                scientific_kg_used=bool(hits), claim_ids=sorted({f[2]["statement_id"] for f in selected}),
                direct_evidence_chunk_ids=ids, candidate_only=False, scope_status="unknown" if unknown else "matched" if hits else "unknown"))

    def enrich_references(self, references, diagnostic):
        from agent.scientific_response_context import _diagnostics
        rows = [dict(ref, knowledge_source="RETRIEVAL_GROUNDED", kg_statements=[]) for ref in references]
        for diag in _diagnostics(diagnostic):
            final = set(diag.get("final_graph_chunk_ids", []))
            for path in diag.get("paths", []):
                for evidence in path.get("evidence", []):
                    for ref in rows:
                        cid = ref.get("source_span_id")
                        if cid not in final.intersection(evidence["chunk_ids"]) or ref.get("source_id") != evidence["source_revision_id"] or ref.get("source_span") != evidence["locator"]:
                            continue
                        if path["fact"] not in ref["kg_statements"]:
                            ref["kg_statements"].append(deepcopy(path["fact"]))
                        source = self.source_for_span(self.spans[evidence["evidence_span_id"]])
                        ref.update(knowledge_source="KG_GROUNDED", exact_excerpt=self.spans[evidence["evidence_span_id"]]["exact_text"],
                                   source_url=source["source_url"], source_type=source["source_type"], source_revision=source,
                                   evidence_span=deepcopy(self.spans[evidence["evidence_span_id"]]))
        return rows


class GovernedChatRetrieval:
    """Keep Legacy KG available only in its explicit baseline lane.

    Production/scientific queries NEVER call the legacy retriever. Scope comes
    from user turns, separate from an LLM-generated retrieval query. ContextVar
    avoids cross-session context leakage in the shared Streamlit backend.
    """
    governed_scientific = True

    def __init__(self, legacy, approved=None):
        self.legacy = legacy
        self.approved = approved or ApprovedScientificKG()
        self._chunks_by_id = {**legacy._chunks_by_id, **self.approved.chunks}
        self.profile = "scientific_kg"
        self._turn = ContextVar("approved_chat_user_scope", default=None)

    @property
    def _scientific_evidence_adapter(self):
        return self.approved if self.governed_scientific else getattr(self.legacy, "_scientific_evidence_adapter", None)

    def configure_profile(self, profile):
        self.profile = profile or "scientific_kg"
        self.governed_scientific = self.profile == "scientific_kg"

    def begin_turn(self, query, conversation):
        context, subject_query = {}, ""
        for row in [*conversation, {"role": "user", "content": query}]:
            if row.get("role") != "user":
                continue
            text = str(row.get("content", ""))
            named = self.approved.subjects(text)
            previous = self.approved.subjects(subject_query)
            if named and previous and not named.intersection(previous):
                context = {}
            if named:
                subject_query = text
            context.update(user_scope(text))
        if not self.approved.subjects(query) and not re.search(
                r"^(那|如果|改成|上述|这个|这些|同样|为什么|这句话)|证据|原文|\b(flavor|chunked|zero_center)\s*[=:]", query, re.I):
            context, subject_query = user_scope(query), query
        self._turn.set((context, subject_query))

    def search(self, request):
        if self.profile == "llm_only":
            return HybridRetrievalResult(query=request.query, mode="bm25", latency_ms=0,
                                         pipeline=["llm_only_no_retrieval"])
        if self.governed_scientific:
            turn = self._turn.get()
            return self.approved.search(request, *(turn or (None, None)))
        result = self.legacy.search(request.model_copy(update={"use_scientific_evidence": self.profile == "legacy_kg",
                                    "use_kg": self.profile in {"legacy_kg", "kg_hybrid", "kg_hybrid_contract"}}))
        if result.scientific_evidence is not None and self.profile == "legacy_kg":
            result.scientific_evidence["baseline_identity"] = "Legacy KG (frozen 1651-node scientific inventory)"
        return result

    def start_dense_warmup(self):
        if not self.governed_scientific:
            return self.legacy.start_dense_warmup()

    def __getattr__(self, name):
        return getattr(self.legacy, name)
