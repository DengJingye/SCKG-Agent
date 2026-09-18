"""Marker annotation delivery, not label inference or scientific evidence acquisition.

The Notebook kernel uses only the stdlib part of this module. The already-running
application's Python validates metadata with the existing annotation service. No
matrix, credentials, network request or execution authorization crosses that boundary.
Reviewed evidence must be supplied explicitly; an absent bundle creates a review packet.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def index_hash(values):
    return hashlib.sha256("\n".join(map(str, values)).encode()).hexdigest()


def matrix_hash(matrix):
    """Integrity fingerprint only; no normalization, conversion of scientific state or fitting."""
    import numpy as np
    from scipy import sparse
    h = hashlib.sha256(str(matrix.shape).encode())
    arrays = [matrix]
    if sparse.issparse(matrix):
        csr = matrix.tocsr()
        arrays = [csr.indptr, csr.indices, csr.data]
    for values in arrays:
        array = np.ascontiguousarray(values)
        h.update(str(array.dtype).encode())
        h.update(memoryview(array).cast("B"))
    return h.hexdigest()


def marker_state(adata):
    """Observe actual groupby/markers; never infer a label from dataset identity."""
    markers = adata.uns.get("rank_genes_groups", {})
    params = markers.get("params", {})
    groupby = str(params.get("groupby", ""))
    if not groupby or groupby not in adata.obs:
        raise ValueError("marker_groupby_missing")
    if adata.obs[groupby].isna().any():
        raise ValueError("cluster_identity_missing")
    groups = list(dict.fromkeys(map(str, adata.obs[groupby])))
    names = markers.get("names")
    fields = list(getattr(getattr(names, "dtype", None), "names", None) or [])
    if not fields or set(fields) != set(groups):
        raise ValueError("marker_cluster_group_mismatch")
    layer = params.get("layer")
    if layer:
        if layer not in adata.layers:
            raise ValueError("marker_expression_layer_missing")
        expression, gene_names = adata.layers[layer], adata.var_names
    elif params.get("use_raw"):
        if adata.raw is None:
            raise ValueError("marker_raw_expression_missing")
        expression, gene_names = adata.raw.X, adata.raw.var_names
    else:
        expression, gene_names = adata.X, adata.var_names
    universe = set(map(str, gene_names))
    ranked = {group: [str(x) for x in names[group]] for group in fields}
    if any(not genes or any(g not in universe for g in genes) for genes in ranked.values()):
        raise ValueError("marker_gene_identity_mismatch")
    # Bind every marker output, including statistics/parameters, not just a key's existence.
    def plain(value):
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if hasattr(value, "tolist"):
            return plain(value.tolist())
        if isinstance(value, (tuple, list)):
            return [plain(v) for v in value]
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return str(value)
        return value
    return {
        "groupby": groupby, "clusters": groups, "markers": ranked,
        "cell_index_hash": index_hash(adata.obs_names),
        "gene_index_hash": index_hash(adata.var_names),
        "marker_feature_index_hash": index_hash(gene_names),
        "marker_expression_hash": matrix_hash(expression),
        "cluster_assignment_hash": digest(list(map(str, adata.obs[groupby]))),
        "marker_result_hash": digest(plain(markers)),
    }


def checked_binding(item, state, base_dir):
    """Resolve source bytes, exact span and human-reviewed candidate association.

    This is integrity validation of supplied evidence, not automated scientific review.
    The human acceptance covers candidate + scope + dataset/marker identity + source tuple.
    """
    from core.annotation_method_models import MarkerEvidenceCandidate
    from core.scientific_knowledge_conformance_models import ReviewDecision, ApplicabilityScope

    candidate = MarkerEvidenceCandidate.model_validate(item["candidate"])
    ApplicabilityScope.model_validate(item["scope"])
    if candidate.cluster_id not in state["clusters"] or not set(candidate.marker_genes) <= set(state["markers"][candidate.cluster_id]):
        raise ValueError("candidate_marker_cluster_mismatch")
    if item["context_hash"] != digest(state):
        raise ValueError("candidate_context_stale_or_misaligned")
    sources = item["sources"]
    if not sources or set(candidate.evidence_source_ids) != {s["source_id"] for s in sources}:
        raise ValueError("candidate_source_binding_mismatch")
    for source in sources:
        if not source["source_revision_id"] or not source["span_id"]:
            raise ValueError("evidence_identity_missing")
        path = (base_dir / source["path"]).resolve()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("source_integrity_mismatch")
        text = raw.decode("utf-8")
        start, end = source["start"], source["end"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
            raise ValueError("evidence_locator_invalid")
        quote = text[start:end]
        if quote != source["quote"] or hashlib.sha256(quote.encode()).hexdigest() != source["span_sha256"]:
            raise ValueError("evidence_span_mismatch")
    # Paths are resolution hints; the reviewed payload includes them as well as all hashes.
    reviewed = {k: item[k] for k in ("binding_id", "candidate", "scope", "context_hash", "sources")}
    review = ReviewDecision.model_validate(item["review"])
    if (review.decision != "accepted" or review.reviewer_type not in {"qualified_human", "designated_owner"}
            or item["binding_id"] not in review.reviewed_record_ids
            or digest(reviewed) not in review.reviewed_artifact_hashes):
        raise ValueError("candidate_evidence_human_review_required")
    return candidate


def evaluate(request):
    """Application-side metadata validation; reuse the existing method-family service."""
    from core.representation_models import RepresentationRecord
    from engine.annotation_method_service import AnnotationMethodFamilyService

    state = request.get("state")
    reasons = list(request.get("reasons", []))
    record = None
    if request.get("marker_record"):
        record = RepresentationRecord.model_validate(request["marker_record"])
    if state and (record is None or not record.validated or record.status != "current"
                  or record.cell_index_hash != state["cell_index_hash"]
                  or record.gene_index_hash != state["gene_index_hash"]):
        reasons.append("marker_record_stale_or_identity_mismatch")
    if state and record:
        if (record.metadata.get("groupby", state["groupby"]) != state["groupby"]
                or record.metadata.get("marker_result_hash", state["marker_result_hash"]) != state["marker_result_hash"]):
            reasons.append("marker_record_metadata_mismatch")
    candidates = []
    for item in request.get("bindings", []):
        try:
            candidates.append(checked_binding(item, state, Path(request["evidence_base"])))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reasons.append(f"invalid_candidate_evidence:{type(exc).__name__}:{exc}")
    if reasons:
        candidates = []  # Do not silently discard a bad binding and call the set complete.
    result = AnnotationMethodFamilyService().marker_evidence_candidates(
        marker_record=record, evidence_candidates=candidates,
    ).model_dump(mode="json")
    reasons.extend(result["blocking_reasons"])
    covered = {item["cluster_id"] for item in result["candidates"]}
    if state and covered != set(state["clusters"]):
        reasons.append("annotation_cluster_coverage_incomplete")
    satisfied = bool(result["candidates"]) and result["eligible_for_confirmation"] and not reasons
    return {"schema_version": "annotation-delivery-v1", "result": result,
            "annotation_candidates_satisfied": satisfied,
            "confirmed_annotation_satisfied": False,
            "status": "WAITING_FOR_USER_CONFIRMATION" if satisfied else "BLOCKED",
            "missing_requirements": sorted(set(reasons)),
            "automatic_marker_calculation_complete": state is not None,
            "human_confirmation_required": True, "execution_request_count": 0}


def invoke_service(request, application_python):
    completed = subprocess.run(
        [str(application_python), str(Path(__file__).resolve()), "--metadata-worker"],
        input=json.dumps(request), text=True, capture_output=True, timeout=60,
        cwd=Path(__file__).resolve().parents[1], check=True,
    )
    return json.loads(completed.stdout)


def write_json(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


class AnnotationDeliverySession:
    """One Notebook run, one immutable delivery directory; never overwrites inputs."""

    def __init__(self, adata, *, ledger, input_path, output_dir, application_python, plan_id):
        self.input_path = Path(input_path)
        self.input_hash = file_hash(self.input_path)
        self.output_dir = Path(output_dir) / f"annotation-{uuid.uuid4().hex}"
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.application_python = application_python
        self.plan_id = plan_id
        self.anchor = None
        self.record = None
        self.initial_reasons = []
        self.delivery = None
        if ledger and ledger.get("source_hash") != self.input_hash:
            self.initial_reasons.append("registered_input_hash_mismatch")
        records = [r for r in (ledger or {}).get("records", []) if r["representation_id"] == "marker_result"]
        if records:
            try:
                self.anchor = marker_state(adata)
                self.record = next((r for r in records if r["slot"] == "uns/rank_genes_groups"), None)
                clusters = [r for r in ledger["records"] if r["representation_id"] == "cluster_labels"
                            and r["slot"] == "obs/" + self.anchor["groupby"]
                            and r["status"] == "current" and r["validated"]
                            and r["cell_index_hash"] == self.anchor["cell_index_hash"]]
                if not clusters or not self.record or not set(self.record["parent_record_ids"]) & {r["representation_record_id"] for r in clusters}:
                    self.initial_reasons.append("marker_cluster_lineage_mismatch")
            except ValueError as exc:
                self.initial_reasons.append(str(exc))

    def record_computed_markers(self, adata):
        """Called only immediately after the actual rank_markers producer succeeds."""
        self.anchor = marker_state(adata)
        self.record = {
            "representation_record_id": "annotation-run:markers:" + digest(self.anchor)[:16],
            "representation_id": "marker_result", "schema_version": "1.0",
            "value_state": "table", "slot": "uns/rank_genes_groups",
            "cell_index_hash": self.anchor["cell_index_hash"],
            "gene_index_hash": self.anchor["gene_index_hash"],
            "validated": True, "status": "current", "parent_record_ids": [],
            "provenance": ["notebook_rank_markers_completed"],
            "metadata": {"groupby": self.anchor["groupby"], "marker_result_hash": self.anchor["marker_result_hash"]},
        }

    def deliver(self, adata, evidence_bundle=None):
        if self.delivery is not None:
            raise ValueError("annotation_delivery_already_written")
        reasons = list(self.initial_reasons)
        state = None
        try:
            state = marker_state(adata)
            if state != self.anchor:
                reasons.append("marker_state_stale_or_unvalidated")
        except ValueError as exc:
            reasons.append(str(exc))
        bindings, base = [], self.output_dir
        if evidence_bundle:
            base = Path(evidence_bundle).resolve().parent
            try:
                bindings = json.loads(Path(evidence_bundle).read_text())["bindings"]
            except (OSError, ValueError, KeyError) as exc:
                reasons.append(f"evidence_bundle_unresolvable:{type(exc).__name__}")
        request = {"state": state, "marker_record": self.record, "reasons": reasons,
                   "bindings": bindings, "evidence_base": str(base)}
        write_json(self.output_dir / "request.json", request)
        write_json(self.output_dir / "marker_review_packet.json", {
            "artifact_kind": "marker_cluster_review_packet", "is_annotation_candidates": False,
            "state": state, "candidate_labels": None, "review_decision": None,
        })
        try:
            delivery = invoke_service(request, self.application_python)
        except (subprocess.SubprocessError, OSError, ValueError):
            delivery = {"status": "FAILED", "annotation_candidates_satisfied": False,
                        "confirmed_annotation_satisfied": False,
                        "missing_requirements": ["annotation_metadata_service_failed"], "result": None}
        delivery.update(plan_id=self.plan_id, input_sha256=self.input_hash,
                        state_hash=digest(state), request_sha256=file_hash(self.output_dir / "request.json"))
        write_json(self.output_dir / "delivery.json", delivery)
        if (delivery.get("result") or {}).get("candidates"):
            write_json(self.output_dir / "annotation_candidates.json", delivery["result"])
            # JSON string is h5ad round-trip safe and retains the existing full schema.
            adata.uns["annotation_candidates"] = {"schema_version": "annotation-delivery-v1",
                "result_json": json.dumps(delivery["result"], sort_keys=True),
                "state_hash": digest(state), "delivery_path": str(self.output_dir)}
        self.delivery = delivery
        return delivery

    def finish(self, adata, *, require_confirmation=False):
        terminal = validate_delivery(self.output_dir, application_python=self.application_python)
        if terminal["annotation_candidates_satisfied"]:
            try:
                slot = adata.uns["annotation_candidates"]
                if (json.loads(slot["result_json"]) != terminal["result"]
                        or slot["state_hash"] != self.delivery["state_hash"]):
                    raise ValueError("annotation_slot_content_mismatch")
            except (KeyError, ValueError, TypeError):
                terminal["annotation_candidates_satisfied"] = False
                terminal["missing_requirements"].append("annotation_slot_content_mismatch")
        try:
            current_state = marker_state(adata)
            if digest(current_state) != (self.delivery or {}).get("state_hash"):
                terminal["annotation_candidates_satisfied"] = False
                terminal["missing_requirements"].append("marker_state_changed_after_delivery")
        except ValueError as exc:
            terminal["annotation_candidates_satisfied"] = False
            terminal["missing_requirements"].append(str(exc))
        if file_hash(self.input_path) != self.input_hash:
            terminal["annotation_candidates_satisfied"] = False
            terminal["missing_requirements"].append("input_hash_changed")
        terminal["required_annotation_target_satisfied"] = terminal["annotation_candidates_satisfied"] and not require_confirmation
        if require_confirmation:
            terminal["missing_requirements"].append("explicit_human_confirmation_required")
        terminal["full_scientific_task_completed"] = False  # this validator covers annotation, not the whole DAG
        write_json(self.output_dir / "terminal_validation.json", terminal)
        print(json.dumps(terminal, indent=2))
        if not terminal["required_annotation_target_satisfied"]:
            raise RuntimeError("ANNOTATION_TERMINAL_INCOMPLETE: " + "; ".join(terminal["missing_requirements"]))
        return terminal


def validate_delivery(output_dir, *, application_python):
    """Re-open all metadata and evidence; review packets/empty lists are never success."""
    output_dir = Path(output_dir)
    try:
        delivery = json.loads((output_dir / "delivery.json").read_text())
        request = json.loads((output_dir / "request.json").read_text())
        if file_hash(output_dir / "request.json") != delivery["request_sha256"]:
            raise ValueError("delivery_request_integrity_mismatch")
        checked = invoke_service(request, application_python)
        if checked["result"] != delivery["result"]:
            raise ValueError("delivery_candidate_binding_mismatch")
        if checked["result"]["candidates"]:
            persisted = json.loads((output_dir / "annotation_candidates.json").read_text())
            if persisted != checked["result"]:
                raise ValueError("persisted_candidate_set_mismatch")
        return checked
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return {"status": "FAILED", "annotation_candidates_satisfied": False,
                "confirmed_annotation_satisfied": False,
                "missing_requirements": [f"delivery_validation_failed:{type(exc).__name__}:{exc}"]}


def pending_confirmation(output_dir, plan_id):
    """A human-review-only plan cannot succeed simply because its cell executed."""
    path = Path(output_dir) / f"human-confirmation-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / "terminal_validation.json", {
        "plan_id": plan_id, "status": "WAITING_FOR_USER_CONFIRMATION",
        "confirmed_annotation_satisfied": False, "required_annotation_target_satisfied": False,
        "full_scientific_task_completed": False, "execution_request_count": 0,
        "missing_requirements": ["explicit_human_confirmation_required"],
        "review_decision": None,
    })
    raise RuntimeError("ANNOTATION_TERMINAL_INCOMPLETE: explicit_human_confirmation_required")


if __name__ == "__main__":
    if sys.argv[1:] != ["--metadata-worker"]:
        raise SystemExit("Only --metadata-worker is supported")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    print(json.dumps(evaluate(json.load(sys.stdin))))
