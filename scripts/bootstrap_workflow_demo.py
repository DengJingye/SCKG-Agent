"""Create a fresh, offline, explicitly synthetic workflow demonstration.

This does not import a scientific knowledge base, create model credentials or
receipts, review evidence, publish a release, or execute scientific analysis.
Run with an explicit --workspace pointing to a new or completely empty folder.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, content_hash
from sckg_workbench.workflow_inputs import WorkflowInputCatalog, WorkflowInputService


DEMO_AUTHORITY = "synthetic_engineering_demo_not_scientific_evidence"
DEMO_CASES = (
    ("demo_counts", "counts", "Synthetic counts route"),
    ("demo_auxiliary", "auxiliary_measurements", "Synthetic auxiliary-input route"),
    ("demo_design", "replicate_design", "Synthetic design-input route"),
)


def _create_only_workspace(path: str | Path) -> Workspace:
    raw = Path(path).expanduser().absolute()
    if any(part.is_symlink() for part in (raw, *raw.parents)):
        raise ValueError("Demo workspace and its parents must not be symlinks")
    target = raw.resolve()
    protected = {Workspace.default().root,
                 (Path.home() / ".local" / "share" / "sckg-workbench").resolve()}
    if any(target == root or root in target.parents or target in root.parents for root in protected):
        raise ValueError("Refusing the production/default workspace or its ancestors/children; choose a separate demo folder")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("Create-only demo requires a new or completely empty directory; existing contents are untouched")
    workspace = Workspace(target)
    # Reuse the workspace's existing initialization lock and empty-directory
    # check, including a second check after acquiring the shared lock.
    with workspace.initialization_lock():
        if any(target.iterdir()):
            raise ValueError("Create-only demo directory became nonempty; existing contents are untouched")
        workspace._initialize_locked()
    return workspace


def bootstrap_demo(path: str | Path) -> dict:
    """Populate only a new demo workspace; never adopt an existing ledger."""
    workspace = _create_only_workspace(path)
    ledger = Ledger(workspace)
    sources, knowledge = SourceService(ledger), KnowledgeService(ledger)
    candidates, routes = [], []
    for route_id, input_name, label in DEMO_CASES:
        text = ("SYNTHETIC ENGINEERING DEMO ONLY. " + label + " is a fictional route used to test interaction. "
                "Its fictional input is " + input_name + ". This text provides no biological method, "
                "scientific validation, benchmark, executable analysis or real-paper evidence.")
        source = sources.register_bytes(route_id + ".txt", text.encode("utf-8"),
            metadata={"fixture_kind": DEMO_AUTHORITY, "biological_evidence": False})
        ir = sources.parse(source["id"])
        block = ir["blocks"][0]
        claim = {"proposition": text, "subject": label, "predicate": "fictionally_requires",
            "object": input_name, "polarity": "positive", "assertion_kind": "source_assertion",
            "conditions": ["Only the fictional engineering demonstration described in this source."],
            "unknowns": ["No biological validity, real-data availability, preprocessing or executable analysis is established."],
            "anchors": [{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                         "end": len(block["exact_text"]), "quote": block["exact_text"]}],
            "typed_attributes": [{"name": "workflow.input", "value": input_name,
                "evidence_anchor_indices": [0], "qualifiers": ["Fictional fixture input, not scientific evidence."]}]}
        # This is repository-authored fixture material, not a model extraction.
        # The shared ingestion integrity path verifies claims and exact anchors;
        # no fake model profile, session, call, assessment or review is created.
        with ledger.transaction() as connection:
            candidate = knowledge._store_candidate(claim, {
                "kind": "synthetic_demo_fixture", "generator": "scripts/bootstrap_workflow_demo.py",
                "authority": DEMO_AUTHORITY, "not_model_output": True}, conn=connection)
        candidates.append(candidate)
        routes.append({"route_id": route_id, "label": "DEMO ONLY · " + label,
            "requirements": [{"requirement_id": input_name, "label": "Report fictional " + input_name,
                "report_pointer": "/reported_inputs/" + input_name,
                "source_bindings": [{"candidate_id": candidate["id"], "candidate_hash": candidate["content_hash"],
                    "attribute_index": 0, "attribute_hash": content_hash(candidate["claim"]["typed_attributes"][0])}]}],
            "context_candidate_ids": [], "requirements_complete": False,
            "scope_notes": ["Synthetic interaction fixture only; not a single-cell analysis recommendation.",
                "Reports are not measurements. Complete scientific applicability and local execution remain unestablished."]})
    catalog = WorkflowInputCatalog.model_validate({
        "schema_version": "development-workflow-input-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review", "routes": routes}).model_dump(mode="json")
    digest = content_hash(catalog)
    record_id = "workflow-demo-catalog-" + digest
    ledger.put_record("workflow_input_catalog", record_id,
        {"id": record_id, "catalog": catalog, "catalog_hash": digest, "demo_authority": DEMO_AUTHORITY})
    ledger.set_state("workflow_input_catalog", {"record_id": record_id, "catalog_hash": digest})
    # These are clearly labeled example fixture values, not an actual user's
    # submission. Missing replicate_design intentionally exercises unknown.
    examples = {"authority": DEMO_AUTHORITY, "actual_user_submission": False,
        "profile": {"reported_inputs": {"counts": True, "auxiliary_measurements": False}},
        "example_prompt": ("Synthetic engineering demo only: counts 已有；auxiliary_measurements 明确没有；"
                           "replicate_design 尚不清楚。请分别检查这三条 fictional demo 路线，保持未知并追问。")}
    review = WorkflowInputService(ledger, catalog, expected_catalog_hash=digest).evaluate(
        [route["route_id"] for route in routes], examples["profile"])
    observations = {route["route_id"]: {
        "reported_state": route["assessment"]["decision_check"]["preconditions_status"],
        "action_state": route["assessment"]["decision_check"]["action_status"]}
        for route in review["route_results"]}
    command = ("SCKG_WORKBENCH_HOME=" + shlex.quote(str(workspace.root))
               + " " + shlex.quote(sys.executable) + " -m streamlit run "
               + shlex.quote(str(ROOT / "workbench_app.py")))
    receipt = {"schema_version": "synthetic-workflow-demo-bootstrap-v1", "status": "created",
        "authority": DEMO_AUTHORITY, "workspace": str(workspace.root), "namespace": workspace.namespace,
        "catalog_record_id": record_id, "catalog_hash": digest,
        "source_count": len(ledger.list_records("source")), "candidate_count": len(candidates),
        "model_calls": len(ledger.list_records("model_call")), "scientific_fits": 0,
        "human_reviews": len(ledger.list_records("review")), "releases": len(ledger.list_records("release")),
        "recommendation_eligible": False, "synthetic_example_observations": observations,
        "ui_command": command, "next_steps": [
            "Open the separate demo workspace with ui_command in your already installed environment.",
            "For offline tri-state interaction, open Knowledge (知识库) → 流程输入检查（开发预览）.",
            "For natural-language interaction, open Research (研究台), explicitly enable 开发流程对话：按来源检查输入, and use example_prompt.",
            "Model chat additionally requires your own real provider/profile and explicit budget; bootstrap configures none."]}
    for filename, value in (("workflow_demo_examples.json", examples), ("workflow_demo_manifest.json", receipt)):
        with (workspace.root / filename).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path,
                        help="A new or completely empty folder, separate from any existing/default workspace")
    args = parser.parse_args(argv)
    try:
        receipt = bootstrap_demo(args.workspace)
    except (OSError, ValueError, RuntimeError) as error:
        print("Demo was not completed: " + str(error)
              + ". Any newly created partial demo is preserved; use a fresh folder after fixing the cause.", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
