from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from execution.model_pack_manager import ModelPackManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local retrieval-bge-m3 pack.")
    parser.add_argument("command", choices=["plan", "install", "probe", "remove"])
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    manager = ModelPackManager()
    if args.command == "probe":
        payload = manager.probe().model_dump(mode="json")
    elif args.command == "plan":
        payload = manager.create_plan().model_dump(mode="json")
    elif args.command == "install":
        plan = manager.create_plan()
        if not args.approve:
            payload = {
                "status": "waiting_approval",
                "plan": plan.model_dump(mode="json"),
                "instruction": "rerun with install --approve after reviewing the plan",
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        approval = manager.approve(plan)
        record = manager.install(plan, approval)
        payload = record.model_dump(mode="json")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if record.state == "ready" else 1
    else:
        if not args.approve:
            print(json.dumps({"status": "waiting_approval", "operation": "remove"}))
            return 2
        manager.remove()
        payload = {"status": "removed"}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
