from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core.capability_pack_registry import CapabilityPackRegistry
from core.execution_models import ExecutionRun
from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_planner import CapabilityPlanCompiler
from execution.capability_adapters import ExecutionAdapterRegistry, RScriptExecutionAdapter
from execution.capability_notebook import (
    GenericNotebookCompiler,
    MaintainerTemplateRenderer,
    NotebookRendererRegistry,
)
from execution.validators.capability import (
    ArtifactHashPrimitive,
    CapabilityValidationPipeline,
    ExecutionSuccessPrimitive,
    RequiredArtifactsPrimitive,
)


class _MockRScientificValidator:
    validator_id = "mock_r_scientific"

    def validate(self, run):
        path = Path(run.artifact_paths.get("mock_r_table.tsv", ""))
        valid = path.is_file() and path.read_text(encoding="utf-8").startswith("id\tvalue")
        return ([] if valid else ["mock_r_schema_invalid"], {"mock_r_schema": valid}, [])


def _mock_ledger():
    return RepresentationLedger(
        ledger_id="mock-r-ledger",
        profile_id="mock-r-profile",
        source_artifact_id="mock-r-artifact",
        source_hash="a" * 64,
        cell_index_hash="b" * 64,
        gene_index_hash="c" * 64,
        records=[
            RepresentationRecord(
                representation_record_id="mock-r-input-record",
                representation_id="mock_r_input",
                schema_version="1.0",
                value_state="table",
                slot="input/table",
                provenance=["mock_input_reviewed"],
                validated=True,
            )
        ],
    )


def test_non_python_pack_reaches_discovery_planning_notebook_validation_and_evaluation(tmp_path):
    registry = CapabilityPackRegistry()
    manifest = registry.load("mock_r_capability", "1.0.0")
    gate = registry.gate(manifest)
    discovery = registry.discover(capability_id="mock_r.transform")

    assert gate.passed is True
    assert [str(item) for item in gate.readiness] == [
        "discovered",
        "planning_ready",
        "notebook_ready",
        "validation_ready",
    ]
    assert gate.execution_eligible is False
    assert discovery[0].method_ids == ["mock_r.identity"]

    plan, plan_result = CapabilityPlanCompiler(registry).compile(
        pack_id="mock_r_capability",
        pack_version="1.0.0",
        ledger=_mock_ledger(),
        target_representations=["mock_r_table"],
        requirement_id="mock-r-extensibility",
    )
    assert plan_result.blocked is False
    assert plan_result.planned_method_ids == ["mock_r.identity"]

    renderer = MaintainerTemplateRenderer(
        {"identity": "result <- input_table"},
        renderer_id="mock_r_renderer",
        language_name="R",
    )
    notebook = tmp_path / "mock-r.ipynb"
    GenericNotebookCompiler(NotebookRendererRegistry([renderer])).compile(
        plan=plan,
        step_contracts=registry.load_step_contracts(manifest),
        output_path=notebook,
        title="Mock R capability",
    )
    payload = json.loads(notebook.read_text(encoding="utf-8"))
    assert payload["metadata"]["language_info"]["name"] == "R"
    assert "result <- input_table" in json.dumps(payload)

    rscript = tmp_path / "Rscript"
    script = tmp_path / "mock_identity.R"
    rscript.write_text("", encoding="utf-8")
    script.write_text("", encoding="utf-8")
    adapters = ExecutionAdapterRegistry()
    adapters.register(RScriptExecutionAdapter("mock_rscript_adapter", rscript, script))
    assert adapters.get("mock_rscript_adapter").command("request.json")[-2:] == [
        "--request-json",
        "request.json",
    ]

    artifact = tmp_path / "mock_r_table.tsv"
    artifact.write_text("id\tvalue\na\t1\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    run = ExecutionRun(
        request_id="mock-r-request",
        run_id="mock-r-run",
        trace_id="mock-r-trace",
        plan_id=plan.plan_id,
        step_id="mock_r.identity",
        wrapper_id="mock-r-wrapper",
        tool_name="mock-r",
        tool_version="1.0",
        environment_id="mock-r-env",
        command_argv_redacted=["Rscript", "mock_identity.R", "--request-json", "request.json"],
        parameters={},
        input_hash="a" * 64,
        start_time=now,
        end_time=now,
        runtime_seconds=0.01,
        exit_code=0,
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
        artifact_paths={"mock_r_table.tsv": str(artifact)},
        artifact_hashes={"mock_r_table.tsv": digest},
        status="succeeded",
        fixture_id="mock-r-fixture",
    )
    validation = CapabilityValidationPipeline(
        primitives=[
            ExecutionSuccessPrimitive(),
            RequiredArtifactsPrimitive({"mock_r_table.tsv"}),
            ArtifactHashPrimitive(),
        ],
        scientific_validator=_MockRScientificValidator(),
    ).validate(run)
    assert validation.passed is True
    assert manifest.gold_case_bindings[0].applicable_metrics == [
        "discovery",
        "planning",
        "notebook",
        "validation",
    ]

    for source in [
        "engine/capability_planner.py",
        "agent/research_chat_service.py",
        "execution/execution_orchestrator.py",
    ]:
        assert "mock_r_capability" not in Path(source).read_text(encoding="utf-8")
