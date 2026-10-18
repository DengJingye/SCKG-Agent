"""Audited imports from an external interactive model session, never API receipts.

Prepare a run BEFORE giving its input_snapshot to an external agent. Import that
agent's exact JSON with the returned input_hash. This records declared session
provenance, not a cryptographically authenticated provider response. No API
credentials, fabricated token/cost figures, human decisions or releases are made.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field

from .catalog import Catalog
from .contracts import Contract, ExtractionOutput, SemanticAssessment
from .extraction_coverage import build_extraction_scope, validate_extraction_coverage
from .knowledge import KnowledgeError, KnowledgeService
from .storage import canonical_json, content_hash, new_id, utcnow


class ExternalProfile(Contract):
    schema_version: Literal["external-session-profile-v1"] = "external-session-profile-v1"
    name: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    model_variant: str | None = None
    runtime: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    identity_evidence: str = Field(min_length=1)


class ExternalAssessmentItem(Contract):
    candidate_id: str = Field(min_length=1)
    assessment: SemanticAssessment


class ExternalAssessmentOutput(Contract):
    assessments: list[ExternalAssessmentItem] = Field(min_length=1, max_length=100)


class ExternalIngestionService:
    """A separate session/run namespace with the existing knowledge governance."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.catalog = Catalog(ledger)
        self.knowledge = KnowledgeService(ledger)

    def create_profile(self, **fields):
        value = ExternalProfile.model_validate(fields).model_dump(mode="json")
        for field in ("name", "model_family", "runtime", "session_id", "identity_evidence"):
            if not value[field].strip():
                raise ValueError(f"{field} must be nonblank")
        profile_id = "external-profile-" + content_hash(value)
        with self.ledger.transaction() as conn:
            existing = self.ledger.get_record("external_model_profile", profile_id, conn=conn)
            if existing:
                return existing
            record = {"id": profile_id, **value, "created_at": utcnow(),
                      "attribution": "declared_external_session", "provider_receipt_available": False}
            self.ledger.put_record("external_model_profile", profile_id, record, conn=conn)
            self.ledger.append_event("external_model_profile_registered", profile_id,
                                     {"attribution": record["attribution"]}, conn=conn)
        return record

    @staticmethod
    def _ids(values, label):
        if (not isinstance(values, list) or not values or
                any(not isinstance(v, str) or not v.strip() for v in values) or
                len(values) != len(set(values))):
            raise ValueError(f"{label} requires a nonempty list of distinct IDs")
        return values

    def _source_snapshot(self, source_id, *, conn):
        source = self.catalog._material(source_id, conn=conn)
        self.catalog._assert_development_allowed(source, conn=conn)
        return {key: source[key] for key in ("id", "source_revision_id", "blob_sha256", "snapshot_id")}

    def _prepare(self, purpose, snapshot, *, profile_id, agent_id, instructions, conn):
        profile = self.knowledge._required("external_model_profile", profile_id, conn)
        if (not isinstance(agent_id, str) or not agent_id.strip() or
                not isinstance(instructions, str) or not instructions.strip()):
            raise ValueError("An explicit agent identity and actual instructions are required")
        snapshot = {"schema_version": "external-session-input-v1", "purpose": purpose,
                    "namespace": self.ledger.workspace.namespace, "instructions": instructions, **snapshot}
        run_id = new_id("external-run")
        run = {"id": run_id, "schema_version": "external-session-run-v1", "purpose": purpose,
               "external_profile_id": profile_id, "profile_snapshot": profile,
               "agent_id": agent_id, "input_snapshot": snapshot, "input_hash": content_hash(snapshot),
               "created_at": utcnow(), "usage_known": False, "usage": None,
               "cost_known": False, "cost_usd": None, "provider_receipt_available": False}
        self.ledger.put_record("external_model_run", run_id, run, conn=conn)
        families = self.catalog._known_families(conn=conn)
        for source in snapshot["sources"]:
            reason = "external_session_" + purpose
            record_id = "development-use-" + content_hash([source["id"], run_id, reason])
            exposure = {"id": record_id, "source_id": source["id"], "run_id": run_id,
                        "run_kind": "external_model_run", "reason": reason,
                        "source_revision_id": source["source_revision_id"],
                        "blob_sha256": source["blob_sha256"], "work_family": families.get(source["id"]),
                        "created_at": utcnow()}
            self.ledger.put_record("development_use", record_id, exposure, conn=conn)
            self.ledger.append_event("development_use_registered", source["id"],
                                     {"record_id": record_id, "run_id": run_id, "reason": reason}, conn=conn)
        self.ledger.append_event("external_run_prepared", run_id,
                                 {"purpose": purpose, "input_hash": run["input_hash"]}, conn=conn)
        return run

    def prepare_extraction(self, source_ids, *, profile_id, agent_id, instructions, ir_ids=None,
                           required_blocks=None):
        self._ids(source_ids, "source_ids")
        if ir_ids is not None:
            self._ids(ir_ids, "ir_ids")
        with self.ledger.transaction() as conn:
            sources = [self._source_snapshot(sid, conn=conn) for sid in source_ids]
            all_irs = (self.ledger.list_records("document_ir", conn=conn) if ir_ids is None else
                       [self.knowledge._required("document_ir", iid, conn) for iid in ir_ids])
            selected = [ir for ir in all_irs if ir["source_id"] in source_ids]
            if len(selected) != len(source_ids) or {ir["source_id"] for ir in selected} != set(source_ids):
                raise ValueError("Select exactly one parsed document IR per source; pass explicit ir_ids if ambiguous")
            if ir_ids is not None and len(selected) != len(ir_ids):
                raise ValueError("Every selected IR must belong to an input source")
            documents = []
            for source in sources:
                ir = next(ir for ir in selected if ir["source_id"] == source["id"])
                if ir["source_revision_id"] != source["source_revision_id"]:
                    raise ValueError("Parsed input revision differs from source")
                documents.append({"source_id": source["id"], "document": ir, "document_hash": content_hash(ir)})
            snapshot = {"sources": sources, "documents": documents}
            if required_blocks is not None:
                snapshot["coverage_scope"] = build_extraction_scope(documents, required_blocks)
            return self._prepare("extraction", snapshot,
                                 profile_id=profile_id, agent_id=agent_id, instructions=instructions, conn=conn)

    def prepare_assessment(self, candidate_ids, *, profile_id, agent_id, instructions):
        self._ids(candidate_ids, "candidate_ids")
        if len(candidate_ids) > 100:
            raise ValueError("At most 100 assessments per external run")
        with self.ledger.transaction() as conn:
            candidates = [self.knowledge._required("candidate", cid, conn) for cid in candidate_ids]
            source_ids = sorted({sid for candidate in candidates for sid in candidate["source_ids"]})
            sources = [self._source_snapshot(sid, conn=conn) for sid in source_ids]
            cases = [{"candidate_id": c["id"], "candidate_hash": c["content_hash"],
                      "previous_assessment_id": self.ledger.get_state("assessment:" + c["id"], conn=conn),
                      "input": self.knowledge.assessment_input(c["id"], conn=conn)} for c in candidates]
            return self._prepare("assessment", {"sources": sources, "cases": cases},
                                 profile_id=profile_id, agent_id=agent_id, instructions=instructions, conn=conn)

    @staticmethod
    def _output(output, contract):
        if isinstance(output, str):
            raw = output
            parsed = json.loads(raw)
            serialization = "supplied_json_text"
        elif isinstance(output, dict):
            parsed = output
            raw = canonical_json(output)
            serialization = "canonicalized_supplied_object"
        else:
            raise ValueError("Output must be the supplied JSON string or object")
        validated = contract.model_validate(parsed).model_dump(mode="json")
        return validated, {"raw_json": raw, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                           "serialization": serialization, "parsed_output": parsed,
                           "parsed_output_hash": content_hash(parsed)}

    def _check_run(self, run_id, purpose, expected_input_hash, *, conn):
        run = self.knowledge._required("external_model_run", run_id, conn)
        if run["purpose"] != purpose or run["input_hash"] != expected_input_hash:
            raise ValueError("External output must bind the exact run purpose and input hash")
        if (content_hash(run["input_snapshot"]) != expected_input_hash or
                run["input_snapshot"]["namespace"] != self.ledger.workspace.namespace):
            raise ValueError("External input snapshot integrity failure")
        if run["profile_snapshot"] != self.knowledge._required("external_model_profile", run["external_profile_id"], conn):
            raise ValueError("External profile snapshot mismatch")
        for source in run["input_snapshot"]["sources"]:
            if source != self._source_snapshot(source["id"], conn=conn):
                raise ValueError("External source snapshot mismatch")
        return run

    def _existing(self, run_id, output, *, conn):
        existing = self.ledger.get_record("external_model_output", run_id, conn=conn)
        if existing is not None and existing["raw_sha256"] != output["raw_sha256"]:
            raise ValueError("Run already has a different immutable output; prepare a new run")
        return existing

    def _save_output(self, run, output, **result):
        return {"id": run["id"], "schema_version": "external-session-output-v1", **output, **result,
                "input_hash": run["input_hash"], "external_profile_id": run["external_profile_id"],
                "origin_kind": "external_session", "agent_id": run["agent_id"], "created_at": utcnow(),
                "import_status": "validated_candidate_output", "usage_known": False, "usage": None,
                "cost_known": False, "cost_usd": None, "provider_receipt_available": False,
                "authority": "external_model_judgment_not_human_review"}

    def import_extraction(self, run_id, output, *, expected_input_hash, coverage=None):
        value, receipt = self._output(output, ExtractionOutput)
        with self.ledger.transaction() as conn:
            run = self._check_run(run_id, "extraction", expected_input_hash, conn=conn)
            coverage_record = validate_extraction_coverage(
                run["input_snapshot"].get("coverage_scope"), value, coverage)
            existing = self._existing(run_id, receipt, conn=conn)
            if existing:
                if existing.get("block_accounting") != coverage_record:
                    raise ValueError("Run already has different immutable block accounting")
                return existing
            documents = run["input_snapshot"]["documents"]
            ir_ids = {row["document"]["id"] for row in documents}
            for row in documents:
                actual = self.knowledge._required("document_ir", row["document"]["id"], conn)
                if actual != row["document"] or content_hash(actual) != row["document_hash"]:
                    raise ValueError("External extraction document snapshot mismatch")
            candidate_ids = []
            origin = {"kind": "external_session", "run_id": run_id,
                      "external_profile_id": run["external_profile_id"], "agent_id": run["agent_id"],
                      "input_hash": run["input_hash"], "output_hash": receipt["parsed_output_hash"]}
            for claim in value["units"]:
                if any(a["ir_id"] not in ir_ids for a in claim["anchors"]):
                    raise KnowledgeError("Claim cites material outside the prepared external input")
                candidate = self.knowledge._store_candidate(claim, origin, conn=conn)
                candidate_ids.append(candidate["id"])
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("Repeated identical candidates in one extraction output")
            record = self._save_output(run, receipt, candidate_ids=candidate_ids, gaps=value["gaps"],
                                       source_summary=value["source_summary"])
            if coverage_record is not None:
                record["block_accounting"] = coverage_record
            self.ledger.put_record("external_model_output", run_id, record, conn=conn)
            self.ledger.append_event("external_extraction_imported", run_id,
                                     {"candidate_ids": candidate_ids, "output_hash": receipt["parsed_output_hash"]}, conn=conn)
        return record

    def import_assessments(self, run_id, output, *, expected_input_hash):
        value, receipt = self._output(output, ExternalAssessmentOutput)
        with self.ledger.transaction() as conn:
            run = self._check_run(run_id, "assessment", expected_input_hash, conn=conn)
            existing = self._existing(run_id, receipt, conn=conn)
            if existing:
                return existing
            cases = {case["candidate_id"]: case for case in run["input_snapshot"]["cases"]}
            ids = [row["candidate_id"] for row in value["assessments"]]
            if len(ids) != len(set(ids)) or set(ids) != set(cases):
                raise ValueError("Assessment output must cover each prepared candidate exactly once")
            assessment_ids = []
            for row in value["assessments"]:
                cid, case = row["candidate_id"], cases[row["candidate_id"]]
                candidate = self.knowledge._required("candidate", cid, conn)
                if (candidate["content_hash"] != case["candidate_hash"] or
                        self.knowledge.assessment_input(cid, conn=conn) != case["input"]):
                    raise ValueError("External assessment no longer binds exact candidate and evidence")
                if self.ledger.get_state("assessment:" + cid, conn=conn) != case["previous_assessment_id"]:
                    raise ValueError("Assessment changed while external run was open; prepare a new run")
                aid = "external-assessment-" + content_hash([run_id, cid])
                assessment = {"id": aid, "candidate_id": cid, "candidate_hash": candidate["content_hash"],
                              "result": row["assessment"], "run_id": run_id, "profile_id": None, "call_id": None,
                              "origin_kind": "external_session", "external_profile_id": run["external_profile_id"],
                              "external_output_id": run_id, "input_hash": run["input_hash"],
                              "output_hash": receipt["parsed_output_hash"], "agent_id": run["agent_id"],
                              "authority": "external_model_judgment_not_human_review", "created_at": utcnow()}
                self.ledger.put_record("assessment", aid, assessment, conn=conn)
                self.ledger.set_state("assessment:" + cid, aid, conn=conn)
                self.knowledge._bump_governance(conn)
                self.ledger.append_event("candidate_assessed", cid,
                                         {"assessment_id": aid, "origin_kind": "external_session"}, conn=conn)
                assessment_ids.append(aid)
            record = self._save_output(run, receipt, assessment_ids=assessment_ids)
            self.ledger.put_record("external_model_output", run_id, record, conn=conn)
            self.ledger.append_event("external_assessments_imported", run_id,
                                     {"assessment_ids": assessment_ids, "output_hash": receipt["parsed_output_hash"]}, conn=conn)
        return record
