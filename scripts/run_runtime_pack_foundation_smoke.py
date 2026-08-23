from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.deterministic_router import DeterministicRouter, RouterRoute
from core.privacy_policy import OutboundDisclosureService, PrivacyMode
from execution.runtime_pack_manager import RuntimePackManager
from scripts.build_local_release import collect_release_files, load_release_manifest, validate_release
from tests.runtime_pack_helpers import build_test_registry


def main() -> int:
    installed_manager = RuntimePackManager()
    inventory = installed_manager.inventory()
    with tempfile.TemporaryDirectory(prefix="sckg-runtime-smoke-") as temporary:
        root = Path(temporary)
        missing_manager = RuntimePackManager(
            registry=build_test_registry(root), home=root / "home"
        )
        probe = missing_manager.probe("test-pack")
        route = DeterministicRouter().route_runtime_pack(
            probe=probe,
            parent_route_override=RouterRoute.RESTRICTED_USER_EXECUTION,
        )
        plan = missing_manager.create_plan(pack_id="test-pack", user_id="smoke-user")
        privacy = OutboundDisclosureService()
        disclosure = privacy.prepare(
            {"query": "plan doublet detection", "matrix": [[1, 2]]},
            purpose="smoke",
            provider="none",
        )
        privacy_decision = privacy.authorize(
            mode=PrivacyMode.STRICT_OFFLINE,
            disclosure_hash=disclosure.disclosure.disclosure_hash,
            session_id="smoke",
            consent_id=None,
        )
    manifest = load_release_manifest()
    release = validate_release(collect_release_files(manifest), manifest)
    summary = {
        "ok": bool(
            len(inventory) == 3
            and all(item.ready for item in inventory)
            and route.route == RouterRoute.WAITING_ENVIRONMENT_APPROVAL
            and route.parent_override_ignored
            and not plan.blockers
            and not privacy_decision.allowed
            and not release["issues"]
        ),
        "installed_runtime_packs": [
            {
                "pack_id": item.pack_id,
                "state": item.state,
                "source": item.source,
                "logical_size_bytes": item.logical_size_bytes,
            }
            for item in inventory
        ],
        "missing_pack_route": route.route,
        "execution_request_count": 0,
        "environment_approval_required": plan.approval_required,
        "strict_offline_external_calls": 0,
        "release_size_bytes": release["total_size_bytes"],
        "release_issues": release["issues"],
        "network_not_os_isolated": True,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
