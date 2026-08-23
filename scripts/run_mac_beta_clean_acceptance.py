from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.runtime_pack_models import (
    ControlPlaneReleaseManifest,
    RuntimePackAcceptanceItem,
    RuntimePackAcceptanceResult,
    RuntimePackInstallTelemetry,
    RuntimePackState,
)
from execution.runtime_pack_manager import RuntimePackManager
from scripts.build_local_release import build_release
from scripts.build_release_inventory import build_inventory


PACK_IDS = ("doublet-python", "doublet-r", "batch-cpu")


def _size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _telemetry(record, manifest) -> RuntimePackInstallTelemetry:
    return RuntimePackInstallTelemetry(
        record_id=record.record_id,
        pack_id=record.pack_id,
        manifest_digest=record.manifest_digest,
        state=record.state,
        elapsed_ms=record.elapsed_ms,
        cache_size_before_bytes=record.cache_size_before_bytes,
        cache_size_after_bytes=record.cache_size_after_bytes,
        cache_growth_bytes=(
            record.cache_size_after_bytes - record.cache_size_before_bytes
        ),
        installed_logical_size_bytes=record.installed_size_bytes,
        installed_physical_size_bytes=record.installed_physical_size_bytes,
        allowed_install_hosts=manifest.allowed_install_hosts,
        smoke_passed=record.smoke_passed,
        error_code=record.error_code,
    )


def _install_once(manager: RuntimePackManager, pack_id: str):
    plan = manager.create_plan(pack_id=pack_id, user_id="maintainer-acceptance")
    if plan.blockers:
        raise RuntimeError(f"{pack_id} plan blocked: {','.join(plan.blockers)}")
    approval = manager.approvals.approve(
        plan_id=plan.plan_id,
        user_id=plan.user_id,
        confirmation_text=manager.approvals.confirmation_text(plan),
    )
    return manager.provision(
        plan_id=plan.plan_id,
        approval_id=approval.approval_id,
    )


