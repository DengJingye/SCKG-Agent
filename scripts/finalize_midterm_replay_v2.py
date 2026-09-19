#!/usr/bin/env python3
"""Freeze the current PBMC3k browser/Jupyter replay as auditable manifests."""

from __future__ import annotations

import hashlib
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data/evaluation/current_version_pbmc3k_replay_v2/20260919-current-01"
SOURCE_DIR = (
    ROOT.parent / "SCKG-Agent/.sckg_exec/approved-inputs/"
    "pbmc3k-scanpy-official/1.0.0"
)

DATASETS = {
    "raw": {
        "source": SOURCE_DIR / "pbmc3k_raw.h5ad",
        "upload": ROOT / ".sckg_exec/approved-inputs/research-uploads/local-user/"
        "89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1.h5ad",
        "notebook": ROOT / ".sckg_exec/research-workspace/local-user/"
        "capability-notebooks/scanpy_core-9e76f6b3d974.ipynb",
        "artifact_dir": ROOT / ".sckg_exec/research-workspace/local-user/"
        "capability-notebooks/.sckg_notebook_artifacts/scanpy_core-9e76f6b3d974",
        "expected_shape": [2700, 32738],
        "expected_plan_id": "cap-plan-060f3fdd8e1664bf",
    },
    "processed": {
        "source": SOURCE_DIR / "pbmc3k.h5ad",
        "upload": ROOT / ".sckg_exec/approved-inputs/research-uploads/local-user/"
        "0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38.h5ad",
        "notebook": ROOT / ".sckg_exec/research-workspace/local-user/"
        "capability-notebooks/scanpy_core-5129135809c4.ipynb",
        "artifact_dir": ROOT / ".sckg_exec/research-workspace/local-user/"
        "capability-notebooks/.sckg_notebook_artifacts/scanpy_core-5129135809c4",
        "expected_shape": [2638, 1838],
        "expected_plan_id": "cap-plan-39567af880c3cd1f",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def observation_by_hash() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(RUN_DIR.glob("observed-*.json")):
        payload = read_json(path)
        if payload.get("component") != "engine/capability_workspace_service.py":
            continue
        result = payload.get("result") or {}
        profile = result.get("data_profile") or {}
        file_hash = profile.get("file_hash")
        if file_hash:
            records[str(file_hash)] = {
                "path": path,
                "result": result,
            }
    return records


def terminal_validation(artifact_dir: Path) -> tuple[Path, dict[str, Any]]:
    matches = sorted(artifact_dir.glob("annotation-*/terminal_validation.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one terminal validation under {artifact_dir}, got {len(matches)}")
    return matches[0], read_json(matches[0])


def notebook_state(path: Path) -> dict[str, Any]:
    notebook = read_json(path)
    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]
    errors = []
    for index, cell in enumerate(code_cells):
        for output in cell.get("outputs", []):
            if output.get("output_type") == "error":
                errors.append(
                    {
                        "code_cell_index": index,
                        "ename": output.get("ename"),
                        "evalue": output.get("evalue"),
                    }
                )
    stored = (notebook.get("metadata", {}).get("sckg", {}).get("cell_source_digests", {}))
    current = {}
    for cell in notebook["cells"]:
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        current[str(cell.get("id"))] = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    return {
        "code_cells": len(code_cells),
        "executed_code_cells": sum(cell.get("execution_count") is not None for cell in code_cells),
        "error_outputs": errors,
        "cell_source_digests_match_compile_manifest": stored == current,
        "plan_id": notebook.get("metadata", {}).get("sckg", {}).get("plan_id"),
        "execution_request_count": notebook.get("metadata", {}).get("sckg", {}).get("execution_request_count"),
        "kernel": notebook.get("metadata", {}).get("kernelspec", {}),
    }


def build_manifest(name: str, config: dict[str, Any], observations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_hash = sha256(config["source"])
    upload_hash = sha256(config["upload"])
    observed = observations[source_hash]
    result = observed["result"]
    profile = result["data_profile"]
    plan = result["workflow_plan"]
    notebook = notebook_state(config["notebook"])
    terminal_path, terminal = terminal_validation(config["artifact_dir"])
    files = sorted(path for path in config["artifact_dir"].rglob("*") if path.is_file())
    operations = [step["operation"] for step in plan.get("steps", [])]
    shape = [profile["n_cells"], profile["n_genes"]]
    all_cells_executed = notebook["executed_code_cells"] == notebook["code_cells"]
    terminal_block_only = bool(notebook["error_outputs"]) and all(
        str(error.get("evalue", "")).startswith("ANNOTATION_TERMINAL_INCOMPLETE:")
        for error in notebook["error_outputs"]
    )
    return {
        "dataset": name,
        "classification": "CURRENT_MEASURED",
        "product_surface": "Streamlit Research -> Stepwise -> local JupyterLab",
        "real_llm_exercised": False,
        "research_runtime_mode": "local_deterministic",
        "source_path": rel(config["source"]),
        "source_sha256": source_hash,
        "uploaded_copy_path": rel(config["upload"]),
        "uploaded_copy_sha256": upload_hash,
        "source_upload_integrity": source_hash == upload_hash,
        "data_profile": {
            "profile_id": profile.get("profile_id"),
            "shape": shape,
            "raw_exists": profile.get("raw_exists"),
            "layers": profile.get("layers"),
            "obsm_keys": profile.get("obsm_keys"),
            "obsp_keys": profile.get("obsp_keys"),
            "obs_keys": profile.get("obs_keys"),
            "matrix_profiles": profile.get("matrix_profiles"),
        },
        "workflow_plan": {
            "plan_id": plan.get("plan_id"),
            "operations": operations,
            "step_count": len(operations),
            "plan_status": plan.get("plan_status"),
            "execution_eligible": plan.get("execution_eligible"),
            "planning_warnings": plan.get("planning_warnings"),
        },
        "notebook": {
            "path": rel(config["notebook"]),
            "sha256_after_execution": sha256(config["notebook"]),
            **notebook,
        },
        "terminal_validation": {
            "path": rel(terminal_path),
            **terminal,
        },
        "artifacts": [
            {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in files
        ],
        "checks": {
            "expected_shape": shape == config["expected_shape"],
            "expected_plan_id": plan.get("plan_id") == config["expected_plan_id"],
            "all_code_cells_executed": all_cells_executed,
            "only_expected_terminal_block_errors": terminal_block_only,
            "cell_source_digests_unchanged": notebook["cell_source_digests_match_compile_manifest"],
            "source_file_unchanged": source_hash == upload_hash,
        },
        "PLAN_COMPILED": True,
        "NOTEBOOK_COMPILED": True,
        "NOTEBOOK_EXECUTED": all_cells_executed,
        "CANDIDATE_TERMINAL_SATISFIED": bool(terminal.get("annotation_candidates_satisfied")),
        "HUMAN_CONFIRMATION_COMPLETED": bool(terminal.get("confirmed_annotation_satisfied")),
        "FULL_SCIENTIFIC_TASK_COMPLETED": bool(terminal.get("full_scientific_task_completed")),
        "observation_path": rel(observed["path"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suffix",
        default="",
        help="Append a suffix before .json so a corrected audit can preserve an earlier failed manifest.",
    )
    args = parser.parse_args()
    suffix = f".{args.suffix}" if args.suffix else ""
    observations = observation_by_hash()
    manifests = {name: build_manifest(name, config, observations) for name, config in DATASETS.items()}
    all_checks = [value for manifest in manifests.values() for value in manifest["checks"].values()]
    summary = {
        "schema_version": "current-version-pbmc3k-replay-v2",
        "classification": "CURRENT_MEASURED",
        "run_id": RUN_DIR.name,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_WITH_EXPECTED_TERMINAL_BLOCKS" if all(all_checks) else "FAIL",
        "browser_product_replay": True,
        "manual_jupyter_restart_and_run_all": True,
        "real_llm_authorized": True,
        "real_llm_exercised": False,
        "controlled_execution_requested": False,
        "execution_request_count": 0,
        "datasets": manifests,
        "claims": {
            "input_binding_correct": all(item["source_upload_integrity"] for item in manifests.values()),
            "raw_numeric_workflow_completed": manifests["raw"]["NOTEBOOK_EXECUTED"],
            "processed_reuse_workflow_completed": manifests["processed"]["NOTEBOOK_EXECUTED"],
            "annotation_candidates_satisfied": False,
            "human_confirmation_completed": False,
            "full_scientific_task_completed": False,
        },
        "limitations": [
            "Research PLAN used the local deterministic path; this replay is not evidence of LLM planning quality.",
            "Run All was an explicit manual Jupyter action, not controlled execution or an ExecutionRequest.",
            "Both notebooks intentionally preserve annotation terminal blocks; no candidate or human-confirmed label was fabricated.",
            "Processed natural-language wording about latest marker revision was not converted into a structured reviewed evidence bundle.",
        ],
    }
    for name, manifest in manifests.items():
        path = RUN_DIR / f"{name}_final_manifest{suffix}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    with (RUN_DIR / f"summary{suffix}.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": summary["status"], "run_dir": rel(RUN_DIR)}, indent=2))


if __name__ == "__main__":
    main()
