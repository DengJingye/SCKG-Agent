"""Archived phase formats and instruction bytes are independent of new defaults."""
import hashlib
import json
from pathlib import Path

import pytest

from sckg_workbench import workflow_chat
from sckg_workbench.storage import canonical_json


ARCHIVE = json.loads((Path(__file__).parent / 'fixtures/workflow_phase_v3_formats.json').read_text())


@pytest.mark.parametrize('phase', ['initial', 'tool_or_finish', 'finish'])
def test_published_v3_formats_stay_identical(phase):
    actual = workflow_chat.workflow_format(initial=phase == 'initial', final_only=phase == 'finish',
        answer_contract_version=workflow_chat.PHASE_CONTRACT_VERSION)
    assert canonical_json(actual) == canonical_json(ARCHIVE['formats'][phase])


@pytest.mark.parametrize('name', list(ARCHIVE['instruction_sha256']))
def test_published_legacy_instructions_stay_identical(name):
    assert hashlib.sha256(getattr(workflow_chat, name).encode()).hexdigest() == ARCHIVE['instruction_sha256'][name]
