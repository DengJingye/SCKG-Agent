"""Bounded real-input service smoke. No LLM, Notebook execution or input mutation.

The browser checkpoint is separate: this exercises the same upload, Research,
profile, planner and compiler services without claiming browser E2E coverage.
Every run has a new directory; failed and historical artifacts are preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")


def identity():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--",
         "app.py", "agent", "core", "engine", "execution", "observability", "capability_packs"],
        cwd=ROOT, text=True).splitlines()
    return {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "source_sha256": {p: sha(ROOT / p) for p in sorted(set(paths)) if (ROOT / p).is_file()},
    }


def run(args):
    # Explicit request-scoped offline policy is also supplied to Research below.
    os.environ["SCKG_EXTERNAL_NETWORK_ALLOWED"] = "false"
    os.environ["SCKG_PRIVACY_MODE"] = "strict_offline"
    from agent.research_chat_service import ResearchChatService
    from core.capability_workspace_models import CapabilityWorkspaceRequest
    from core.research_agent_models import ResearchAgentRequest
    from core.trace_context import TraceCollector
    from engine.capability_workspace_service import CapabilityWorkspaceService
    from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
    from execution.data_registry import DataRegistry
    from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
    from execution.research_input_binding import (
        authorize_uploaded_binding, register_upload, select_registered_input, switch_conversation,
    )

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    storage = ROOT / ".sckg_exec" / "midterm-input-binding" / out.name
    storage.mkdir(parents=True, exist_ok=False)
    (storage / "inputs").mkdir()
    sources = {"raw": args.raw.resolve(), "processed": args.processed.resolve()}
    before = {name: {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
              for name, path in sources.items()}
    preflight = {"started_at": datetime.now(timezone.utc).isoformat(), **identity(),
                 "inputs": before, "scope": "real_data_offline_service_integration",
                 "real_llm": False, "browser_replay": False, "notebook_execution": False,
                 "storage": str(storage), "script_sha256": sha(__file__)}
    write(out / "preflight.json", preflight)
    reg = DataRegistry(approved_input_roots=[storage / "inputs"], registry_root=storage / "registry")
    collector = TraceCollector(out / "traces.jsonl")
    research = ResearchChatService(data_registry=reg, dense_default_enabled=False, trace_collector=collector)
    workspace = CapabilityWorkspaceService(data_registry=reg, trace_collector=collector,
        notebook_compiler=GenericNotebookCompiler(NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])))
    bindings, results, checks = {}, [], []
    error = None
    try:
        for name, path in sources.items():
            bindings[name] = register_upload(reg, user_id="sprint-audit", filename="same.h5ad", content=path.read_bytes())
            assert bindings[name]["sha256"] == before[name]["sha256"]
            assert bindings[name]["shape"] == ({"raw": [2700, 32738], "processed": [2638, 1838]}[name])
        assert bindings["raw"]["artifact_id"] != bindings["processed"]["artifact_id"]
        checks.append({"check": "same_name_distinct_content", "pass": True})
        state = {}
        query = "请根据当前已绑定数据的真实状态生成 Scanpy Core 分析计划，复用有效表示，交接到 Stepwise；只做画像与 PLAN，不执行。"
        for index, name in enumerate(("raw", "processed", "raw")):
            switch_conversation(state, name)
            binding = bindings[name]
            if index < 2:
                assert "workspace_artifact_id" not in state
            else:
                assert state["workspace_artifact_id"] == binding["artifact_id"]
            state["workspace_artifact_id"] = binding["artifact_id"]
            authorize_uploaded_binding(reg, binding, user_id="sprint-audit")
            request = ResearchAgentRequest(request_id=f"binding-{out.name}-{index}", conversation_id=name,
                user_id="sprint-audit", artifact_id=binding["artifact_id"], query=query)
            response = research.run_request(request, user_runtime_config={
                "privacy_mode": "strict_offline", "privacy_authorized": False, "outbound_authorized": False})
            write(out / f"{index}-{name}-research.json", response.model_dump(mode="json"))
            handoff = response.workspace_handoff
            assert handoff.status == "available", handoff
            assert response.execution_handoff.artifact_id == binding["artifact_id"]
            assert response.execution_handoff.execution_request_count == 0
            request2 = CapabilityWorkspaceRequest(request_id=f"workspace-{out.name}-{index}",
                user_id="sprint-audit", artifact_id=binding["artifact_id"], requirement_id=f"requirement-{index}",
                pack_id=handoff.pack_id, pack_version=handoff.pack_version,
                target_representations=handoff.target_representations, preferred_method_ids=handoff.preferred_method_ids,
                origin_trace_id=handoff.origin_trace_id, handoff_id=handoff.handoff_id,
                parent_request_id=handoff.parent_request_id, mode="PLAN")
            notebook = storage / f"{index}-{name}.ipynb"
            result = workspace.prepare(request2, notebook_path=notebook)
            write(out / f"{index}-{name}-workspace.json", result.model_dump(mode="json"))
            assert result.data_profile.file_hash == binding["sha256"]
            assert [result.data_profile.n_cells, result.data_profile.n_genes] == binding["shape"]
            assert result.status == "planned", result.blockers
            nb = json.loads(notebook.read_text())
            code = "\n".join("".join(c["source"]) for c in nb["cells"])
            assert binding["sha256"] in code and "scanpy_core_synthetic" not in code
            assert nb["metadata"]["sckg"]["plan_id"] == result.workflow_plan.plan_id
            assert all(not c.get("outputs") and c.get("execution_count") is None for c in nb["cells"])
            for cell in nb["cells"]:
                if cell["cell_type"] == "code":
                    compile("".join(cell["source"]), notebook.name, "exec")
            assert result.execution_request_count == 0
            state["capability_workspace_result"] = result.model_dump(mode="json")
            results.append({"order": index, "dataset": name, "binding": binding,
                "plan_id": result.workflow_plan.plan_id, "steps": [s.operation for s in result.workflow_plan.steps],
                "notebook": str(notebook), "notebook_sha256": sha(notebook),
                "profile_shape": binding["shape"], "trace_id": result.canonical_trace_id,
                "PLAN_COMPILED": True, "NOTEBOOK_COMPILED": True, "NOTEBOOK_EXECUTED": False,
                "CANDIDATE_TERMINAL_SATISFIED": None, "HUMAN_CONFIRMATION_COMPLETED": False,
                "FULL_SCIENTIFIC_TASK_COMPLETED": False})
        checks.append({"check": "A_B_A_isolation", "pass": True, "transitions": 2})
        switch_conversation(state, "empty")
        assert "workspace_artifact_id" not in state and "capability_workspace_result" not in state
        checks.append({"check": "empty_conversation_unbound", "pass": True})
        restarted = DataRegistry(approved_input_roots=reg.approved_input_roots, registry_root=reg.registry_root)
        for binding in bindings.values():
            restored = select_registered_input(restarted, artifact_id=binding["artifact_id"], user_id="sprint-audit")
            assert restored["sha256"] == binding["sha256"] and restored["shape"] == binding["shape"]
        checks.append({"check": "explicit_selection_after_restart", "pass": True})
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    unchanged = {name: sha(path) == before[name]["sha256"] for name, path in sources.items()}
    sources_unchanged = all(sha(ROOT / p) == value for p, value in preflight["source_sha256"].items())
    passed = error is None and all(unchanged.values()) and sources_unchanged and len(results) == 3
    summary = {"status": "PASS" if passed else "FAIL", "classification": "CURRENT_MEASURED",
        "scope": preflight["scope"], "real_llm": False, "browser_replay": False,
        "results": results, "checks": checks, "input_integrity": unchanged, "source_integrity": sources_unchanged,
        "INPUT_BINDING_CORRECT": passed, "CROSS_SESSION_LEAKAGE": 0 if passed else None,
        "SYNTHETIC_FALLBACK_WITHOUT_EXPLICIT_USER_CHOICE": 0 if passed else None,
        "error": error, "finished_at": datetime.now(timezone.utc).isoformat(),
        "limitations": ["No browser upload events exercised here; multiple-file UI behavior is separate.",
                         "No LLM proposal accuracy or scientific completion claim."]}
    write(out / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "output": str(out), "error": error}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
