"""Serialize an already validated preview snapshot; no file, queue or tool access."""
import hashlib
import io
import zipfile

from .storage import canonical_json, content_hash


EXPORT_SCHEMA = "sckg-preview-export-v1"
MAX_EXPORT_BYTES = 1024 * 1024


def build_result_export(*, summary, task, run, binding):
    """Internal projection called only after AnalysisService's integrity checks."""
    summary_bytes = (canonical_json(summary) + "\n").encode("utf-8")
    missing = {name: "not_recorded_in_analysis_receipt" for name in (
        "parent_run_id", "code_sha", "model_actual_identity", "model_config_hash",
        "prompt_hash", "corpus_snapshot", "index_hash", "tool_registry_hash")}
    lineage = binding["lineage"]
    manifest = {
        "schema_version": EXPORT_SCHEMA,
        "authority": "preview_engineering_only",
        "scientific_claim_allowed": False,
        "computation_performed_by_export": False,
        "task_id": task["task_id"], "attempt": task["attempt"],
        "run_id": run.run_id, "status": task["status"],
        **{name: None for name in missing}, "missing_provenance": missing,
        "reproduction_complete": False,
        "dataset_hash": lineage["source_hash"], "preview_hash": run.input_hash,
        "dataset_origin": summary["dataset_origin"],
        "dataset_origin_verification": summary["dataset_origin_verification"],
        "scientific_truth_verified": False,
        "tool": {"name": run.tool_name, "version": run.tool_version,
                 "contract_digest": lineage["tool_contract_digest"]},
        "execution_seed": run.execution_seed,
        "parameters": run.parameters, "parameter_hash": lineage["parameter_hash"],
        "environment": {"id": run.environment_id, "digest": lineage["environment_digest"]},
        "notebook_hash": lineage["notebook_hash"],
        "step_template_digest": lineage["step_template_digest"],
        "budget": task["budget"], "usage": task["usage"], "budget_status": task["budget_status"],
        "usage_scope": "analysis_task_only_not_parent_conversation",
        "validation": summary["validation"],
        "receipt_hashes": {name: binding[name] for name in (
            "analysis_result_digest", "preparation_digest", "execution_run_digest",
            "store_result_sha256", "store_sidecar_sha256", "axis_ids_sha256")},
        "original_artifact_hashes": {name: run.artifact_hashes[name] for name in (
            "doublet_results.tsv", "parameters.json", "result_metadata.json")},
        "files": {"result_summary.json": hashlib.sha256(summary_bytes).hexdigest()},
        "contents": "Aggregate summary and recorded provenance; raw inputs, cell rows, environment and executable notebook are not included.",
    }
    if "code_provenance" in binding:
        code = binding["code_provenance"]
        manifest["code_provenance"] = code
        manifest["code_sha"] = code["git"]["head"]
        manifest["code_sha_semantics"] = "Git HEAD observed before preparation; not a verified execution image or complete reproduction identity."
        if manifest["code_sha"] is not None:
            missing.pop("code_sha")
        else:
            missing["code_sha"] = code["git"]["reason"]
    files = {"result_summary.json": summary_bytes,
             "manifest.json": (canonical_json(manifest) + "\n").encode("utf-8")}
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(payload).hexdigest()}  {name}\n" for name, payload in sorted(files.items())).encode("ascii")
    if sum(map(len, files.values())) > MAX_EXPORT_BYTES:
        raise ValueError("result export exceeds size limit")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in sorted(files.items()):
            # Fixed ZIP metadata makes repeated reads byte-identical.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, payload)
    data = buffer.getvalue()
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError("result export exceeds size limit")
    return {"schema_version": EXPORT_SCHEMA, "status": "ready",
            "filename": "sckg-preview-" + content_hash([task["task_id"], task["attempt"], run.run_id])[:16] + ".zip",
            "mime": "application/zip", "data": data, "sha256": hashlib.sha256(data).hexdigest(),
            "computation_performed_by_export": False}
