from types import SimpleNamespace

from core.execution_models import ParameterProvenance
from core.runtime_pack_models import RuntimePackSource, RuntimePackState
from observability.workflow_plan_presentation import parameter_source_rows, runtime_probe_display


def test_parameter_links_preserve_exact_registered_provenance():
    source = ParameterProvenance(
        parameter_name="n_neighbors", value_or_range=15,
        origin_type="source_bound_prior", source_type="official_default",
        source_id="https://scanpy.readthedocs.io/en/stable/api/generated/scanpy.pp.neighbors.html",
        source_span="parameters.n_neighbors", tool_version="1.11.2",
        applicable_scope="project profile", limitations=["not a tuned optimum"],
    )
    before = source.model_dump()
    rows = parameter_source_rows([SimpleNamespace(operation="neighbors", parameter_provenance=[source])])
    assert rows[0]["source_url"] == source.source_id
    assert rows[0]["locator"] == "parameters.n_neighbors"
    assert rows[0]["version"] == "1.11.2"
    assert rows[0]["limitations"] == "not a tuned optimum"
    assert source.model_dump() == before


def test_internal_missing_unsafe_sources_are_not_invented_links():
    for identity in (None, "scanpy:1.11.2", "scanpy_core_reproducibility_policy_v1", "javascript:alert(1)"):
        source = ParameterProvenance(parameter_name="seed", value_or_range=0,
            origin_type="contract_default", source_type="policy_rule", source_id=identity)
        rows = parameter_source_rows([SimpleNamespace(operation="umap", parameter_provenance=[source])])
        assert rows[0]["source_url"] is None
        assert rows[0]["source_id"] == (identity or "未登记来源")
    assert parameter_source_rows([]) == []


def test_missing_runtime_is_not_called_invalid_or_ready():
    row = runtime_probe_display(SimpleNamespace(state=RuntimePackState.MISSING, source=RuntimePackSource.NONE))
    assert row["state"] == "missing"
    assert row["source"] == "未发现已登记环境"
    assert "不是数据大小" in row["说明"]


def test_plan_ui_renders_actual_clickable_column(tmp_path):
    from streamlit.testing.v1 import AppTest
    # Isolated UI smoke: no app-level fixtures, data registration or frozen Seed writes.
    app = AppTest.from_string('''
import streamlit as st
from types import SimpleNamespace
from core.execution_models import ParameterProvenance
from observability.workflow_plan_presentation import parameter_source_rows
p = ParameterProvenance(parameter_name="n", value_or_range=15,
    origin_type="source_bound_prior", source_type="official_default",
    source_id="https://scanpy.readthedocs.io/en/stable/")
st.dataframe(parameter_source_rows([SimpleNamespace(operation="neighbors", parameter_provenance=[p])]),
    column_config={"source_url": st.column_config.LinkColumn("原文链接", display_text="打开原文")})
''').run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["source_url"] == "https://scanpy.readthedocs.io/en/stable/"
    assert '"type": "link"' in app.dataframe[0].proto.columns
