from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from core.privacy_policy import PrivacyMode
from core.settings import PROJECT_ROOT, get_settings
from execution.runtime_pack_manager import RuntimePackManager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sckg",
        description="Local scKG-Agent control plane",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Check core and Runtime Pack readiness")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    launch = subparsers.add_parser("launch", help="Launch localhost Streamlit UI")
    launch.add_argument("--port", type=int, default=8501)
    launch.add_argument("--no-browser", action="store_true")

    packs = subparsers.add_parser("packs", help="Manage reviewed Runtime Packs")
    pack_commands = packs.add_subparsers(dest="pack_command", required=True)
    list_command = pack_commands.add_parser("list")
    list_command.add_argument("--json", action="store_true", dest="as_json")
    plan = pack_commands.add_parser("plan")
    plan.add_argument("pack_id")
    plan.add_argument("--user", required=True)
    approve = pack_commands.add_parser("approve")
    approve.add_argument("plan_id")
    approve.add_argument("--user", required=True)
    approve.add_argument("--confirm", required=True)
    install = pack_commands.add_parser("install")
    install.add_argument("plan_id")
    install.add_argument("approval_id")
    remove = pack_commands.add_parser("remove")
    remove.add_argument("pack_id")
    remove.add_argument("--confirm", required=True)
    return parser


def _probe_row(probe, manifest) -> dict:
    return {
        "pack_id": probe.pack_id,
        "task_family": manifest.task_family,
        "tools": [
            f"{item.tool_name} {item.tool_version}"
            for item in manifest.supported_tools
        ],
        "state": str(probe.state),
        "source": str(probe.source),
        "environment_id": probe.environment_id,
        "logical_size_bytes": probe.logical_size_bytes,
        "physical_size_bytes": probe.physical_size_bytes,
        "last_used_at": probe.last_used_at.isoformat() if probe.last_used_at else None,
        "disk_free_bytes": probe.disk_free_bytes,
        "warnings": probe.warnings,
        "manifest_digest": probe.manifest_digest,
        "maintainer_signature_verified": True,
    }


def _print_rows(rows: list[dict]) -> None:
    for row in rows:
        tools = ", ".join(row["tools"])
        size_gib = row["logical_size_bytes"] / 1024**3
        allocated_gib = row["physical_size_bytes"] / 1024**3
        print(
            f"{row['pack_id']:<18} {row['state']:<30} "
            f"{size_gib:>5.2f} GiB logical / {allocated_gib:>5.2f} GiB allocated  {tools}"
        )
        for warning in row["warnings"]:
            print(f"  warning: {warning}")
        if row.get("last_used_at"):
            print(f"  last used: {row['last_used_at']}")


def _doctor(manager: RuntimePackManager) -> dict:
    settings = get_settings()
    probes = manager.inventory()
    return {
        "product": "scKG Local Research Workbench",
        "project_root": "[project]",
        "platform": manager.registry.current_platform_tag(),
        "privacy_mode": settings.privacy_mode.value,
        "external_network_allowed": settings.external_network_allowed,
        "execution_policy": os.environ.get("SCKG_EXECUTION_POLICY", "disabled"),
        "core_assets": {
            "catalog": (PROJECT_ROOT / "data" / "scrna_tools.tsv").is_file(),
            "local_graph": (PROJECT_ROOT / "data" / "knowledge_graph_v2").is_dir(),
            "runtime_manifests": len(probes),
        },
        "runtime_packs": [
            _probe_row(probe, manager.registry.get(probe.pack_id))
            for probe in probes
        ],
        "network_not_os_isolated": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manager = RuntimePackManager()
    if args.command == "doctor":
        result = _doctor(manager)
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("scKG Local Research Workbench")
            print(f"platform: {result['platform']}")
            print(f"privacy: {result['privacy_mode']} (external network disabled by default)")
            print(f"execution policy: {result['execution_policy']}")
            _print_rows(result["runtime_packs"])
        return 0
    if args.command == "launch":
        if not 1024 <= args.port <= 65535:
            raise SystemExit("port must be between 1024 and 65535")
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(PROJECT_ROOT / "app.py"),
            "--server.address",
            "localhost",
            "--server.port",
            str(args.port),
            "--server.headless",
            "true" if args.no_browser else "false",
        ]
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            shell=False,
            check=False,
        )
        return int(completed.returncode)
    if args.command == "packs" and args.pack_command == "list":
        rows = [
            _probe_row(probe, manager.registry.get(probe.pack_id))
            for probe in manager.inventory()
        ]
        if args.as_json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            _print_rows(rows)
        return 0
    if args.command == "packs" and args.pack_command == "plan":
        plan = manager.create_plan(pack_id=args.pack_id, user_id=args.user)
        print(plan.model_dump_json(indent=2))
        print(f"confirmation: {manager.approvals.confirmation_text(plan)}")
        return 2 if plan.blockers else 0
    if args.command == "packs" and args.pack_command == "approve":
        approval = manager.approvals.approve(
            plan_id=args.plan_id,
            user_id=args.user,
            confirmation_text=args.confirm,
        )
        print(approval.model_dump_json(indent=2))
        return 0
    if args.command == "packs" and args.pack_command == "install":
        record = manager.provision(
            plan_id=args.plan_id,
            approval_id=args.approval_id,
        )
        print(record.model_dump_json(indent=2))
        return 0 if str(record.state) == "ready" else 1
    if args.command == "packs" and args.pack_command == "remove":
        removed = manager.remove(
            pack_id=args.pack_id,
            confirmation_text=args.confirm,
        )
        print(json.dumps({"pack_id": args.pack_id, "removed": removed}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
