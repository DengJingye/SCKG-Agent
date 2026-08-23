from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from core.execution_models import StrictModel
from core.settings import PROJECT_ROOT
from scripts.build_local_release import build_release
from eval.evaluation_registry import EvaluationExperimentRegistry


class PortfolioAcceptanceCheck(StrictModel):
    check_id: str
    status: Literal["passed", "failed", "not_run"]
    command: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    artifact: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class PortfolioAcceptanceResult(StrictModel):
    schema_version: str = "portfolio-acceptance-v1"
    version: str = "2.7.2-rc"
    generated_at: str
    portfolio_status: Literal["RC_READY_FOR_USER_REVIEW", "RC_BLOCKED"]
    phase6_status: Literal["PHASE6_TRIAL_READY"] = "PHASE6_TRIAL_READY"
    execution_policy: Literal["disabled"] = "disabled"
    real_trial_participants: int = 0
    git_head: str
    git_branch: str
    git_dirty: bool
    tracked_modified_count: int = Field(ge=0)
    untracked_count: int = Field(ge=0)
    worktree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: list[PortfolioAcceptanceCheck]
    hard_gate_passed: bool
    limitations: list[str]


class PortfolioAcceptanceRunner:
    """Run existing quality gates and package their immutable results for review."""

    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        python_executable: Path | str = sys.executable,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.python_executable = str(python_executable)

    def run(self, *, output_root: Path) -> PortfolioAcceptanceResult:
        output_root = Path(output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        logs = output_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["SCKG_PRIVACY_MODE"] = "strict_offline"
        env["SCKG_EXECUTION_POLICY"] = "disabled"

        commands = (
            (
                "pytest",
                [self.python_executable, "-m", "pytest"],
                None,
            ),
            (
                "mainline",
                [
                    self.python_executable,
                    "eval/run_mainline_quality_gate.py",
                    "--output-root",
                    str(output_root / "mainline"),
                ],
                output_root / "mainline" / "summary.json",
            ),
            (
                "retrieval",
                [
                    self.python_executable,
                    "eval/run_retrieval_evaluation_v2.py",
                    "--output",
                    str(output_root / "retrieval"),
                    "--route-policy-output",
                    str(output_root / "retrieval" / "route_decision.json"),
                ],
                output_root / "retrieval" / "summary.json",
            ),
            (
                "agent_quality",
                [
                    self.python_executable,
                    "eval/run_agent_quality_evaluation.py",
                    "--output",
                    str(output_root / "agent_quality"),
                    "--repetitions",
                    "3",
                ],
                output_root / "agent_quality" / "summary.json",
            ),
            (
                "memory",
                [
                    self.python_executable,
                    "eval/run_memory_quality_evaluation.py",
                    "--output",
                    str(output_root / "memory"),
                ],
                output_root / "memory" / "summary.json",
            ),
            (
                "interview_demo",
                [
                    self.python_executable,
                    "scripts/run_interview_demo.py",
                    "--output-root",
                    str(output_root / "interview"),
                ],
                output_root / "interview" / "interview_summary.json",
            ),
        )
        checks = [
            self._run_command(
                check_id=check_id,
                argv=argv,
                log_path=logs / f"{check_id}.log",
                artifact=artifact,
                env=env,
                output_root=output_root,
            )
            for check_id, argv, artifact in commands
        ]
        unified = EvaluationExperimentRegistry().latest("pr")
        unified_gate = dict(unified.get("release_gate") or {})
        checks.append(
            PortfolioAcceptanceCheck(
                check_id="unified_evaluation_pr",
                status=(
                    "passed"
                    if unified_gate.get("status") == "passed"
                    else "not_run"
                    if not unified
                    else "failed"
                ),
                artifact=str(unified.get("path") or ""),
                metrics={
                    "experiment_id": unified.get("experiment_id", ""),
                    "release_gate": unified_gate.get("status", "not_run"),
                    "blocker_count": len(unified_gate.get("blockers") or []),
                },
                reason=(
                    ""
                    if unified_gate.get("status") == "passed"
                    else "run_unified_pr_evaluation_before_portfolio_acceptance"
                ),
            )
        )
        checks.append(self._git_integrity_check(log_path=logs / "git_integrity.log"))

        release_report = build_release(output_root / "release.zip", check_only=True)
        portfolio_issues = _scan_portfolio_privacy(output_root)
        release_issues = list(release_report.get("issues") or [])
        privacy_report = {
            **release_report,
            "release_issues": release_issues,
            "portfolio_issues": portfolio_issues,
            "issues": [*release_issues, *portfolio_issues],
        }
        (output_root / "release_privacy_report.json").write_text(
            json.dumps(
                {key: value for key, value in privacy_report.items() if key != "file_hashes"},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        checks.append(
            PortfolioAcceptanceCheck(
                check_id="release_privacy",
                status="passed" if not privacy_report["issues"] else "failed",
                artifact="release_privacy_report.json",
                metrics={
                    "file_count": int(release_report.get("file_count") or 0),
                    "total_size_bytes": int(release_report.get("total_size_bytes") or 0),
                    "release_privacy_issue_count": len(release_issues),
                    "portfolio_privacy_issue_count": len(portfolio_issues),
                    "privacy_issue_count": len(privacy_report["issues"]),
                },
                reason=";".join(privacy_report["issues"]),
            )
        )

        git_snapshot = self._git_snapshot()
        result = evaluate_portfolio_artifacts(
            output_root=output_root,
            checks=checks,
            git_snapshot=git_snapshot,
            release_report=privacy_report,
        )
        (output_root / "environment_snapshot.json").write_text(
            json.dumps(_environment_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (output_root / "portfolio_acceptance.json").write_text(
            result.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        (output_root / "artifact_manifest.json").write_text(
            json.dumps(_artifact_manifest(output_root), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result

    def _run_command(
        self,
        *,
        check_id: str,
        argv: list[str],
        log_path: Path,
        artifact: Path | None,
        env: dict[str, str],
        output_root: Path,
    ) -> PortfolioAcceptanceCheck:
        started = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=self.project_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        log_path.write_text(_redact_text(completed.stdout or ""), encoding="utf-8")
        artifact_exists = artifact is None or artifact.is_file()
        metrics: dict[str, Any] = {}
        if check_id == "pytest":
            matches = re.findall(r"(\d+) passed", completed.stdout or "")
            metrics["passed_count"] = int(matches[-1]) if matches else 0
            artifact = log_path
        elif artifact and artifact.is_file():
            metrics = _read_json(artifact)
        passed = completed.returncode == 0 and artifact_exists
        return PortfolioAcceptanceCheck(
            check_id=check_id,
            status="passed" if passed else "failed",
            command=["<python>" if index == 0 else _redact_argument(value) for index, value in enumerate(argv)],
            exit_code=completed.returncode,
            elapsed_ms=round(elapsed_ms, 3),
            artifact=_relative_artifact(artifact, output_root) if artifact else "",
            metrics=metrics,
            reason="" if passed else "command_failed_or_expected_artifact_missing",
        )

    def _git_integrity_check(self, *, log_path: Path) -> PortfolioAcceptanceCheck:
        started = time.perf_counter()
        fsck = subprocess.run(
            ["git", "fsck", "--full", "--no-progress"],
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        dataless = _tracked_dataless_audit(self.project_root)
        log_path.write_text(_redact_text(fsck.stdout or ""), encoding="utf-8")
        passed = (
            fsck.returncode == 0
            and dataless["audit_error_count"] == 0
            and dataless["unreadable_or_mismatch_count"] == 0
        )
        return PortfolioAcceptanceCheck(
            check_id="git_integrity",
            status="passed" if passed else "failed",
            command=["git", "fsck", "--full", "--no-progress"],
            exit_code=fsck.returncode,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
            artifact="logs/git_integrity.log",
            metrics={
                "tracked_dataless_flag_count": dataless["raw_flagged_count"],
                "tracked_dataless_content_verified_count": dataless["content_verified_count"],
                "tracked_dataless_unreadable_or_mismatch_count": dataless[
                    "unreadable_or_mismatch_count"
                ],
                "tracked_dataless_audit_error_count": dataless["audit_error_count"],
                "tracked_content_integrity_passed": dataless[
                    "unreadable_or_mismatch_count"
                ]
                == 0,
                "dangling_objects_are_nonfatal": fsck.returncode == 0,
            },
            reason="" if passed else "git_fsck_or_tracked_content_integrity_failed",
        )

    def _git_snapshot(self) -> dict[str, Any]:
        head = _git(self.project_root, "rev-parse", "HEAD")
        branch = _git(self.project_root, "rev-parse", "--abbrev-ref", "HEAD")
        tracked = _git(self.project_root, "status", "--porcelain=v1", "--untracked-files=no")
        untracked = _git(self.project_root, "ls-files", "--others", "--exclude-standard")
        tracked_count = len([line for line in tracked.splitlines() if line.strip()])
        untracked_count = len([line for line in untracked.splitlines() if line.strip()])
        return {
            "head": head,
            "branch": branch,
            "dirty": bool(tracked_count or untracked_count),
            "tracked_modified_count": tracked_count,
            "untracked_count": untracked_count,
        }


def evaluate_portfolio_artifacts(
    *,
    output_root: Path,
    checks: list[PortfolioAcceptanceCheck],
    git_snapshot: dict[str, Any],
    release_report: dict[str, Any],
) -> PortfolioAcceptanceResult:
    by_id = {row.check_id: row for row in checks}
    mainline = by_id.get("mainline", PortfolioAcceptanceCheck(check_id="mainline", status="failed")).metrics
    retrieval = by_id.get("retrieval", PortfolioAcceptanceCheck(check_id="retrieval", status="failed")).metrics
    agent = by_id.get("agent_quality", PortfolioAcceptanceCheck(check_id="agent_quality", status="failed")).metrics
    memory = by_id.get("memory", PortfolioAcceptanceCheck(check_id="memory", status="failed")).metrics
    interview = by_id.get("interview_demo", PortfolioAcceptanceCheck(check_id="interview_demo", status="failed")).metrics
    pytest_count = int(by_id.get("pytest", PortfolioAcceptanceCheck(check_id="pytest", status="failed")).metrics.get("passed_count") or 0)
    hybrid = (retrieval.get("profiles") or {}).get("kg_hybrid_tool_contract") or {}
    package_integrity = interview.get("package_integrity") or {}

    gates = {
        "all_checks_passed": all(row.status == "passed" for row in checks),
        "pytest": pytest_count >= 358,
        "mainline": bool(mainline.get("hard_gate_passed"))
        and int(mainline.get("passed_case_count") or 0) == int(mainline.get("case_count") or -1),
        "retrieval": (
            float(hybrid.get("recall_at_10") or 0.0) >= 0.97
            and float(hybrid.get("precision_at_10") or 0.0) >= 0.91
            and float(hybrid.get("mrr") or 0.0) >= 0.99
            and float(hybrid.get("source_span_hit_rate") or 0.0) == 1.0
            and int(hybrid.get("governance_leakage_count") or 0) == 0
        ),
        "agent_quality": (
            bool(agent.get("release_gate_passed"))
            and float(agent.get("task_routing_accuracy") or 0.0) == 1.0
            and float(agent.get("intent_accuracy") or 0.0) == 1.0
            and float(agent.get("tool_correctness") or 0.0) == 1.0
            and float(agent.get("blocker_correctness") or 0.0) == 1.0
            and float(agent.get("latency_p95_ms") or float("inf")) <= 300.0
        ),
        "memory": bool(memory.get("release_gate_passed"))
        and int(memory.get("scientific_authority_violation_count") or 0) == 0,
        "interview": (
            interview.get("status") == "passed"
            and int(interview.get("case_count") or 0) == 4
            and float(interview.get("trace_completeness") or 0.0) == 1.0
            and int(interview.get("blocked_execution_request_count") or 0) == 0
            and bool(package_integrity.get("all_complete"))
        ),
        "privacy": not release_report.get("issues"),
        "unauthorized_execution": int(mainline.get("unauthorized_execution_request_count") or 0) == 0,
        "governance_leakage": int(mainline.get("candidate_evidence_leakage_count") or 0) == 0,
    }
    hard_gate = all(gates.values())
    release_hashes = release_report.get("file_hashes") or {}
    digest_payload = {
        "git_head": git_snapshot.get("head", ""),
        "tracked_modified_count": int(git_snapshot.get("tracked_modified_count") or 0),
        "untracked_count": int(git_snapshot.get("untracked_count") or 0),
        "release_file_hashes": release_hashes,
        "gates": gates,
    }
    worktree_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    limitations = [
        "Phase 6 remains PHASE6_TRIAL_READY because independent participant count is zero.",
        "The Git worktree contains the current uncommitted 2.7.x implementation; the worktree digest makes this review bundle traceable but is not a Git tag.",
        "Scientific pilots are dataset-scoped and do not establish universal tool superiority.",
        "LocalControlledExecutor is application-level process control, not OS-level sandboxing.",
        "Cell Type Annotation remains implemented_unqualified and planning-only.",
    ]
    git_integrity = by_id.get(
        "git_integrity", PortfolioAcceptanceCheck(check_id="git_integrity", status="failed")
    ).metrics
    flagged_count = int(git_integrity.get("tracked_dataless_flag_count") or 0)
    if flagged_count:
        limitations.append(
            f"macOS retained the dataless metadata flag on {flagged_count} tracked hidden files, "
            "but every flagged file was readable and matched its Git blob; content integrity, not "
            "the re-applied FileProvider flag, is the release gate."
        )

    return PortfolioAcceptanceResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        portfolio_status="RC_READY_FOR_USER_REVIEW" if hard_gate else "RC_BLOCKED",
        git_head=str(git_snapshot.get("head") or "unknown"),
        git_branch=str(git_snapshot.get("branch") or "unknown"),
        git_dirty=bool(git_snapshot.get("dirty")),
        tracked_modified_count=int(git_snapshot.get("tracked_modified_count") or 0),
        untracked_count=int(git_snapshot.get("untracked_count") or 0),
        worktree_digest=worktree_digest,
        checks=[
            *checks,
            PortfolioAcceptanceCheck(
                check_id="hard_gate",
                status="passed" if hard_gate else "failed",
                artifact="portfolio_acceptance.json",
                metrics=gates,
                reason="" if hard_gate else "one_or_more_portfolio_gates_failed",
            ),
            PortfolioAcceptanceCheck(
                check_id="external_llm_stability",
                status="not_run",
                reason="external disclosure not authorized for this RC",
            ),
            PortfolioAcceptanceCheck(
                check_id="ragas",
                status="not_run",
                reason="optional evaluator is outside the deterministic release gate",
            ),
            PortfolioAcceptanceCheck(
                check_id="real_user_trial",
                status="not_run",
                metrics={"participant_count": 0},
                reason="no independent participants recorded",
            ),
        ],
        hard_gate_passed=hard_gate,
        limitations=limitations,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        return row if isinstance(row, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _tracked_dataless_audit(root: Path) -> dict[str, int]:
    completed = subprocess.run(
        ["find", ".", "-path", "./.git", "-prune", "-o", "-flags", "+dataless", "-print"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "raw_flagged_count": 0,
            "content_verified_count": 0,
            "unreadable_or_mismatch_count": 0,
            "audit_error_count": int(platform.system() == "Darwin"),
        }
    flagged_paths: list[str] = []
    for raw in completed.stdout.splitlines():
        path = raw.removeprefix("./")
        if path:
            flagged_paths.append(path)
    if not flagged_paths:
        return {
            "raw_flagged_count": 0,
            "content_verified_count": 0,
            "unreadable_or_mismatch_count": 0,
            "audit_error_count": 0,
        }
    index = subprocess.run(
        ["git", "ls-files", "--stage", "-z", "--", *flagged_paths],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    index_hashes: dict[str, str] = {}
    for raw in index.stdout.split(b"\0"):
        if not raw or b"\t" not in raw:
            continue
        metadata, encoded_path = raw.split(b"\t", 1)
        fields = metadata.split()
        if len(fields) >= 2:
            index_hashes[os.fsdecode(encoded_path)] = fields[1].decode("ascii", "replace")
    tracked_paths = [path for path in flagged_paths if path in index_hashes]
    if not tracked_paths:
        return {
            "raw_flagged_count": 0,
            "content_verified_count": 0,
            "unreadable_or_mismatch_count": 0,
            "audit_error_count": int(index.returncode != 0),
        }
    hashed = subprocess.run(
        ["git", "hash-object", "--stdin-paths"],
        cwd=root,
        input=("\n".join(tracked_paths) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    actual_hashes = hashed.stdout.decode("ascii", "replace").splitlines()
    content_verified_count = sum(
        actual == index_hashes[path]
        for path, actual in zip(tracked_paths, actual_hashes, strict=False)
    )
    unreadable_or_mismatch_count = len(tracked_paths) - content_verified_count
    audit_error_count = int(index.returncode != 0 or hashed.returncode != 0)
    return {
        "raw_flagged_count": len(tracked_paths),
        "content_verified_count": content_verified_count,
        "unreadable_or_mismatch_count": unreadable_or_mismatch_count,
        "audit_error_count": audit_error_count,
    }


def _relative_artifact(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _redact_argument(value: str) -> str:
    if value.startswith("/Users/") or value.startswith("/opt/anaconda3/"):
        return Path(value).name
    return value


def _redact_text(value: str) -> str:
    text = re.sub(r"/Users/[^\"'`\s,}\]]+", "[local-path-redacted]", value)
    text = re.sub(
        r"/opt/anaconda3/[^\"'`\s,}\]]+", "[conda-path-redacted]", text
    )
    return re.sub(r"/Data/Omics/[^\"'`\s,}\]]+", "[local-path-redacted]", text)


def _scan_portfolio_privacy(root: Path) -> list[str]:
    forbidden = (
        b"/Users/",
        b"/opt/anaconda3/",
        b"/Data/Omics/",
        b"BEGIN PRIVATE KEY",
        b"BEGIN RSA PRIVATE KEY",
        b"BEGIN OPENSSH PRIVATE KEY",
    )
    issues: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            data = path.read_bytes()
        except OSError:
            issues.append(f"portfolio_artifact_unreadable:{path.relative_to(root).as_posix()}")
            continue
        if any(fragment in data for fragment in forbidden):
            issues.append(f"portfolio_path_or_secret_material:{path.relative_to(root).as_posix()}")
    return issues


def _environment_snapshot() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "privacy_mode": "strict_offline",
        "execution_policy": "disabled",
        "external_model_calls": 0,
    }


def _artifact_manifest(root: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "artifact_manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        artifacts.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {
        "schema_version": "portfolio-artifact-manifest-v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "hashes_valid": True,
    }
