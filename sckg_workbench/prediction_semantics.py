"""Opt-in source-bound artifact explanation; no execution acceptance.

Files are streamed for identity, but prediction rows/values are never parsed.
"""
from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import time
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, OpenClaim
from .external_evidence import _ReadOnlyKnowledge
from .storage import content_hash
from .workflow_inputs import Digest, Identifier, Label


JSON_LIMIT = 64 * 1024
MANIFEST_LIMIT = 512 * 1024
SCORE_LIMIT = 64 * 1024 * 1024
HEADER_LIMIT = 4096
READ_SECONDS = 15
CATALOG_STATE = "prediction_semantics_catalog"


class PredictionSemanticsError(ValueError):
    pass


class FileReference(Contract):
    relative_path: str = Field(min_length=1, max_length=500)
    sha256: Digest
    manifest_key: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def relative(self):
        path = PurePosixPath(self.relative_path)
        if (path.is_absolute() or "\\" in self.relative_path or ".." in path.parts
                or str(path) != self.relative_path or not path.parts):
            raise ValueError("Only normalized workspace-relative paths are allowed")
        return self


class ArtifactBinding(Contract):
    schema_version: Literal["developer-prediction-artifact-binding-v1"]
    authority: Literal["developer_snapshot_not_execution_acceptance"]
    namespace: str
    run_id: str = Field(min_length=1, max_length=180)
    run_identity_kind: Literal["execution_run_record", "legacy_manifest_slot"]
    manifest: FileReference
    metadata: FileReference
    parameters: FileReference | None
    score: FileReference
    header_sha256: Digest
    delimiter: Literal[",", "\t"]
    score_role: Literal["class_probability_matrix", "maximum_probability_summary", "label_probability_summary", "confidence_unspecified"]


class SourceSpec(Contract):
    source_id: str
    blob_sha256: Digest
    metadata_hash: Digest
    package: Literal["celltypist"]
    version: Literal["1.7.1"]
    original_filename: Literal["models.py", "classifier.py", "annotate.py"]


class ClauseBinding(Contract):
    candidate_id: str
    candidate_hash: Digest
    attribute_index: int = Field(ge=0)
    attribute_hash: Digest
    expected_assertion_kind: Literal["source_assertion", "synthesis"]


class Clause(Contract):
    clause_id: Identifier
    label: Label
    role: Literal["matrix_definition", "best_match", "prob_match", "default_confidence", "voting_confidence", "row_sum"]
    binding: ClauseBinding

    @model_validator(mode="after")
    def synthesis_scope(self):
        if self.binding.expected_assertion_kind == "synthesis" and self.role != "row_sum":
            raise ValueError("Explicit synthesis is limited to the source-traced row-sum clause")
        return self


class PredictionCatalog(Contract):
    schema_version: Literal["development-prediction-semantics-catalog-v1"]
    authority: Literal["developer_source_interpretation_not_human_review"]
    package: Literal["celltypist"]
    version: Literal["1.7.1"]
    sources: list[SourceSpec] = Field(min_length=1, max_length=3)
    clauses: list[Clause] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def distinct(self):
        if (len({s.source_id for s in self.sources}) != len(self.sources)
                or len({c.clause_id for c in self.clauses}) != len(self.clauses)):
            raise ValueError("Catalog identifiers must be distinct")
        return self


