"""Create an offline, fictional method-preview demo in a new workspace.

The original three-route workflow demo remains selected for input/chat use.
This adds a separate method sidecar, never scientific evidence or execution.
No model profile, provider receipt, human review or release is manufactured.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
for location in (ROOT, SCRIPT_DIR):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

from bootstrap_workflow_demo import DEMO_AUTHORITY, bootstrap_demo
from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, content_hash
from sckg_workbench.workflow_inputs import WorkflowInputCatalog
from sckg_workbench.workflow_methods import WorkflowMethodCatalog, configured_method_service


FEATURE_ROUTE = "demo_feature_train"
ALTERNATIVE_ROUTE = "demo_counts"


def _binding(candidate, index, *, method=False):
    attribute = candidate["claim"]["typed_attributes"][index]
    value = {"candidate_id": candidate["id"], "candidate_hash": candidate["content_hash"],
             "attribute_index": index, "attribute_hash": content_hash(attribute)}
    return {**value, "attribute_kind": attribute["name"]} if method else value


def _atom(field_id, value=None, *, other_field=None, op="eq"):
    return {"field_id": field_id, "op": op, "value": value, "other_field": other_field}


def _all(*atoms):
    return {"mode": "all", "atoms": list(atoms)}


def bootstrap_method_demo(path: str | Path) -> dict:
    """Extend a freshly created synthetic demo; never adopt an existing ledger."""
    # The shared initializer owns create-only, symlink and production-path
    # protection. Do not initialize or open a requested existing workspace here.
    legacy = bootstrap_demo(path)
    workspace = Workspace(Path(legacy["workspace"]))
    ledger = Ledger(workspace)
    original_pointer = ledger.get_state("workflow_input_catalog")
    legacy_record = ledger.get_record("workflow_input_catalog", legacy["catalog_record_id"])
    counts_route = next(route for route in legacy_record["catalog"]["routes"]
                        if route["route_id"] == ALTERNATIVE_ROUTE)

    text = ("SYNTHETIC ENGINEERING DEMO ONLY. Fictional Feature Trainer is an invented interaction fixture, "
            "not a biological method or a claim about any real software. Its fictional input is counts. "
            "In this fixture, when feature_selection is enabled, the reported postfilter_genes count must "
            "exceed the reported top_genes count. Its fictional balance option applies only when both "
            "use_sgd and mini_batch are enabled. These invented conditions demonstrate typed checks only; "
            "they establish no scientific validity, measurement, calibration, benchmark or executable analysis.")
    source = SourceService(ledger).register_bytes("fictional_feature_trainer.txt", text.encode("utf-8"),
        metadata={"fixture_kind": DEMO_AUTHORITY, "biological_evidence": False})
    ir = SourceService(ledger).parse(source["id"])
    block = ir["blocks"][0]
    claim = {"proposition": text, "subject": "Fictional Feature Trainer (synthetic only)",
        "predicate": "fictionally_requires", "object": "counts and explicitly conditional fixture settings",
        "polarity": "positive", "assertion_kind": "source_assertion",
        "conditions": ["Only the invented engineering fixture described in this source."],
        "unknowns": ["No biological validity, real-data suitability or local execution is established."],
        "anchors": [{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                     "end": len(block["exact_text"]), "quote": block["exact_text"]}],
        "typed_attributes": [
            {"name": "workflow.input", "value": "Fictional counts input is required.",
             "evidence_anchor_indices": [0], "qualifiers": ["Synthetic fixture only."]},
            {"name": "workflow.input", "value": "When fictional feature_selection is enabled, reported postfilter_genes must exceed top_genes.",
             "evidence_anchor_indices": [0], "qualifiers": ["Conditional fixture input precondition; not a biological claim."]},
            {"name": "workflow.action", "value": "The fictional balance option applies only with both use_sgd=True and mini_batch=True.",
             "evidence_anchor_indices": [0], "qualifiers": ["Option scope only; an unavailable option does not reject the whole method."]}],
        "model_self_score": None}
    with ledger.transaction() as connection:
        candidate = KnowledgeService(ledger)._store_candidate(claim, {
            "kind": "synthetic_demo_fixture", "generator": "scripts/bootstrap_method_demo.py",
            "authority": DEMO_AUTHORITY, "not_model_output": True}, conn=connection)

    base = WorkflowInputCatalog.model_validate({
        "schema_version": "development-workflow-input-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review", "routes": [
            {"route_id": FEATURE_ROUTE, "label": "SYNTHETIC ONLY · Fictional Feature Trainer",
             "requirements": [{"requirement_id": "counts", "label": "Report fictional counts input",
                "report_pointer": "/reported_inputs/counts", "source_bindings": [_binding(candidate, 0)]}],
             "context_candidate_ids": [], "requirements_complete": False,
             "scope_notes": ["Invented engineering fixture; no scientific recommendation or executable analysis."]},
            deepcopy(counts_route)]}).model_dump(mode="json")
    base_hash = content_hash(base)
    base_id = "method-demo-base-" + base_hash
    ledger.put_record("workflow_input_catalog", base_id,
        {"id": base_id, "catalog": base, "catalog_hash": base_hash, "demo_authority": DEMO_AUTHORITY})

    def field(key, label, *, kind="boolean", show_when=None):
        return {"field_id": key, "label": "SYNTHETIC · " + label, "scope": "method", "kind": kind,
                "choices": [], "show_when": show_when}

    catalog = WorkflowMethodCatalog.model_validate({
        "schema_version": "development-workflow-method-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review",
        "base_catalog": {"record_id": base_id, "catalog_hash": base_hash}, "protocol": None,
        "fields": [field("feature_selection", "Enable fictional feature selection"),
            field("postfilter_genes", "Reported filtered gene count", kind="integer",
                  show_when={"field_id": "feature_selection", "value": True}),
            field("top_genes", "Reported top gene count", kind="integer",
                  show_when={"field_id": "feature_selection", "value": True}),
            field("balance", "Enable fictional balancing option"),
            field("use_sgd", "Enable fictional SGD flag", show_when={"field_id": "balance", "value": True}),
            field("mini_batch", "Enable fictional mini-batch flag", show_when={"field_id": "balance", "value": True})],
        "routes": [
            {"route_id": FEATURE_ROUTE, "method_scope": "Invented feature-training fixture; synthetic only",
             "version_scope": "Fictional fixture v1; not a measured software version",
             "rules": [
                {"rule_id": "fictional_feature_count", "label": "SYNTHETIC · Filtered count must exceed top count",
                 "kind": "precondition", "when": _all(_atom("feature_selection", True)),
                 "expect": _all(_atom("postfilter_genes", other_field="top_genes", op="gt")),
                 "reported_requirement_id": None, "source_bindings": [_binding(candidate, 1, method=True)]},
                {"rule_id": "fictional_balance_scope", "label": "SYNTHETIC · Balancing option needs both flags",
                 "kind": "option_scope", "when": _all(_atom("balance", True)),
                 "expect": _all(_atom("use_sgd", True), _atom("mini_batch", True)),
                 "reported_requirement_id": None, "source_bindings": [_binding(candidate, 2, method=True)]}],
             "local_policy_checks": []},
            {"route_id": ALTERNATIVE_ROUTE, "method_scope": "Original synthetic counts-only lightweight alternative",
             "version_scope": "Original demo fixture; no scientific version inferred", "rules": [],
             "local_policy_checks": []}]}).model_dump(mode="json")
    digest = content_hash(catalog)
    record_id = "method-demo-catalog-" + digest
    ledger.put_record("workflow_method_catalog", record_id,
        {"id": record_id, "catalog": catalog, "catalog_hash": digest, "demo_authority": DEMO_AUTHORITY})
    ledger.set_state("workflow_method_catalog", {"record_id": record_id, "catalog_hash": digest})
    if ledger.get_state("workflow_input_catalog") != original_pointer:
        raise RuntimeError("Legacy workflow catalog selection unexpectedly changed")

    profile = {"reported_inputs": {"counts": True}, "reported_config": {
        "feature_selection": True, "postfilter_genes": 300, "top_genes": 300,
        "balance": True, "use_sgd": True, "mini_batch": False}, "reported_protocol": {}}
    review = configured_method_service(ledger).evaluate([FEATURE_ROUTE, ALTERNATIVE_ROUTE], profile)
    example = {"schema_version": "synthetic-method-demo-example-v1", "authority": DEMO_AUTHORITY,
        "actual_user_submission": False, "measurements_established": False,
        "description": "Synthetic equal-count boundary blocks only the fictional trainer; its counts-only alternative remains conditional.",
        "profile": profile, "review": review}
    receipt = {"schema_version": "synthetic-method-demo-bootstrap-v1", "status": "created",
        "authority": DEMO_AUTHORITY, "workspace": str(workspace.root), "namespace": workspace.namespace,
        "legacy_input_catalog": original_pointer, "base_catalog_record_id": base_id, "base_catalog_hash": base_hash,
        "method_catalog_record_id": record_id, "method_catalog_hash": digest,
        "fictional_source_id": source["id"], "fictional_candidate_id": candidate["id"],
        "source_count": len(ledger.list_records("source")), "candidate_count": len(ledger.list_records("candidate")),
        "model_calls": len(ledger.list_records("model_call")), "scientific_fits": 0,
        "human_reviews": len(ledger.list_records("review")), "releases": len(ledger.list_records("release")),
        "recommendation_eligible": False, "protocol": None,
        "static_example_report": "method_demo_example_report.json", "example_authority": DEMO_AUTHORITY,
        "synthetic_example_decisions": {r["route_id"]: r["method_decision"] for r in review["route_results"]},
        "ui_command": "# SYNTHETIC ENGINEERING DEMO ONLY\n" + legacy["ui_command"],
        "ui_command_authority": DEMO_AUTHORITY,
        "next_steps": [
            "Run ui_command using the existing installed Streamlit environment; no model is configured.",
            "Open Knowledge (知识库) and locate 开发候选方法 · 配置与适用条件.",
            "Select both synthetic methods, report counts present, enable feature selection, and enter 300 for both counts.",
            "Click 检查方法配置. Change the filtered count to 301 or disable feature selection to inspect the conditional branch.",
            "The original three input/chat routes, workflow_demo_manifest.json and workflow_demo_examples.json remain available.",
            "No scientific suitability, measurement, human review, release or local execution is established."]}
    for filename, value in (("method_demo_example_report.json", example), ("method_demo_manifest.json", receipt)):
        with (workspace.root / filename).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path,
                        help="A new or completely empty, separate synthetic demo directory")
    args = parser.parse_args(argv)
    try:
        receipt = bootstrap_method_demo(args.workspace)
    except (OSError, ValueError, RuntimeError) as error:
        print("Synthetic method demo was not completed: " + str(error)
              + ". Any partial new demo is preserved; use a fresh folder after fixing the cause.", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
