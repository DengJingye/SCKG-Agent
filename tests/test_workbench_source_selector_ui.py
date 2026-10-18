"""Consecutive source changes must keep the selected ID and original aligned."""
import json

from streamlit.testing.v1 import AppTest

from tests.test_workbench_workflow_demo import demo


def test_consecutive_source_changes_and_refresh_keep_the_actual_original(tmp_path):
    receipt = demo.bootstrap_demo(tmp_path / "synthetic-source-selector")
    app = AppTest.from_string("""
from pathlib import Path
from sckg_workbench.storage import Ledger, Workspace
from sckg_workbench.sources import SourceService
from sckg_workbench.ui import _source_library
ledger = Ledger(Workspace(Path(WORKSPACE)))
_source_library(ledger, SourceService(ledger))
""".replace("WORKSPACE", repr(receipt["workspace"]))).run()
    assert not app.exception and not app.error
    from pathlib import Path
    from sckg_workbench.storage import Ledger, Workspace
    ledger = Ledger(Workspace(Path(receipt["workspace"])))
    sources = ledger.list_records("source")
    # Returning to the first choice catches default-index identity resets too.
    for source in sources + sources[:1]:
        select = next(item for item in app.selectbox if item.label == "查看来源")
        select.set_value(source["id"]).run()
        assert not app.exception and not app.error
        assert next(item for item in app.selectbox if item.label == "查看来源").value == source["id"]
        assert app.session_state["active_ingest_source_id"] == source["id"]
        original = ledger.get_record("original", source["original_id"])
        text = (ledger.workspace.root / original["blob_path"]).read_text()
        assert text in [item.value for item in app.code]
    before = {r["id"]: json.dumps(r, sort_keys=True) for r in ledger.list_records("source")}
    for _ in range(2):
        app.run()
        assert not app.exception and not app.error
        assert next(item for item in app.selectbox if item.label == "查看来源").value == sources[0]["id"]
    assert {r["id"]: json.dumps(r, sort_keys=True) for r in ledger.list_records("source")} == before
