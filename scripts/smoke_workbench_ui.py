"""Standalone full-app Streamlit smoke on a new synthetic workspace.

Requires the pinned Streamlit 1.56.0 environment; no pytest, provider, science
runtime or existing workspace is used. Python call guards and application
configuration are not an operating-system sandbox. The caller should supervise
time/memory separately. Existing workspaces and output files are never replaced.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_bootstrap_spec = spec_from_file_location("sckg_public_workflow_demo_bootstrap",
                                         ROOT / "scripts" / "bootstrap_workflow_demo.py")
_bootstrap = module_from_spec(_bootstrap_spec)
_bootstrap_spec.loader.exec_module(_bootstrap)
bootstrap_demo = _bootstrap.bootstrap_demo


class ProbeFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ProbeFailure(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def widget(collection, *, label=None, key=None):
    matches = [item for item in collection if (label is None or item.label == label)
               and (key is None or getattr(item, "key", None) == key)]
    require(len(matches) == 1, f"Expected one widget label={label!r}, key={key!r}; found {len(matches)}")
    return matches[0]


def visible_text(app):
    return "\n".join(str(item.value) for name in
        ("text", "markdown", "code", "caption", "info", "warning", "subheader", "title")
        for item in getattr(app, name))


def healthy(app, report, phase):
    observation = {"phase": phase, "titles": [str(item.value) for item in app.title],
        "errors": [str(item.value) for item in app.error],
        "exceptions": [str(item.value) for item in app.exception],
        "info_count": len(app.info), "warning_count": len(app.warning)}
    report["ui_observations"].append(observation)
    # render_app deliberately catches exceptions into st.error. Both surfaces
    # must be checked; an empty app.exception alone cannot establish success.
    require(not observation["exceptions"], f"AppTest exception in {phase}: {observation['exceptions']}")
    require(not observation["errors"], f"Rendered st.error in {phase}: {observation['errors']}")


def database_snapshot(ledger):
    from sckg_workbench.storage import canonical_json, content_hash

    def value(cell):
        if isinstance(cell, bytes):
            return {"blob_sha256": hashlib.sha256(cell).hexdigest(), "bytes": len(cell)}
        return cell

    with ledger.connect() as connection:
        schema = [list(row) for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        tables = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(canonical_json([value(cell) for cell in row])
                          for row in connection.execute("SELECT * FROM " + quoted))
            tables[name] = {"row_count": len(rows), "rows_hash": content_hash(rows)}
        kinds = {row[0]: row[1] for row in connection.execute(
            "SELECT kind,COUNT(*) FROM records GROUP BY kind ORDER BY kind")}
    files = {str(path.relative_to(ledger.workspace.root)): sha256(path)
        for path in sorted(ledger.workspace.root.rglob("*"))
        if path.is_file() and path.name not in {"ledger.sqlite3", "ledger.sqlite3-wal", "ledger.sqlite3-shm"}}
    return {"schema_hash": content_hash(schema), "tables": tables, "record_kinds": kinds,
            "non_database_files": files}


def offline_guards(stack, attempts):
    from sckg_workbench import analysis, chat, datasets, model_service, sources, worker

    def forbidden(name):
        def stop(*args, **kwargs):
            attempts[name] = attempts.get(name, 0) + 1
            raise ProbeFailure("Offline UI probe attempted forbidden operation: " + name)
        return stop

    targets = (
        (model_service.ModelService, "invoke", "model.invoke"),
        (model_service.ModelService, "embed", "model.embed"),
        (model_service, "http_transport", "network.model_http"),
        (sources, "fetch_public_url", "network.source_fetch"),
        (socket, "create_connection", "network.create_connection"),
        (socket, "getaddrinfo", "network.getaddrinfo"),
        (socket.socket, "connect", "network.socket_connect"),
        (socket.socket, "connect_ex", "network.socket_connect_ex"),
        (chat.ChatService, "submit_send", "chat.submit_send"),
        (chat.ChatService, "send", "chat.send"),
        (worker.Worker, "submit_ingestion", "worker.submit_ingestion"),
        (worker.Worker, "run_once", "worker.run_once"),
        (analysis.AnalysisService, "submit_scrublet", "science.submit_scrublet"),
        (analysis.AnalysisService, "run_once", "science.run_once"),
        (datasets.DatasetService, "register_local", "data.register_local"),
        (datasets.DatasetService, "profile", "data.profile"),
    )
    for owner, method, name in targets:
        attempts[name] = 0
        stack.enter_context(patch.object(owner, method, forbidden(name)))


def run_probe(workspace_path, report):
    # Telemetry configuration is set before importing Streamlit. Call guards
    # below cover the in-process probe; this is not a network/process sandbox.
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "STREAMLIT_SERVER_FILE_WATCHER_TYPE": "none"}))
        import streamlit
        require(streamlit.__version__ == "1.56.0",
                "Requires pinned Streamlit 1.56.0; observed " + streamlit.__version__)
        report["runtime"] = {"python": sys.version, "executable": sys.executable,
                             "streamlit": streamlit.__version__, "streamlit_file": streamlit.__file__}
        streamlit.config.set_option("browser.gatherUsageStats", False)
        from streamlit.testing.v1 import AppTest
        from sckg_workbench.storage import Ledger, Workspace, content_hash
        from sckg_workbench.ui import PAGES
        from sckg_workbench.workflow_inputs import WorkflowInputService

        offline_guards(stack, report["forbidden_attempts"])
        report["stage"] = "synthetic_bootstrap"
        receipt = bootstrap_demo(workspace_path)
        report["bootstrap"] = receipt
        ledger = Ledger(Workspace(Path(receipt["workspace"])))
        bootstrap_snapshot = database_snapshot(ledger)
        stack.enter_context(patch.dict(os.environ, {"SCKG_WORKBENCH_HOME": str(ledger.workspace.root)}))
        require(len(PAGES) == 7, "Expected the seven public application pages")
        report["stage"] = "seven_pages"
        app_path = ROOT / "workbench_app.py"
        require(app_path.is_file(), "Missing full application entry point")
        app = AppTest.from_file(str(app_path), default_timeout=15).run()
        healthy(app, report, "initial_full_application")
        require(widget(app.radio, key="navigation").options == list(PAGES), "Navigation differs from ui.PAGES")
        visited = []
        for page in PAGES:
            widget(app.radio, key="navigation").set_value(page).run()
            healthy(app, report, "page:" + page)
            require(any(item.value == page for item in app.title), "Missing real page title: " + page)
            visited.append(page)
            if page == "质量评测":
                require({"待审任务格", "可用于推荐的正式知识"}.issubset({m.label for m in app.metric}),
                        "Quality page did not build its actual coverage metrics")
                require("正式对照成绩：未产生" in visible_text(app),
                        "Quality page did not execute the scientific-readiness view")
                dependencies = {}
                for name in ("eval.workbench_snapshot", "eval.scientific_value_registry"):
                    module = sys.modules.get(name)
                    expected = ROOT / (name.replace(".", "/") + ".py")
                    require(module is not None and Path(module.__file__).resolve() == expected.resolve(),
                            "Quality dependency did not load from this checkout: " + name)
                    dependencies[name] = {"path": str(expected), "sha256": sha256(expected)}
                fixture = ROOT / "eval" / "fixtures" / "genpilot_sckg_eval_v1.json"
                require(fixture.is_file(), "Missing actual quality-page development fixture")
                dependencies["development_fixture"] = {"path": str(fixture), "sha256": sha256(fixture)}
                report["quality_dependencies"] = dependencies
        report["pages_visited"] = visited

        report["stage"] = "developer_option"
        widget(app.radio, key="navigation").set_value("研究台").run()
        healthy(app, report, "developer_option_visible")
        option = widget(app.checkbox, key="research_workflow_enabled")
        require(option.label == "开发流程对话：按来源检查输入" and not option.disabled,
                "The explicit developer workflow option is unavailable")
        option.set_value(True).run()
        healthy(app, report, "developer_option_enabled_without_send")
        require(widget(app.checkbox, key="research_use_knowledge").disabled,
                "Developer mode did not isolate the ordinary knowledge switch")
        require("开发候选流程" in visible_text(app), "Developer mode scope notice is absent")
        report["developer_option_exercised"] = True
        widget(app.checkbox, key="research_workflow_enabled").set_value(False).run()
        healthy(app, report, "developer_option_reset_without_send")

        report["stage"] = "candidate_and_source_visibility"
        widget(app.radio, key="navigation").set_value("知识库").run()
        healthy(app, report, "knowledge_candidates")
        candidates = ledger.list_records("candidate")
        sources = ledger.list_records("source")
        require(len(candidates) == len(sources) == 3, "Synthetic demo source/candidate count changed")
        for index, candidate in enumerate(candidates):
            widget(app.selectbox, label="候选知识").set_value(candidate["id"]).run()
            healthy(app, report, f"candidate:{index}")
            require(candidate["claim"]["proposition"] in visible_text(app), "Candidate text is not rendered")
            require(candidate["claim"]["anchors"][0]["quote"] in {str(item.value) for item in app.code},
                    "Candidate's actual source quote is absent")
        for index, source in enumerate(sources):
            widget(app.selectbox, label="查看来源").set_value(source["id"]).run()
            healthy(app, report, f"source:{index}")
            require(widget(app.selectbox, label="查看来源").value == source["id"], "Source selection did not bind its ID")
            text = (ledger.workspace.artifacts_dir / "source_blobs" / source["blob_sha256"]).read_text()
            require(text in {str(item.value) for item in app.code}, "Full synthetic original is not visible")
        report["candidate_sources_visible"] = {"candidates": len(candidates), "sources": len(sources)}

        # Normal page/service/schema initialization is recorded separately.
        # Read-only assertions begin only after all seven pages were exercised.
        baseline = database_snapshot(ledger)
        report["initialization"] = {"bootstrap_snapshot": bootstrap_snapshot,
            "post_page_initialization_snapshot": baseline,
            "changed_before_readonly_baseline": bootstrap_snapshot != baseline,
            "scope": "normal fresh-workspace page/service initialization, not a zero-write claim"}
        report["stage"] = "input_form_and_refresh"
        configured = ledger.get_state("workflow_input_catalog")
        catalog = ledger.get_record("workflow_input_catalog", configured["record_id"])["catalog"]
        prefix = "workflow_inputs_" + content_hash({"workspace": str(ledger.workspace.root),
                    "catalog_hash": configured["catalog_hash"]})[:20] + "_"
        widget(app.multiselect, key=prefix + "routes").set_value([r["route_id"] for r in catalog["routes"]]).run()
        healthy(app, report, "all_demo_input_routes_selected")
        for name, choice in (("counts", "声明具备"), ("auxiliary_measurements", "明确没有"),
                             ("replicate_design", "未说明")):
            key = prefix + "input_" + content_hash("/reported_inputs/" + name)[:20]
            widget(app.selectbox, key=key).set_value(choice)
        app.run()
        healthy(app, report, "three_input_states_filled")
        require(database_snapshot(ledger) == baseline, "Preparing the input form changed persistent records")
        evaluations = []
        original = WorkflowInputService.evaluate

        def counted(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            evaluations.append(result["result_hash"])
            return result

        stack.enter_context(patch.object(WorkflowInputService, "evaluate", counted))
        widget(app.button, key=prefix + "evaluate").click().run()
        healthy(app, report, "actual_development_input_check")
        require(len(evaluations) == 1, "Expected exactly one actual deterministic input evaluation")
        saved = deepcopy(app.session_state[prefix + "result"])
        review = saved["result"]
        expected = {"demo_counts": ("reported_met", "conditional_plan"),
                    "demo_auxiliary": ("reported_unmet", "blocked"), "demo_design": ("unknown", "needs_evidence")}
        observed = {r["route_id"]: (r["assessment"]["decision_check"]["preconditions_status"],
                    r["assessment"]["decision_check"]["action_status"]) for r in review["route_results"]}
        require(observed == expected, "Actual input-form results differ from the three explicit fixture states")
        require(not review["recommendation_eligible"], "Synthetic candidates acquired recommendation eligibility")
        require(all(r["local_execution"] == {"state":"unbound", "execution_authorized":False,
                    "execution_attempted":False} for r in review["route_results"]), "An execution status was upgraded")
        require("未授权，未执行" in visible_text(app), "The no-execution UI status is absent")
        for index in range(2):
            app.run()
            healthy(app, report, f"readonly_refresh:{index+1}")
            require(len(evaluations) == 1 and app.session_state[prefix + "result"] == saved,
                    "Refresh recomputed or changed the saved deterministic check")
            require(database_snapshot(ledger) == baseline, "Input check/refresh mutated the baseline ledger or files")
        report["input_form"] = {"evaluation_count": len(evaluations), "refresh_count": 2,
            "observed_states": observed, "result_hash": review["result_hash"], "persistent_snapshot_unchanged": True}
        for kind in ("model_connection", "model_profile", "model_request", "model_call", "review", "release", "task_submission"):
            require(ledger.list_records(kind) == [], "Unexpected model/scientific/governance records: " + kind)
        require(not any(report["forbidden_attempts"].values()), "A forbidden operation was attempted")
        report["activity"] = {"model_calls": 0, "network_attempts": 0, "scientific_fits": 0,
                              "human_reviews": 0, "releases": 0}
        report["stage"] = "complete"
        report["status"] = "passed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path, help="New or completely empty independent demo folder")
    parser.add_argument("--output", required=True, type=Path, help="New JSON result file; never overwrite an existing file")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        parser.error("--output must be a new file without symlink path components")
    report = {"schema_version":"standalone-public-workbench-ui-smoke-v1", "status":"failed",
        "stage":"runtime_check", "repo":str(ROOT), "ui_observations":[], "forbidden_attempts":{},
        "limits":["Actual full-app AppTest, not a browser screenshot or scientific evaluation.",
            "Synthetic engineering sources and explicit manual input states; no model conversation is sent.",
            "Python call guards and application telemetry settings are not an operating-system sandbox.",
            "Fresh schema/page initialization precedes the separately recorded read-only baseline."]}
    try:
        run_probe(args.workspace, report)
    except Exception as error:
        report["error"] = {"type":type(error).__name__, "message":str(error)[:4000]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status":report["status"], "stage":report["stage"], "output":str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
