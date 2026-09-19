"""Composer drafts are transient; submitted task bindings and input files survive."""
from types import SimpleNamespace

import pytest

from tests.test_research_input_binding import app_function, registry, upload_bytes
from execution.research_input_binding import (
    register_upload, register_sample, registered_input_options, select_registered_input,
)


class State(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def test_composer_clear_and_browser_refresh_preserve_task_identity():
    state = State(session_id='A', workspace_artifact_id='sent-data',
                  workspace_task_handoff={'input_binding': {'artifact_id': 'sent-data'}},
                  workspace_input_pending=True)
    ns = {'st': SimpleNamespace(session_state=state), 'Dict': dict, 'Any': object}
    draft = app_function('_research_composer_draft', ns)
    stage = app_function('_stage_research_input', ns)
    clear = app_function('_clear_research_attachments', ns)
    stage({'artifact_id': 'unsent-data'})
    draft()['uploaded_context'] = {'files': [{'file_name': 'notes.txt'}]}
    assert state.workspace_artifact_id == 'sent-data'
    state.session_id = 'B'
    assert draft() == {}
    state.session_id = 'A'
    assert draft()['input_binding']['artifact_id'] == 'unsent-data'
    clear()
    assert draft() == {} and not state.workspace_input_pending
    assert state.workspace_task_handoff['input_binding']['artifact_id'] == 'sent-data'
    assert state.research_upload_generation_A == 1
    # A refreshed browser gets a fresh session, not a draft restored from the task.
    ns['st'].session_state = State(session_id='A', workspace_artifact_id='sent-data')
    assert draft() == {}


def test_registered_upload_selection_after_process_restart(tmp_path):
    reg = registry(tmp_path)
    uploaded = register_upload(reg, user_id='alice', filename='my cells.h5ad', content=upload_bytes(tmp_path))
    restarted = registry(tmp_path)
    available, unavailable = registered_input_options(restarted, user_id='alice')
    assert unavailable == [] and available[0][1] == 'my cells.h5ad'
    selected = select_registered_input(restarted, artifact_id=uploaded['artifact_id'], user_id='alice')
    assert selected == uploaded
    assert restarted.path_authorized(selected['artifact_id'], user_id='alice')
    with pytest.raises(PermissionError):
        select_registered_input(restarted, artifact_id=uploaded['artifact_id'], user_id='bob')


def test_unresolved_local_history_hidden_and_can_be_explicitly_reassociated(tmp_path):
    reg = registry(tmp_path)
    local = reg.approved_input_roots[0] / 'local.h5ad'
    local.write_bytes(upload_bytes(tmp_path))
    record = reg.register(user_id='alice', path=local)
    restarted = registry(tmp_path)
    assert registered_input_options(restarted, user_id='alice') == ([], [record.artifact_id])
    assert local.is_file()  # Hiding a stale selector entry does not remove the input.
    restarted.register(user_id='alice', path=local)
    assert select_registered_input(restarted, artifact_id=record.artifact_id, user_id='alice')['shape'] == [3, 4]


def test_missing_or_tampered_upload_cannot_be_selected(tmp_path):
    reg = registry(tmp_path)
    uploaded = register_upload(reg, user_id='alice', filename='data.h5ad', content=upload_bytes(tmp_path))
    path = reg.resolve_path(uploaded['artifact_id'], user_id='alice')
    content = path.read_bytes()
    # Same-size drift still must fail full identity validation on explicit selection.
    path.write_bytes(b'x' + content[1:])
    restarted = registry(tmp_path)
    with pytest.raises(ValueError):
        select_registered_input(restarted, artifact_id=uploaded['artifact_id'], user_id='alice')
    path.unlink()  # Disposable test fixture only.
    assert registered_input_options(restarted, user_id='alice') == ([], [uploaded['artifact_id']])


def test_sample_display_name_and_identity_after_restart(tmp_path):
    reg = registry(tmp_path)
    sample = register_sample(reg, user_id='alice')
    assert sample['original_filename'] == 'sample.h5ad'
    assert sample['source'] == 'explicit_demo'
    restarted = registry(tmp_path)
    assert registered_input_options(restarted, user_id='alice')[0][0][1] == 'sample.h5ad'
    assert select_registered_input(restarted, artifact_id=sample['artifact_id'], user_id='alice') == sample
