from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRUBLET_RECIPE = Path("examples/workflows/scrublet_doublet_workflow.py")
SCRUBLET_SMOKE_SUMMARY = Path(
    "data/evaluation/workflow_code_smoke_v1/summary.json"
)
HARMONY_RECIPE = Path("examples/workflows/harmony_batch_integration_workflow.py")
HARMONY_SMOKE_SUMMARY = Path(
    "data/evaluation/workflow_code_smoke_v1/harmony_summary.json"
)


class WorkflowCodeBundle(BaseModel):
    """A versioned, maintainer-owned recipe that can be shown in Research Chat."""

    model_config = ConfigDict(protected_namespaces=())

    recipe_id: str
    recipe_version: str
    task_id: str
    tool_name: str
    runtime_pack: str
    environment_name: str
    language: str = "python"
    relative_path: str
    recipe_sha256: str
    code: str
    demo_command: str
    data_command: str
    input_requirements: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    smoke_tested: bool = False
    smoke_status: str = "not_run"
    smoke_summary: dict = Field(default_factory=dict)
    execution_boundary: str = (
        "Version-controlled export recipe; it is not arbitrary generated code and does "
        "not bypass scKG approval or execution gates."
    )


class WorkflowCodeService:
    """Resolve only allowlisted, checked-in workflow recipes."""

    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        self.project_root = Path(project_root).resolve()

    def get_bundle(
        self,
        *,
        task_id: str,
        preferred_tool: str = "",
    ) -> Optional[WorkflowCodeBundle]:
        if task_id == "batch_integration":
            return self._harmony_bundle(preferred_tool)
        if task_id != "doublet_detection":
            return None
        if preferred_tool and preferred_tool.casefold() != "scrublet":
            return None

        recipe_path = self.project_root / SCRUBLET_RECIPE
        if not recipe_path.is_file():
            return None
        code = recipe_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        smoke_summary = self._smoke_summary(SCRUBLET_SMOKE_SUMMARY, digest)
        smoke_tested = bool(smoke_summary.get("smoke_passed"))
        return WorkflowCodeBundle(
            recipe_id="doublet-detection-scrublet-python",
            recipe_version="1.0.0",
            task_id=task_id,
            tool_name="Scrublet",
            runtime_pack="doublet-python",
            environment_name="scRNAseq",
            relative_path=SCRUBLET_RECIPE.as_posix(),
            recipe_sha256=digest,
            code=code,
            demo_command=(
                "conda run -n scRNAseq python "
                "examples/workflows/scrublet_doublet_workflow.py "
                "--demo --output scrublet_demo_results"
            ),
            data_command=(
                "conda run -n scRNAseq python "
                "examples/workflows/scrublet_doublet_workflow.py "
                "--input your_pbmc.h5ad --sample-key sample "
                "--output scrublet_results"
            ),
            input_requirements=[
                "AnnData .h5ad with non-negative integer raw UMI counts",
                "Prefer layers['counts']; otherwise a valid X or raw.X is selected",
                "Provide --sample-key when multiple 10x captures are stored together",
            ],
            output_artifacts=[
                "doublet_results.tsv",
                "doublet_annotated.h5ad",
                "doublet_score_distribution.png",
                "doublet_score_vs_library_size.png",
                "workflow_summary.json",
            ],
            limitations=[
                "Homotypic doublets and continuous cell states remain difficult.",
                "The expected rate and automatic threshold require dataset-level review.",
                "The demo smoke is an engineering check, not biological validation.",
            ],
            smoke_tested=smoke_tested,
            smoke_status="passed" if smoke_tested else "not_run_or_recipe_changed",
            smoke_summary=smoke_summary,
        )

    def _harmony_bundle(self, preferred_tool: str) -> Optional[WorkflowCodeBundle]:
        if preferred_tool and preferred_tool.casefold() != "harmony":
            return None
        recipe_path = self.project_root / HARMONY_RECIPE
        if not recipe_path.is_file():
            return None
        code = recipe_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        smoke_summary = self._smoke_summary(HARMONY_SMOKE_SUMMARY, digest)
        smoke_tested = bool(smoke_summary.get("smoke_passed"))
        return WorkflowCodeBundle(
            recipe_id="batch-integration-harmony-python",
            recipe_version="1.0.0",
            task_id="batch_integration",
            tool_name="Harmony",
            runtime_pack="batch-cpu",
            environment_name="sckg-batch-cpu",
            relative_path=HARMONY_RECIPE.as_posix(),
            recipe_sha256=digest,
            code=code,
            demo_command=(
                "conda run -n sckg-batch-cpu python "
                "examples/workflows/harmony_batch_integration_workflow.py "
                "--demo --output harmony_demo_results"
            ),
            data_command=(
                "conda run -n sckg-batch-cpu python "
                "examples/workflows/harmony_batch_integration_workflow.py "
                "--input your_pbmc.h5ad --batch-key batch "
                "--matrix-state raw_counts --output harmony_results"
            ),
            input_requirements=[
                "AnnData .h5ad with at least two batches in --batch-key",
                "Declare whether the selected matrix is raw_counts or log_normalized",
                "Use a batch variable that represents technical rather than biological variation",
            ],
            output_artifacts=[
                "integrated_embedding.tsv",
                "harmony_integrated.h5ad",
                "batch_mixing_before_after.png",
                "workflow_summary.json",
            ],
            limitations=[
                "Improved batch mixing must not be accepted if biological separation collapses.",
                "Harmony corrects an embedding and does not create corrected count values.",
                "The demo smoke is an engineering check, not biological validation.",
            ],
            smoke_tested=smoke_tested,
            smoke_status="passed" if smoke_tested else "not_run_or_recipe_changed",
            smoke_summary=smoke_summary,
        )

    def _smoke_summary(self, relative_path: Path, recipe_digest: str) -> dict:
        path = self.project_root / relative_path
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if payload.get("recipe_sha256") != recipe_digest:
            return {}
        return payload