def _bootstrap_control_plane(home: Path, report_dir: Path) -> tuple[bool, list[str]]:
    command = [
        str(PROJECT_ROOT / "release" / "bootstrap" / "install_sckg.command"),
        "--accept-reviewed-install",
    ]
    env = {
        **os.environ,
        "SCKG_HOME": str(home),
        "SCKG_PRIVACY_MODE": "strict_offline",
        "SCKG_EXTERNAL_NETWORK_ALLOWED": "false",
    }
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=7_200,
    )
    (report_dir / "control-plane.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    (report_dir / "control-plane.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    blockers = [] if completed.returncode == 0 else [
        f"control_plane_bootstrap_failed:{completed.returncode}"
    ]
    return completed.returncode == 0, blockers


def _core_cold_start(home: Path, report_dir: Path) -> tuple[bool, dict]:
    python = home / "control-plane" / "bin" / "python"
    if not python.is_file():
        return False, {"error": "control_plane_python_missing"}
    env = {
        **os.environ,
        "SCKG_HOME": str(home),
        "SCKG_PRIVACY_MODE": "strict_offline",
        "SCKG_EXTERNAL_NETWORK_ALLOWED": "false",
        "SCKG_OFFLINE_LLM": "true",
        "SCKG_ALLOW_LEGACY_ENVIRONMENTS": "false",
        "PYTHONNOUSERSITE": "1",
    }
    completed = subprocess.run(
        [str(python), str(PROJECT_ROOT / "scripts" / "run_core_cold_start_smoke.py")],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    (report_dir / "core-cold-start.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"error": "core_cold_start_invalid_json"}
    (report_dir / "core-cold-start.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return completed.returncode == 0 and bool(payload.get("passed")), payload


def run_acceptance(
    *,
    home: Path,
    report_dir: Path,
    install_reviewed_packs: bool,
    remove_rebuild: bool,
    second_machine_attested: bool,
    resume_report: Path | None = None,
) -> RuntimePackAcceptanceResult:
    report_dir.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    manifest = ControlPlaneReleaseManifest.model_validate_json(
        (PROJECT_ROOT / "release" / "control-plane-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    previous: RuntimePackAcceptanceResult | None = None
    if resume_report is not None:
        previous = RuntimePackAcceptanceResult.model_validate_json(
            resume_report.read_text(encoding="utf-8")
        )
    if home.exists() and any(home.iterdir()) and previous is None:
        blockers.append("acceptance_home_not_empty")

    control_ready = False
    cold_start_passed = False
    cold_start_payload: dict = {}
    if not blockers and install_reviewed_packs:
        if previous is not None:
            control_ready = (home / "control-plane" / "bin" / "python").is_file()
            cold_start_passed = previous.core_cold_start_passed
            cold_start_path = report_dir / "core-cold-start.json"
            if cold_start_path.is_file():
                cold_start_payload = json.loads(cold_start_path.read_text(encoding="utf-8"))
        else:
            control_ready, bootstrap_blockers = _bootstrap_control_plane(home, report_dir)
            blockers.extend(bootstrap_blockers)
            if control_ready:
                cold_start_passed, cold_start_payload = _core_cold_start(home, report_dir)
                if not cold_start_passed:
                    blockers.append("core_cold_start_failed")
    else:
        blockers.append("actual_clean_install_not_requested")

    pack_results: list[RuntimePackAcceptanceItem] = []
    micromamba = home / "micromamba" / "bin" / "micromamba"
    if control_ready and micromamba.is_file():
        os.environ["SCKG_MICROMAMBA_EXE"] = str(micromamba)
        manager = RuntimePackManager(
            home=home,
            allow_legacy_environments=False,
        )
        previous_items = {
            item.pack_id: item for item in (previous.pack_results if previous else [])
        }
        for pack_id in PACK_IDS:
            initial = manager.probe(pack_id)
            previous_item = previous_items.get(pack_id)
            if (
                previous_item is not None
                and previous_item.installed_from_lock
                and previous_item.remove_rebuild_passed
                and initial.ready
            ):
                pack_results.append(previous_item)
                continue
            telemetry: list[RuntimePackInstallTelemetry] = list(
                previous_item.telemetry if previous_item else []
            )
            item_blockers: list[str] = []
            record = _install_once(manager, pack_id)
            telemetry.append(_telemetry(record, manager.registry.get(pack_id)))
            if not record.smoke_passed or record.state != RuntimePackState.READY:
                item_blockers.append(record.error_code or "pack_install_failed")
            rebuild_passed = False
            if remove_rebuild and not item_blockers:
                manager.remove(
                    pack_id=pack_id,
                    confirmation_text=f"REMOVE {pack_id}",
                )
                rebuilt = _install_once(manager, pack_id)
                telemetry.append(_telemetry(rebuilt, manager.registry.get(pack_id)))
                rebuild_passed = (
                    rebuilt.smoke_passed
                    and rebuilt.state == RuntimePackState.READY
                )
                if not rebuild_passed:
                    item_blockers.append(
                        rebuilt.error_code or "pack_remove_rebuild_failed"
                    )
            final = manager.probe(pack_id)
            pack_results.append(
                RuntimePackAcceptanceItem(
                    pack_id=pack_id,
                    initial_state=(
                        previous_item.initial_state if previous_item else initial.state
                    ),
                    final_state=final.state,
                    installed_from_lock=(
                        final.ready
                        and record.smoke_passed
                        and record.manifest_digest
                        == manager.registry.get(pack_id).manifest_digest
                    ),
                    remove_rebuild_passed=rebuild_passed,
                    telemetry=telemetry,
                    blockers=item_blockers,
                )
            )
            blockers.extend(f"{pack_id}:{reason}" for reason in item_blockers)
    elif install_reviewed_packs:
        blockers.append("pinned_micromamba_missing_after_bootstrap")

    sbom, licenses = build_inventory()
    (PROJECT_ROOT / "release" / "sbom.cdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PROJECT_ROOT / "release" / "license-inventory.json").write_text(
        json.dumps(licenses, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    release_report = build_release(
        PROJECT_ROOT / "dist" / "sckg-local-workbench-mac-arm64-beta.zip"
    )
    release_passed = not release_report["issues"]
    if not release_passed:
        blockers.extend(release_report["issues"])

    pack_gate = (
        len(pack_results) == len(PACK_IDS)
        and all(item.installed_from_lock for item in pack_results)
        and (not remove_rebuild or all(item.remove_rebuild_passed for item in pack_results))
    )
    cache_relocation = home.resolve() != (Path.home() / ".sckg").resolve()
    first_launch_size = _size(home / "control-plane") + int(
        release_report.get("total_size_bytes", 0)
    )
    if first_launch_size > manifest.max_first_launch_size_bytes:
        blockers.append("first_launch_size_limit_exceeded")
    if not pack_gate:
        blockers.append("runtime_pack_clean_install_gate_failed")

    technical_gate = all(
        [
            control_ready,
            cold_start_passed,
            pack_gate,
            cache_relocation,
            release_passed,
            first_launch_size <= manifest.max_first_launch_size_bytes,
        ]
    )
    if technical_gate and second_machine_attested:
        status = "clean_machine_accepted"
    elif technical_gate:
        status = "release_candidate"
        blockers.append("second_clean_apple_silicon_attestation_missing")
    else:
        status = "blocked"

    result = RuntimePackAcceptanceResult(
        acceptance_id=f"mac-beta-{uuid.uuid4().hex}",
        platform=manager.registry.current_platform_tag() if control_ready else "osx-arm64",
        isolated_home_redacted="[isolated-sckg-home]",
        legacy_fallback_disabled=True,
        core_cold_start_passed=cold_start_passed,
        pack_results=pack_results,
        cache_relocation_passed=cache_relocation,
        release_archive_passed=release_passed,
        release_size_bytes=int(release_report.get("archive_size_bytes", 0)),
        first_launch_size_bytes=first_launch_size,
        privacy_issue_count=len(release_report["issues"]),
        status=status,
        blockers=sorted(set(blockers)),
        created_at=datetime.now(timezone.utc),
    )
    (report_dir / "mac-beta-acceptance.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (report_dir / "mac-beta-acceptance.md").write_text(
        _markdown_summary(result, cold_start_payload), encoding="utf-8"
    )
    return result


def _markdown_summary(result: RuntimePackAcceptanceResult, cold_start: dict) -> str:
    lines = [
        "# Mac Beta clean-prefix acceptance",
        "",
        f"Status: `{result.status}`",
        "",
        f"- Core cold start: `{result.core_cold_start_passed}`",
        f"- Release archive: `{result.release_archive_passed}`",
        f"- First-launch bytes: `{result.first_launch_size_bytes}`",
        f"- Privacy issues: `{result.privacy_issue_count}`",
        f"- Catalog tools: `{cold_start.get('catalog_tool_count', 0)}`",
        "",
        "## Runtime Packs",
        "",
    ]
    for item in result.pack_results:
        lines.append(
            f"- `{item.pack_id}`: `{item.final_state}`, from lock "
            f"`{item.installed_from_lock}`, rebuild `{item.remove_rebuild_passed}`"
        )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- `{reason}`" for reason in result.blockers)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated Apple Silicon beta acceptance")
    default_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument(
        "--home",
        type=Path,
        default=PROJECT_ROOT / ".sckg_exec" / "acceptance" / f"mac-beta-{default_id}" / "home",
    )
    parser.add_argument("--install-reviewed-packs", action="store_true")
    parser.add_argument("--remove-rebuild", action="store_true")
    parser.add_argument("--second-machine-attested", action="store_true")
    parser.add_argument("--resume-report", type=Path)
    args = parser.parse_args()
    report_dir = args.home.parent / "report"
    started = time.perf_counter()
    result = run_acceptance(
        home=args.home.expanduser().resolve(),
        report_dir=report_dir,
        install_reviewed_packs=args.install_reviewed_packs,
        remove_rebuild=args.remove_rebuild,
        second_machine_attested=args.second_machine_attested,
        resume_report=args.resume_report,
    )
    payload = result.model_dump(mode="json")
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    payload["report_path"] = str(report_dir / "mac-beta-acceptance.json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if result.status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