def _json(data):
    def distinct(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise PredictionSemanticsError("Duplicate JSON key")
            value[key] = item
        return value
    value = json.loads(data.decode("utf-8"), object_pairs_hook=distinct,
                       parse_constant=lambda _: (_ for _ in ()).throw(PredictionSemanticsError("Nonfinite JSON")))
    if not isinstance(value, dict):
        raise PredictionSemanticsError("Expected a JSON object")
    return value


def _coalesce(value, names, *, casefold=False):
    """Accept an explicit spelling, never conflicting synonymous records."""
    present = [value[name] for name in names if name in value]
    normalized = [(item.casefold() if casefold and isinstance(item, str) else item) for item in present]
    if normalized and any(item != normalized[0] for item in normalized[1:]):
        raise PredictionSemanticsError("Conflicting synonymous metadata fields")
    return present[0] if present else None


def _read(ledger, reference, *, limit, deadline, keep_json=False, header=False):
    """No-follow descriptor traversal; body chunks are hashed, never decoded."""
    root = ledger.workspace.root
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise PredictionSemanticsError("Symlink workspace")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = os.open(root, flags | os.O_DIRECTORY)
    descriptor = None
    try:
        parts = PurePosixPath(reference["relative_path"]).parts
        for part in parts[:-1]:
            next_directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(parts[-1], flags, dir_fd=directory)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise PredictionSemanticsError("Artifact is nonregular or exceeds its byte limit")
        digest, size, retained, first_line = hashlib.sha256(), 0, bytearray(), bytearray()
        header_finished = False
        while True:
            if time.monotonic() > deadline:
                raise PredictionSemanticsError("Artifact identity read exceeded its deadline")
            chunk = os.read(descriptor, min(128 * 1024, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise PredictionSemanticsError("Artifact grew beyond its byte limit")
            digest.update(chunk)
            if keep_json:
                retained.extend(chunk)
            if header and not header_finished:
                prefix, separator, _ = chunk.partition(b"\n")
                first_line.extend(prefix)
                if len(first_line) > HEADER_LIMIT:
                    raise PredictionSemanticsError("Header exceeds its byte limit")
                if separator:
                    first_line.extend(b"\n")
                    if len(first_line) > HEADER_LIMIT:
                        raise PredictionSemanticsError("Header exceeds its byte limit")
                    header_finished = True
        after = os.fstat(descriptor)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after) or digest.hexdigest() != reference["sha256"]:
            raise PredictionSemanticsError("Bound artifact identity changed")
        if header and not header_finished:
            raise PredictionSemanticsError("A complete bounded header is required")
        return bytes(retained), bytes(first_line), size
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


class PredictionSemanticsService:
    def __init__(self, ledger, *, catalog_record_id, expected_catalog_hash):
        self.ledger = ledger
        self.reference = {"record_id": catalog_record_id, "catalog_hash": expected_catalog_hash}
        self.knowledge = _ReadOnlyKnowledge(ledger)

    def binding_ids(self):
        return [r["id"] for r in self.ledger.list_records("prediction_artifact_binding")]

    def _snapshot(self, binding_id):
        with self.ledger.connect() as conn:
            conn.execute("BEGIN")
            if self.ledger.get_state(CATALOG_STATE, conn=conn) != self.reference:
                raise PredictionSemanticsError("Configured catalog selection changed")
            record = self.ledger.get_record(CATALOG_STATE, self.reference["record_id"], conn=conn)
            catalog = PredictionCatalog.model_validate(record["catalog"]).model_dump(mode="json")
            if (record.get("id") != self.reference["record_id"] or record.get("catalog_hash") != content_hash(catalog)
                    or content_hash(catalog) != self.reference["catalog_hash"]):
                raise PredictionSemanticsError("Catalog content changed")
            record = self.ledger.get_record("prediction_artifact_binding", binding_id, conn=conn)
            binding = ArtifactBinding.model_validate(record["binding"]).model_dump(mode="json")
            digest = content_hash(binding)
            if (record.get("id") != binding_id or binding_id != "prediction-artifact-" + digest
                    or record.get("binding_hash") != digest or binding["namespace"] != self.ledger.workspace.namespace):
                raise PredictionSemanticsError("Binding is not the selected immutable workspace snapshot")
            specs = {s["source_id"]: s for s in catalog["sources"]}
            clauses = []
            for clause in catalog["clauses"]:
                bind = clause["binding"]
                candidate = self.ledger.get_record("candidate", bind["candidate_id"], conn=conn)
                if not candidate or candidate.get("status") != "candidate" or self.knowledge._suspended(candidate, conn):
                    raise PredictionSemanticsError("Candidate absent or suspended")
                claim = OpenClaim.model_validate(candidate["claim"]).model_dump(mode="json")
                payload = {"claim": claim, **{k: candidate[k] for k in ("source_ids", "source_revision_ids")}}
                candidate_hash = content_hash(payload)
                if (candidate["id"] != "candidate-" + candidate_hash or candidate["content_hash"] != candidate_hash
                        or candidate_hash != bind["candidate_hash"]
                        or claim["assertion_kind"] != bind["expected_assertion_kind"]):
                    raise PredictionSemanticsError("Candidate identity or explicit assertion kind changed")
                evidence = self.knowledge._anchors(claim, conn)
                if (sorted({e["source_id"] for e in evidence}) != candidate["source_ids"]
                        or sorted({e["source_revision_id"] for e in evidence}) != candidate["source_revision_ids"]):
                    raise PredictionSemanticsError("Source provenance changed")
                for item in evidence:
                    spec = specs.get(item["source_id"])
                    source = self.ledger.get_record("source", item["source_id"], conn=conn)
                    metadata = source["metadata"]
                    if (spec is None or item["blob_sha256"] != spec["blob_sha256"]
                            or content_hash(metadata) != spec["metadata_hash"]
                            or metadata.get("source_kind") != "author_package_source"
                            or metadata.get("package") != catalog["package"]
                            or metadata.get("version") != catalog["version"]
                            or metadata.get("original_filename") != spec["original_filename"]):
                        raise PredictionSemanticsError("Author package/version/source metadata changed")
                index = bind["attribute_index"]
                if index >= len(claim["typed_attributes"]) or content_hash(claim["typed_attributes"][index]) != bind["attribute_hash"]:
                    raise PredictionSemanticsError("Bound source attribute changed")
                clauses.append({**clause, "attribute": deepcopy(claim["typed_attributes"][index]),
                    "source": {"candidate_id": candidate["id"], "candidate_hash": candidate_hash,
                               "claim": claim, "evidence": evidence, "authority": "development_candidate_only"}})
            return {"binding": binding, "catalog": catalog, "clauses": clauses,
                    "governance_version": self.ledger.get_state("governance_version", 0, conn=conn)}

    def explain(self, binding_id):
        try:
            snapshot = self._snapshot(binding_id)
            binding = snapshot["binding"]
            deadline = time.monotonic() + READ_SECONDS
            manifest = _json(_read(self.ledger, binding["manifest"], limit=MANIFEST_LIMIT, deadline=deadline, keep_json=True)[0])
            metadata = _json(_read(self.ledger, binding["metadata"], limit=JSON_LIMIT, deadline=deadline, keep_json=True)[0])
            parameters = (_json(_read(self.ledger, binding["parameters"], limit=JSON_LIMIT, deadline=deadline, keep_json=True)[0])
                          if binding["parameters"] else metadata)
            parameters = parameters.get("parameters", {})
            if not isinstance(parameters, dict):
                raise PredictionSemanticsError("Parameters are not an object")
            _, header, bytes_hashed = _read(self.ledger, binding["score"], limit=SCORE_LIMIT, deadline=deadline, header=True)
            if hashlib.sha256(header).hexdigest() != binding["header_sha256"]:
                raise PredictionSemanticsError("Exact header changed")
            columns = next(csv.reader([header.decode("utf-8").rstrip("\r\n")], delimiter=binding["delimiter"], strict=True))
            if (not 2 <= len(columns) <= 256 or len(set(columns)) != len(columns)
                    or columns[0] != "cell_id" or any(not c or any(ord(x) < 32 for x in c) for c in columns)):
                raise PredictionSemanticsError("Unsupported or duplicate header")
            if binding["score_role"] in {"maximum_probability_summary", "label_probability_summary", "confidence_unspecified"}:
                if columns != ["cell_id", "predicted_label", "confidence"]:
                    raise PredictionSemanticsError("Scalar confidence role does not match header")
            elif columns == ["cell_id", "predicted_label", "confidence"]:
                raise PredictionSemanticsError("Scalar confidence cannot masquerade as a full probability matrix")
            if binding["run_identity_kind"] == "legacy_manifest_slot":
                runs = manifest.get("runs")
                if not isinstance(runs, list) or any(not isinstance(row, dict) for row in runs):
                    raise PredictionSemanticsError("Legacy manifest runs must be objects")
                selected = [r for r in runs if r.get("slot") == binding["run_id"]]
                if len(selected) != 1 or selected[0].get("prediction") != binding["score"]["manifest_key"]:
                    raise PredictionSemanticsError("Original legacy run selection changed")
                hashes = manifest.get("output_hashes", {})
            else:
                if manifest.get("run_id") != binding["run_id"]:
                    raise PredictionSemanticsError("Original run identity differs")
                hashes = manifest.get("artifact_hashes", {})
            if not isinstance(hashes, dict):
                raise PredictionSemanticsError("Manifest hashes must be an object")
            for ref in [binding["metadata"], binding["score"], *([binding["parameters"]] if binding["parameters"] else [])]:
                if hashes.get(ref["manifest_key"]) != ref["sha256"]:
                    raise PredictionSemanticsError("Original manifest does not bind this artifact")
            tool = _coalesce(metadata, ("tool_name", "method"), casefold=True)
            if not isinstance(tool, str) or tool.casefold() != "celltypist":
                raise PredictionSemanticsError("Artifact is not recorded as CellTypist")
            version = _coalesce(metadata, ("tool_version", "celltypist_version"))
            version = version if isinstance(version, str) and len(version) <= 40 else None
            mode_fields = {key: metadata[key] for key in ("mode", "prediction_mode") if key in metadata}
            if "mode" in parameters:
                mode_fields["parameter_mode"] = parameters["mode"]
            mode = _coalesce(mode_fields, ("mode", "prediction_mode", "parameter_mode"))
            mode = mode if mode in ("best match", "prob match") else None
            observed_label = _coalesce(metadata, ("selected_label_column", "label_column"))
            observed_label = observed_label if observed_label in ("predicted_labels", "majority_voting") else None
            voting = parameters.get("majority_voting")
            voting = voting if type(voting) is bool else None
            unknowns = [key for key, value in {"tool_version": version, "prediction_mode": mode,
                         "selected_label_column": observed_label, "voting_requested": voting}.items() if value is None]
            insertion = metadata.get("confidence_insert_conf")
            insertion = insertion if type(insertion) is bool else None
            if insertion is None and any(c["role"] == "voting_confidence" for c in snapshot["clauses"]):
                unknowns.append("confidence_insert_conf")
            clauses = []
            for clause in snapshot["clauses"]:
                role = clause["role"]
                supported = version == snapshot["catalog"]["version"]
                if role in ("matrix_definition", "row_sum"):
                    supported &= binding["score_role"] == "class_probability_matrix"
                elif role in ("best_match", "prob_match"):
                    supported &= mode == ("best match" if role == "best_match" else "prob match") and observed_label == "predicted_labels"
                elif role == "default_confidence":
                    supported &= binding["score_role"] == "maximum_probability_summary"
                else:
                    supported &= (binding["score_role"] == "label_probability_summary"
                                  and observed_label == "majority_voting"
                                  and insertion is True
                                  and metadata.get("confidence_insert_conf_by") == "majority_voting")
                clauses.append({**clause, "applies_to_this_artifact": bool(supported),
                    "scope": "source_definition_matches_recorded_artifact_role" if supported else "conditional_reference_not_established_for_this_artifact"})
            # Reopen/hash every selected file and recheck current catalog/source
            # state. A source/selection/file change must invalidate this result.
            for key, limit in [("manifest", MANIFEST_LIMIT), ("metadata", JSON_LIMIT), ("parameters", JSON_LIMIT), ("score", SCORE_LIMIT)]:
                if binding[key] is not None:
                    _read(self.ledger, binding[key], limit=limit, deadline=deadline)
            if self._snapshot(binding_id) != snapshot:
                raise PredictionSemanticsError("Source/catalog snapshot changed during explanation")
            result = {"schema_version": "development-prediction-explanation-v1",
                "authority": "developer_snapshot_not_execution_acceptance", "binding_id": binding_id,
                "binding_hash": content_hash(binding), "catalog_hash": self.reference["catalog_hash"],
                "run_id": binding["run_id"], "run_identity_kind": binding["run_identity_kind"],
                "status": "identity_valid_semantics_supported" if any(c["applies_to_this_artifact"] for c in clauses) else "identity_valid_semantics_unresolved",
                "artifact_facts": {"tool_name_recorded": tool, "tool_version_recorded": version,
                    "prediction_mode_recorded": mode, "voting_requested": voting,
                    "selected_label_column_recorded": observed_label, "header_columns": columns,
                    "confidence_insertion_recorded": insertion,
                    "score_role_declared_by_developer_binding": binding["score_role"],
                    "score_sha256": binding["score"]["sha256"], "header_sha256": binding["header_sha256"],
                    "raw_calibration_declaration": metadata.get("confidence_is_calibrated")},
                "clauses": clauses, "unknowns": unknowns, "calibration_status": "not_established",
                "report_origin": "existing_artifact_metadata_not_independent_scientific_measurement",
                "source_semantics_reassessed": False,
                "to_adata_call_verification": "not_established_by_definition_matching",
                "identity_io": {"full_score_bytes_hashed": bytes_hashed * 2, "score_hash_passes": 2,
                    "per_cell_rows_parsed": 0, "purpose": "identity_only_not_scoring"},
                "recommendation_eligible": False, "execution_authorized": False,
                "scientific_truth_verified": False, "provider_calls": 0, "fits": 0}
            return {**result, "result_hash": content_hash(result)}
        except (OSError, ValueError, KeyError, TypeError, StopIteration, csv.Error) as error:
            raise PredictionSemanticsError("Prediction preview unavailable; bound files or sources did not pass read-only checks") from error


def configured_prediction_semantics_service(ledger):
    reference = ledger.get_state(CATALOG_STATE)
    if reference is None:
        return None
    if not isinstance(reference, dict) or set(reference) != {"record_id", "catalog_hash"}:
        raise PredictionSemanticsError("Invalid configured prediction catalog")
    return PredictionSemanticsService(ledger, catalog_record_id=reference["record_id"],
                                      expected_catalog_hash=reference["catalog_hash"])
