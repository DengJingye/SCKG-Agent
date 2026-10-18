"""Evidence-bound candidates, explicit local human decisions and atomic releases.

This module enforces integrity, never scientific truth. Source assertions remain
scoped assertions even after review. No legacy stores or model defaults are read.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from math import log

from .contracts import EvidencePackage, OpenClaim, SemanticAssessment
from .storage import canonical_json, content_hash, new_id, utcnow


class KnowledgeError(ValueError):
    pass


def _cjk_ngrams(value: str) -> set[str]:
    """Character n-grams are a recall aid, not a scientific relevance decision."""
    grams = set()
    for run in re.findall(r"[\u3400-\u9fff]+", value):
        for size in (2, 3):
            grams.update(run[index:index + size] for index in range(len(run) - size + 1))
    return grams


class KnowledgeService:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.connect() as conn:
            conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS release_search USING fts5(
                release_id UNINDEXED, candidate_id UNINDEXED, text, tokenize='unicode61')""")

    def _required(self, kind, record_id, conn=None):
        record = self.ledger.get_record(kind, record_id, conn=conn)
        if record is None:
            raise KnowledgeError(f"Unknown {kind}: {record_id}")
        return record

    def _anchors(self, claim, conn=None):
        evidence = []
        for anchor in claim["anchors"]:
            ir = self._required("document_ir", anchor["ir_id"], conn)
            block = next((b for b in ir["blocks"] if b["id"] == anchor["block_id"]), None)
            if block is None or block["exact_text"][anchor["start"]:anchor["end"]] != anchor["quote"]:
                raise KnowledgeError("Evidence quote does not match the exact document span")
            source = self._required("source", ir["source_id"], conn)
            if source["source_revision_id"] != ir["source_revision_id"]:
                raise KnowledgeError("Evidence source revision mismatch")
            sha = source["blob_sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise KnowledgeError("Invalid original digest")
            path = self.ledger.workspace.artifacts_dir / "source_blobs" / sha
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise KnowledgeError("Original evidence blob is missing or changed")
            evidence.append({**anchor, "source_id": source["id"], "source_revision_id": ir["source_revision_id"],
                             "snapshot_id": source["snapshot_id"], "blob_sha256": sha,
                             "filename": source["filename"], "locator": block["locator"],
                             "parse_status": ir["status"], "coverage": ir["coverage"], "gaps": ir["gaps"]})
        return evidence

    def add_candidate(self, claim, *, run_id, profile_id, lease_guard=None):
        claim = OpenClaim.model_validate(claim).model_dump(mode="json")
        self._required("model_profile", profile_id)
        with self.ledger.transaction() as conn:
            if lease_guard:
                lease_guard(conn)
            record = self._store_candidate(claim, {"run_id": run_id, "profile_id": profile_id}, conn=conn)
        return record

    def _store_candidate(self, claim, origin, *, conn):
        """Shared integrity path; callers authenticate their own execution origin."""
        claim = OpenClaim.model_validate(claim).model_dump(mode="json")
        evidence = self._anchors(claim, conn)
        payload = {"claim": claim, "source_ids": sorted({e["source_id"] for e in evidence}),
                   "source_revision_ids": sorted({e["source_revision_id"] for e in evidence})}
        digest = content_hash(payload)
        candidate_id = "candidate-" + digest
        existing = self.ledger.get_record("candidate", candidate_id, conn=conn)
        record = existing or {"id": candidate_id, **payload, "content_hash": digest, "created_at": utcnow(),
                              "origin": origin, "status": "candidate"}
        self.ledger.put_record("candidate", candidate_id, record, conn=conn)
        self.ledger.append_event("candidate_observed", candidate_id, origin, conn=conn)
        return record

    def assess(self, candidate_id, assessment, *, run_id, profile_id, call_id, lease_guard=None):
        result = SemanticAssessment.model_validate(assessment).model_dump(mode="json")
        profile = self._required("model_profile", profile_id)
        if profile["purpose"] != "assessment":
            raise KnowledgeError("An assessment profile is required")
        call = self._required("model_call", call_id)
        if call["profile_id"] != profile_id or call["status"] != "succeeded":
            raise KnowledgeError("Assessment must reference a successful matching model call")
        request = self._required("model_request", call_id)
        messages = request["payload"].get("messages", [])
        if not messages or messages[-1] != {"role": "user", "content": canonical_json(self.assessment_input(candidate_id))}:
            raise KnowledgeError("Assessment call does not bind the exact candidate and evidence context")
        if call.get("structured_output_hash") != content_hash(assessment):
            raise KnowledgeError("Assessment result differs from the actual model output")
        with self.ledger.transaction() as conn:
            if lease_guard:
                lease_guard(conn)
            candidate = self._required("candidate", candidate_id, conn)
            self._anchors(candidate["claim"], conn)
            assessment_id = "assessment-" + content_hash([candidate_id, call_id])
            existing = self.ledger.get_record("assessment", assessment_id, conn=conn)
            if existing is not None:
                return existing
            record = {"id": assessment_id, "candidate_id": candidate_id, "candidate_hash": candidate["content_hash"],
                      "result": result, "run_id": run_id, "profile_id": profile_id, "call_id": call_id, "created_at": utcnow()}
            self.ledger.put_record("assessment", record["id"], record, conn=conn)
            self.ledger.set_state("assessment:" + candidate_id, record["id"], conn=conn)
            self._bump_governance(conn)
            self.ledger.append_event("candidate_assessed", candidate_id, {"assessment_id": record["id"]}, conn=conn)
        return record

    def list_candidates(self):
        result = []
        with self.ledger.connect() as conn:
            for candidate in self.ledger.list_records("candidate", conn=conn):
                record = dict(candidate)
                for kind in ("assessment", "review"):
                    ref = self.ledger.get_state(kind + ":" + candidate["id"], conn=conn)
                    record[kind] = self.ledger.get_record(kind, ref, conn=conn) if ref else None
                result.append(record)
        return result

    def evidence(self, candidate_id):
        candidate = self._required("candidate", candidate_id)
        return self._anchors(candidate["claim"])

    def assessment_input(self, candidate_id, *, conn=None):
        candidate = self._required("candidate", candidate_id, conn)
        self._anchors(candidate["claim"], conn)
        documents = []
        for ir_id in sorted({a["ir_id"] for a in candidate["claim"]["anchors"]}):
            ir = self._required("document_ir", ir_id, conn)
            block_ids = {a["block_id"] for a in candidate["claim"]["anchors"] if a["ir_id"] == ir_id}
            documents.append({"ir_id": ir_id, "source_revision_id": ir["source_revision_id"], "status": ir["status"],
                              "gaps": ir["gaps"], "coverage": ir["coverage"],
                              "blocks": [b for b in ir["blocks"] if b["id"] in block_ids]})
        return {"claim": candidate["claim"], "documents": documents}

    @staticmethod
    def _human(actor, reason):
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise KnowledgeError("An explicit human actor and reason are required")

    def review(self, candidate_id, *, actor, decision, allowed_uses, reason, expected_hash, expected_assessment_id=None):
        self._human(actor, reason)
        if decision not in {"approve", "reject", "defer"}:
            raise KnowledgeError("Invalid review decision")
        if not isinstance(allowed_uses, list) or any(u not in {"explanation", "recommendation"} for u in allowed_uses):
            raise KnowledgeError("Invalid approved uses")
        if decision == "approve" and not allowed_uses:
            raise KnowledgeError("Approval must specify scientific uses")
        if decision != "approve" and allowed_uses:
            raise KnowledgeError("Only approval grants a use")
        with self.ledger.transaction() as conn:
            candidate = self._required("candidate", candidate_id, conn)
            if expected_hash != candidate["content_hash"]:
                raise KnowledgeError("Candidate changed; review the exact revision")
            assessment_id = self.ledger.get_state("assessment:" + candidate_id, conn=conn)
            assessment = self.ledger.get_record("assessment", assessment_id, conn=conn) if assessment_id else None
            if decision == "approve":
                if not expected_assessment_id or expected_assessment_id != assessment_id:
                    raise KnowledgeError("Evidence assessment changed; review the exact assessment")
                if not assessment or assessment["candidate_hash"] != expected_hash:
                    raise KnowledgeError("An exact evidence assessment is required before approval")
                self._anchors(candidate["claim"], conn)
                if "recommendation" in allowed_uses:
                    result = assessment["result"]
                    if result["relation"] != "support" or result["extent"] != "full" or candidate["claim"]["assertion_kind"] != "source_assertion":
                        raise KnowledgeError("Recommendation requires full support for a source assertion")
                if self._suspended(candidate, conn):
                    raise KnowledgeError("Suspended evidence cannot be approved")
            record = {"id": new_id("review"), "candidate_id": candidate_id, "candidate_hash": expected_hash,
                      "assessment_id": assessment_id, "actor": actor.strip(), "decision": decision,
                      "allowed_uses": sorted(set(allowed_uses)), "reason": reason, "created_at": utcnow(),
                      "authority": "explicit_local_human_action"}
            self.ledger.put_record("review", record["id"], record, conn=conn)
            self.ledger.set_state("review:" + candidate_id, record["id"], conn=conn)
            self._bump_governance(conn)
            self.ledger.append_event("human_review", candidate_id, {"review_id": record["id"], "decision": decision}, conn=conn)
        return record

    def current_release(self):
        with self.ledger.connect() as conn:
            ref = self.ledger.get_state("current_release", conn=conn)
            return self.ledger.get_record("release", ref, conn=conn) if ref else None

    def publish(self, candidate_ids, *, actor, expected_release_id=None, expected_review_ids=None):
        """Publish an explicit FULL manifest; omission removes a prior unit.

        A release, FTS projection and current pointer share one SQLite commit.
        Review IDs are frozen in the manifest, never resolved to latest later.
        """
        self._human(actor, "publish")
        if not isinstance(candidate_ids, list) or len(candidate_ids) != len(set(candidate_ids)):
            raise KnowledgeError("An explicit list of distinct candidate IDs is required")
        with self.ledger.transaction() as conn:
            if self.ledger.get_state("current_release", conn=conn) != expected_release_id:
                raise KnowledgeError("Release changed; reload the full proposed manifest")
            units = []
            for candidate_id in candidate_ids:
                candidate = self._required("candidate", candidate_id, conn)
                review_id = self.ledger.get_state("review:" + candidate_id, conn=conn)
                review = self._required("review", review_id, conn)
                if review["decision"] != "approve" or review["candidate_hash"] != candidate["content_hash"]:
                    raise KnowledgeError("Every published revision and use needs explicit human approval")
                if review["assessment_id"] != self.ledger.get_state("assessment:" + candidate_id, conn=conn):
                    raise KnowledgeError("Evidence was reassessed after review; a fresh review is required")
                self._anchors(candidate["claim"], conn)
                if self._suspended(candidate, conn):
                    raise KnowledgeError("Suspended evidence cannot be published")
                units.append({"candidate_id": candidate_id, "candidate_hash": candidate["content_hash"],
                              "review_id": review_id, "assessment_id": review["assessment_id"],
                              "allowed_uses": review["allowed_uses"]})
            if expected_review_ids is not None and expected_review_ids != {u["candidate_id"]: u["review_id"] for u in units}:
                raise KnowledgeError("Review manifest changed; reload the proposed publication")
            release = {"id": new_id("release"), "namespace": self.ledger.workspace.namespace, "parent_id": expected_release_id,
                       "units": units, "actor": actor.strip(), "created_at": utcnow(), "ontology_version": "open-envelope-v1"}
            release["manifest_hash"] = content_hash(release)
            self.ledger.put_record("release", release["id"], release, conn=conn)
            for unit in units:
                c = self._required("candidate", unit["candidate_id"], conn)["claim"]
                attributes = [piece for item in c.get("typed_attributes", [])
                              for piece in (item["name"], item["value"], *item.get("qualifiers", []))]
                text = " ".join([c["proposition"], c["subject"], c["predicate"], c["object"],
                                 *c["conditions"], *c["unknowns"], *attributes])
                conn.execute("INSERT INTO release_search VALUES (?,?,?)", (release["id"], unit["candidate_id"], text))
            self.ledger.set_state("current_release", release["id"], conn=conn)
            self.ledger.append_event("release_published", release["id"], {"parent_id": expected_release_id, "unit_count": len(units)}, conn=conn)
        return release

    def rollback(self, release_id, *, actor, reason):
        self._human(actor, reason)
        with self.ledger.transaction() as conn:
            release = self._required("release", release_id, conn)
            previous = self.ledger.get_state("current_release", conn=conn)
            self.ledger.set_state("current_release", release_id, conn=conn)
            self.ledger.append_event("release_rollback", release_id, {"previous_id": previous, "actor": actor, "reason": reason}, conn=conn)
        return release

    def suspend(self, kind, record_id, *, actor, reason, suspended=True):
        self._human(actor, reason)
        if kind not in {"source", "candidate"} or type(suspended) is not bool:
            raise KnowledgeError("Invalid suspension target")
        with self.ledger.transaction() as conn:
            self._required(kind, record_id, conn)
            record = {"kind": kind, "id": record_id, "suspended": suspended, "actor": actor, "reason": reason, "at": utcnow()}
            self.ledger.set_state("governance:" + kind + ":" + record_id, record, conn=conn)
            version = self._bump_governance(conn)
            self.ledger.append_event("evidence_suspended" if suspended else "evidence_restored", record_id,
                                     {**record, "governance_version": version}, conn=conn)
        return record

    def _bump_governance(self, conn):
        version = self.ledger.get_state("governance_version", 0, conn=conn) + 1
        self.ledger.set_state("governance_version", version, conn=conn)
        return version

    def _suspended(self, candidate, conn=None):
        for kind, record_id in [("candidate", candidate["id"]), *[("source", i) for i in candidate["source_ids"]]]:
            state = self.ledger.get_state("governance:" + kind + ":" + record_id, {}, conn=conn)
            if state.get("suspended"):
                return True
        return False

    def _eligible_unit(self, manifest, *, purpose, conn, gaps):
        """Resolve one current manifest entry through the shared eligibility gates."""
        if purpose not in manifest["allowed_uses"]:
            return None
        cid = manifest["candidate_id"]
        candidate = self._required("candidate", cid, conn)
        if self._suspended(candidate, conn):
            gaps.append("暂停的证据已排除。")
            return None
        # A later reject/defer invalidates use even for an older release.
        latest_review_id = self.ledger.get_state("review:" + cid, conn=conn)
        latest_review = self._required("review", latest_review_id, conn)
        if latest_review["decision"] != "approve" or purpose not in latest_review["allowed_uses"]:
            gaps.append("已撤回或收窄的审核用途已排除。")
            return None
        try:
            evidence = self._anchors(candidate["claim"], conn)
        except (KnowledgeError, OSError):
            gaps.append("缺失或损坏的原文证据已排除。")
            return None
        assessment = self._required("assessment", manifest["assessment_id"], conn)
        if self.ledger.get_state("assessment:" + cid, conn=conn) != manifest["assessment_id"]:
            gaps.append("证据已重新核验，需重新审核发布。")
            return None
        return {"candidate_id": cid, "claim": candidate["claim"], "evidence": evidence,
                "assessment": assessment["result"], "review_id": manifest["review_id"],
                # A live review may narrow a release's uses; a broader review
                # cannot grant a use that has not itself been published.
                "allowed_uses": sorted(set(manifest["allowed_uses"]) & set(latest_review["allowed_uses"])),
                "eligibility": "eligible",
                "confidence": {"model_self_score": candidate["claim"]["model_self_score"],
                               "calibrated_probability": None}}

    def resolve(self, candidate_ids, *, purpose="explanation"):
        """Revalidate exact IDs in the current release without ranking or truncation.

        Missing and ineligible IDs are omitted, never replaced by other units.
        This checks current provenance eligibility, not scientific relevance.
        """
        if (purpose not in {"explanation", "recommendation"}
                or not isinstance(candidate_ids, list)
                or any(not isinstance(cid, str) or not cid.strip() for cid in candidate_ids)
                or len(candidate_ids) != len(set(candidate_ids))):
            raise KnowledgeError("An explicit list of distinct candidate IDs and valid purpose is required")
        with self.ledger.connect() as conn:
            conn.execute("BEGIN")
            release_id = self.ledger.get_state("current_release", conn=conn)
            governance = self.ledger.get_state("governance_version", 0, conn=conn)
            release = self.ledger.get_record("release", release_id, conn=conn) if release_id else None
            retrieval = {"method": "exact_candidate_ids", "candidate_ids": list(candidate_ids),
                         "scope": "current_release_only", "semantic_relevance": "not_verified"}
            if release is None:
                return EvidencePackage(namespace=self.ledger.workspace.namespace, release_id=None, governance_version=governance,
                                       purpose=purpose, units=[], gaps=["尚无正式发布的知识。"], retrieval=retrieval)
            manifests = {u["candidate_id"]: u for u in release["units"]}
            units, gaps = [], []
            for cid in candidate_ids:
                if cid not in manifests:
                    gaps.append("指定证据不在当前发布中。")
                    continue
                unit = self._eligible_unit(manifests[cid], purpose=purpose, conn=conn, gaps=gaps)
                if unit is not None:
                    units.append(unit)
            if candidate_ids and not units:
                gaps.append("指定证据当前不可用于该用途；不能据此推断命题为假。")
            return EvidencePackage(namespace=self.ledger.workspace.namespace, release_id=release_id, governance_version=governance,
                                   purpose=purpose, units=units, gaps=list(dict.fromkeys(gaps)), retrieval=retrieval)

    def search(self, query, *, purpose="explanation", limit=10, unit_filter=None):
        if purpose not in {"explanation", "recommendation"} or type(limit) is not int or not 1 <= limit <= 100:
            raise KnowledgeError("Invalid search purpose or limit")
        if unit_filter is not None and not callable(unit_filter):
            raise KnowledgeError("Search unit filter must be callable")
        if not isinstance(query, str) or len(query) > 8000:
            raise KnowledgeError("Invalid query")
        with self.ledger.connect() as conn:
            # Snapshot release and governance together; no cached eligibility.
            conn.execute("BEGIN")
            release_id = self.ledger.get_state("current_release", conn=conn)
            governance = self.ledger.get_state("governance_version", 0, conn=conn)
            release = self.ledger.get_record("release", release_id, conn=conn) if release_id else None
            retrieval = {"method": "sqlite_fts5_bm25", "dense_index": "not_built", "query": query,
                         "scope": "current_release_only", "semantic_relevance": "not_verified"}
            if release is None:
                return EvidencePackage(namespace=self.ledger.workspace.namespace, release_id=None, governance_version=governance,
                                       purpose=purpose, units=[], gaps=["尚无正式发布的知识。"], retrieval=retrieval)
            manifests = {u["candidate_id"]: u for u in release["units"]}
            words = re.findall(r"[^\W_]+", query, re.UNICODE)[:40]
            if words:
                expression = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
                rows = conn.execute("SELECT candidate_id FROM release_search WHERE release_search MATCH ? AND release_id=? ORDER BY bm25(release_search)",
                                    (expression, release_id)).fetchall()
                ids = [r[0] for r in rows]
            else:
                ids = list(manifests) if not query.strip() else []
            if not ids and _cjk_ngrams(query):
                # unicode61 often indexes an entire Chinese clause as one token.
                # Existing, published index rows supply the fallback corpus; no
                # new claims, source text or governance decisions are inferred.
                query_grams = _cjk_ngrams(query)
                rows = conn.execute("SELECT candidate_id,text FROM release_search WHERE release_id=?", (release_id,)).fetchall()
                candidates = {}
                frequency = Counter()
                for row in rows:
                    cid = row["candidate_id"]
                    if cid not in manifests:
                        continue
                    claim = self._required("candidate", cid, conn)["claim"]
                    attributes = [piece for item in claim.get("typed_attributes", [])
                                  for piece in (item["name"], item["value"], *item.get("qualifiers", []))]
                    primary = query_grams & _cjk_ngrams(" ".join(
                        [claim["proposition"], claim["subject"], claim["predicate"], claim["object"],
                         *attributes]))
                    qualifiers = query_grams & _cjk_ngrams(" ".join([*claim["conditions"], *claim["unknowns"]]))
                    if not primary and not qualifiers:
                        continue
                    candidates[cid] = (primary, qualifiers)
                    frequency.update(primary | qualifiers)
                size = len(rows)
                scored = []
                for cid, (primary, qualifiers) in candidates.items():
                    score = (sum(2 * log((size + 1) / (frequency[gram] + 1)) for gram in primary)
                             + sum(log((size + 1) / (frequency[gram] + 1)) for gram in qualifiers))
                    scored.append((-score, cid))
                ids = [cid for _, cid in sorted(scored)]
                retrieval["method"] = "sqlite_fts5_bm25_then_cjk_ngrams"
                retrieval["fallback_candidate_count"] = len(ids)
            units, gaps = [], []
            for cid in ids:
                unit = self._eligible_unit(manifests[cid], purpose=purpose, conn=conn, gaps=gaps)
                if unit is None:
                    continue
                if unit_filter is not None and not unit_filter(unit, conn):
                    continue
                units.append(unit)
                if len(units) >= limit:
                    break
            if not units:
                gaps.append("当前发布中没有符合检索与用途要求的可用证据；不能据此推断命题为假。")
            return EvidencePackage(namespace=self.ledger.workspace.namespace, release_id=release_id, governance_version=governance,
                                   purpose=purpose, units=units, gaps=list(dict.fromkeys(gaps)), retrieval=retrieval)

    def graph(self):
        package = self.search("", limit=100)
        nodes, edges = {}, []
        for unit in package.units:
            cid = unit["candidate_id"]
            nodes[cid] = {"id": cid, "kind": "claim", "label": unit["claim"]["proposition"]}
            for evidence in unit["evidence"]:
                sid = evidence["source_id"]
                nodes[sid] = {"id": sid, "kind": "source", "label": evidence["filename"]}
                edges.append({"source": sid, "target": cid, "relation": unit["assessment"]["relation"]})
        return {"release_id": package.release_id, "governance_version": package.governance_version,
                "nodes": list(nodes.values()), "edges": edges, "limit": 100, "scope": "evidence_graph"}
