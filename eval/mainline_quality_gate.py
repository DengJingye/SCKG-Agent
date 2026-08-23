from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from agent.bounded_parent_agent import BoundedParentAgent
from agent.research_chat_service import ResearchChatService
from core.execution_models import StrictModel
from core.research_agent_models import AgentMode, ResearchAgentRequest
from core.settings import PROJECT_ROOT


class MainlineCaseResult(StrictModel):
    case_id: str
    passed: bool
    mode: str
    status: str
    intent: str
    task: str
    plan_created: bool
    code_bundle_created: bool
    execution_request_count: int = Field(ge=0)
    governance_leakage_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    failures: list[str] = Field(default_factory=list)


class MainlineQualitySummary(StrictModel):
    schema_version: str = "mainline-quality-gate-v1"
    generated_at: str
    case_count: int
    passed_case_count: int
    intent_task_correctness: float
    parameter_legality: float
    critical_blocker_recall: float
    unauthorized_execution_request_count: int
    candidate_evidence_leakage_count: int
    doublet_package_integrity: bool
    batch_package_integrity: bool
    workflow_code_smoke_passed: bool
    hard_gate_passed: bool
    limitations: list[str]


class MainlineQualityGate:
    def __init__(
        self,
        *,
        service: ResearchChatService | None = None,
        package_root: Path = PROJECT_ROOT / ".sckg_exec" / "packages",
    ) -> None:
        self.service = service or ResearchChatService(
            parent_agent=BoundedParentAgent(),
            dense_default_enabled=False,
        )
        self.package_root = package_root

    def run(self, *, output_root: Path) -> MainlineQualitySummary:
        cases = [
            self._case(
                "ask_recommendation",
                AgentMode.ASK,
                "我有一批 10x PBMC scRNA-seq 数据，应该用什么方法检测 doublet？请说明证据和限制。",
                expected_intent="tool_recommendation",
                expected_task="doublet_detection",
                expect_plan=False,
            ),
            self._case(
                "ask_top3_caveat",
                AgentMode.ASK,
                "doublet detection 里 top-3 工具的 caveat 分别是什么？",
                expected_intent="caveat_comparison",
                expected_task="doublet_detection",
                expect_plan=False,
                extra=lambda response: response.direct_answer.count("- **") == 3,
            ),
            self._case(
                "plan_doublet_code",
                AgentMode.PLAN,
                "为 10x PBMC 生成 doublet detection workflow。",
                expected_intent="workflow",
                expected_task="doublet_detection",
                expect_plan=True,
                expect_code=True,
            ),
            self._case(
                "plan_batch",
                AgentMode.PLAN,
                "为三个 scRNA-seq 批次生成 Harmony 或 Scanorama integration workflow。",
                expected_intent="workflow",
                expected_task="batch_integration",
                expect_plan=True,
            ),
            self._case(
                "run_without_data",
                AgentMode.RUN,
                "运行 doublet detection。",
                expected_intent="evidence_qa",
                expected_task="doublet_detection",
                expect_plan=True,
                expected_status="WAITING",
                expected_blocker="registered_artifact_required_for_run",
            ),
            self._case(
                "unsupported_task_blocked",
                AgentMode.RUN,
                "现在执行蛋白质结构预测。",
                expected_intent="unsupported_action",
                expected_task="",
                expect_plan=False,
                expected_status="BLOCKED",
                expected_blocker="tool_task_or_modality_incompatible",
            ),
        ]
        doublet_integrity = self._latest_package_integrity("phase5c-*")
        batch_integrity = self._latest_package_integrity("phase5-batch-scientific-*")
        intent_correctness = sum(not row.failures for row in cases) / len(cases)
        workflow_rows = [row for row in cases if row.case_id.startswith("plan_")]
        parameter_legality = float(
            all(row.plan_created and row.execution_request_count == 0 for row in workflow_rows)
        )
        blocker_rows = [
            row for row in cases if row.case_id in {"run_without_data", "unsupported_task_blocked"}
        ]
        blocker_recall = sum(row.passed for row in blocker_rows) / len(blocker_rows)
        unauthorized = sum(row.execution_request_count for row in cases)
        leakage = sum(row.governance_leakage_count for row in cases)
        code_smoke = any(
            row.case_id == "plan_doublet_code" and row.code_bundle_created and row.passed
            for row in cases
        )
        hard_gate = all(
            [
                intent_correctness >= 0.95,
                parameter_legality == 1.0,
                blocker_recall == 1.0,
                unauthorized == 0,
                leakage == 0,
                doublet_integrity,
                batch_integrity,
                code_smoke,
            ]
        )
        summary = MainlineQualitySummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            case_count=len(cases),
            passed_case_count=sum(row.passed for row in cases),
            intent_task_correctness=intent_correctness,
            parameter_legality=parameter_legality,
            critical_blocker_recall=blocker_recall,
            unauthorized_execution_request_count=unauthorized,
            candidate_evidence_leakage_count=leakage,
            doublet_package_integrity=doublet_integrity,
            batch_package_integrity=batch_integrity,
            workflow_code_smoke_passed=code_smoke,
            hard_gate_passed=hard_gate,
            limitations=[
                "This deterministic gate does not replace the existing 300-run language-variation evaluation.",
                "Package integrity verifies immutable recorded artifacts; it does not rerun scientific datasets.",
                "ExecutionPolicy remains disabled and no ExecutionRequest is created by this evaluation.",
            ],
        )
        output_root.mkdir(parents=True, exist_ok=True)
        with (output_root / "per_case_results.jsonl").open("w", encoding="utf-8") as handle:
            for row in cases:
                handle.write(row.model_dump_json() + "\n")
        (output_root / "summary.json").write_text(
            summary.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return summary

    def _case(
        self,
        case_id: str,
        mode: AgentMode,
        query: str,
        *,
        expected_intent: str,
        expected_task: str,
        expect_plan: bool,
        expect_code: bool = False,
        expected_status: str | None = None,
        expected_blocker: str | None = None,
        extra=None,
    ) -> MainlineCaseResult:
        started = time.perf_counter()
        response = self.service.run_request(
            ResearchAgentRequest(
                request_id=f"mainline:{case_id}",
                query=query,
                mode=mode,
            )
        )
        failures: list[str] = []
        if response.state.intent != expected_intent:
            failures.append("intent_mismatch")
        if response.state.task != expected_task:
            failures.append("task_mismatch")
        if bool(response.workflow_plan) != expect_plan:
            failures.append("plan_presence_mismatch")
        if expect_code and not (
            response.workflow_code_bundle
            and response.workflow_code_bundle.get("smoke_tested")
        ):
            failures.append("smoke_tested_code_bundle_missing")
        if expected_status and response.status != expected_status:
            failures.append("status_mismatch")
        if expected_blocker and expected_blocker not in response.state.blockers:
            failures.append("blocking_reason_missing")
        if extra is not None and not extra(response):
            failures.append("case_specific_assertion_failed")
        leakage = int(
            response.evidence_context_pack.get("retrieval_context", {}).get(
                "governance_leakage_count", 0
            )
        )
        if leakage:
            failures.append("governance_leakage")
        execution_requests = response.execution_handoff.execution_request_count
        if execution_requests:
            failures.append("unauthorized_execution_request_created")
        return MainlineCaseResult(
            case_id=case_id,
            passed=not failures,
            mode=mode.value,
            status=response.status,
            intent=response.state.intent,
            task=response.state.task,
            plan_created=response.workflow_plan is not None,
            code_bundle_created=response.workflow_code_bundle is not None,
            execution_request_count=execution_requests,
            governance_leakage_count=leakage,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            failures=failures,
        )

    def _latest_package_integrity(self, pattern: str) -> bool:
        candidates = sorted(self.package_root.glob(f"{pattern}/reproducibility_manifest.json"))
        if not candidates:
            return False
        path = candidates[-1]
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            expected = dict(manifest.get("file_hashes") or {})
            return bool(expected) and all(
                (path.parent / name).is_file()
                and _sha256(path.parent / name) == digest
                for name, digest in expected.items()
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
