"""Real AppTest over synthetic method catalogs; no model or scientific run."""
from streamlit.testing.v1 import AppTest

from tests.test_workbench_knowledge import kb
from tests.test_workbench_workflow_methods import methods
from tests.test_workbench_workflow_inputs_ui import _snapshot, _visible
from sckg_workbench.storage import content_hash
from copy import deepcopy


def _render(root):
    from pathlib import Path
    from sckg_workbench.storage import Ledger, Workspace
    from sckg_workbench.workflow_methods_ui import render_workflow_methods
    render_workflow_methods(Ledger(Workspace(Path(root))))


def ui(f):
    return AppTest.from_function(_render, args=(str(f.ledger.workspace.root),), default_timeout=20).run()


def choose(app, label, value):
    next(w for w in app.selectbox if w.label == label).set_value(value)
    return app.run()


def ready(app):
    for key, value in [('format', True), ('axes', True), ('input_kind', 'matrix'), ('normalized', True),
        ('feature_selection', False), ('balance', True), ('sgd', True), ('mini_batch', False),
        ('sparse', True), ('with_mean', False)]:
        app = choose(app, key, value)
    return app


def check(app):
    next(w for w in app.button if w.label == '检查方法配置').click()
    return app.run()


def test_opt_in_only_and_no_default_writes(methods):
    methods.ledger.set_state('workflow_method_catalog', None)
    before = _snapshot(methods.ledger)
    app = ui(methods)
    assert not app.exception and not app.subheader and not app.button
    assert _snapshot(methods.ledger) == before


def test_options_and_hidden_feature_fields_refresh_without_durable_changes(methods):
    before = _snapshot(methods.ledger)
    app = ready(ui(methods))
    assert not app.exception and not app.text_input
    app = check(app)
    text = _visible(app)
    assert 'Synthetic train：仅保留条件计划' in text
    assert '该选项不适用；不据此否定整个方法' in text
    assert '未绑定、未授权、未执行' in text
    app.run()
    assert not app.exception and 'Synthetic train：仅保留条件计划' in _visible(app)
    app = choose(app, 'feature_selection', True)
    assert '旧结果已隐藏' in _visible(app)
    assert {w.label for w in app.text_input} == {'top_genes', 'postfilter_genes'}
    app = check(app)
    assert 'Synthetic train：需补充信息' in _visible(app)
    for widget in app.text_input:
        widget.set_value('300')
    app.run(); app = check(app)
    assert 'Synthetic train：当前报告阻塞此配置' in _visible(app)
    app = choose(app, 'feature_selection', False)
    assert not app.text_input and '旧结果已隐藏' in _visible(app)
    app = check(app)
    assert 'Synthetic train：仅保留条件计划' in _visible(app)
    assert _snapshot(methods.ledger) == before


def test_conflicting_user_reports_and_separate_protocol_are_visible(methods):
    before = _snapshot(methods.ledger)
    app = ready(ui(methods)); app = choose(app, 'normalized', False); app = check(app)
    assert 'Synthetic train：报告冲突，先澄清' in _visible(app)
    assert any('输入声明与配置报告冲突' in w.value for w in app.warning)
    app = choose(app, 'normalized', True)
    app.checkbox[0].set_value(True).run()
    app = choose(app, 'reference_only', False); app = check(app)
    assert 'Synthetic train：仅保留条件计划' in _visible(app)
    assert '研究者协议检查：blocked' in _visible(app)
    assert _snapshot(methods.ledger) == before


def test_governance_change_hides_previously_valid_result_and_bad_integer_does_not_pass(methods):
    app = ready(ui(methods)); app = choose(app, 'feature_selection', True)
    app.text_input[0].set_value('-1').run()
    assert app.error and not app.button
    for widget in app.text_input:
        widget.set_value('300' if widget.label == 'top_genes' else '301')
    app.run(); app = check(app)
    assert 'Synthetic train：仅保留条件计划' in _visible(app)
    methods.knowledge.suspend('source', methods.train_source['id'], actor='fixture', reason='Synthetic withdrawal')
    before = _snapshot(methods.ledger)
    app.run()
    assert app.error and '方法预览不可用' in _visible(app)
    assert 'Synthetic train：仅保留条件计划' not in _visible(app)
    assert _snapshot(methods.ledger) == before


def test_visibility_controller_is_reachable_when_only_its_child_is_in_the_rule(methods):
    catalog = deepcopy(methods.catalog)
    rule = catalog['routes'][0]['rules'][1]
    rule['when'] = None
    rule['expect'] = {'mode': 'all', 'atoms': [
        {'field_id': 'top_genes', 'op': 'gt', 'value': 100, 'other_field': None}]}
    catalog['routes'][0]['rules'] = [rule]
    catalog['routes'][0]['local_policy_checks'] = []
    ref = {'record_id': 'synthetic-methods-controller', 'catalog_hash': content_hash(catalog)}
    methods.ledger.put_record('workflow_method_catalog', ref['record_id'],
        {'id': ref['record_id'], 'catalog': catalog, 'catalog_hash': ref['catalog_hash']})
    methods.ledger.set_state('workflow_method_catalog', ref)
    before = _snapshot(methods.ledger)
    app = ui(methods)
    assert 'feature_selection' in {w.label for w in app.selectbox}
    app = choose(app, 'feature_selection', True)
    assert {w.label for w in app.text_input} == {'top_genes'}
    app = choose(app, 'format', True); app = choose(app, 'axes', True)
    app.text_input[0].set_value('101').run(); app = check(app)
    assert 'Synthetic train：仅保留条件计划' in _visible(app)
    assert _snapshot(methods.ledger) == before
