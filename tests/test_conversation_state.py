from agent.conversation_state import (
    next_conversation_task_state,
    resolve_conversation_task_state,
)
from core.research_agent_models import ConversationTaskState, DomainKind


def test_structured_state_is_recovered_without_reparsing_answer_prose() -> None:
    state = resolve_conversation_task_state(
        [
            {
                "role": "assistant",
                "content": "Free-form prose that mentions unrelated tools.",
                "conversation_state": {
                    "confirmed_domain": "SINGLE_CELL",
                    "confirmed_task": "doublet_detection",
                    "referenced_tools": ["Scrublet", "scDblFinder"],
                    "last_answer_claims": ["claim-001"],
                    "state_epoch": 2,
                    "runtime_build_id": "build-a",
                },
            }
        ],
        runtime_build_id="build-a",
    )

    assert state.confirmed_task == "doublet_detection"
    assert state.referenced_tools == ["Scrublet", "scDblFinder"]
    assert state.last_answer_claims == ["claim-001"]
    assert state.state_epoch == 2


def test_build_change_invalidates_cross_turn_task_state() -> None:
    state = resolve_conversation_task_state(
        [
            {
                "conversation_state": {
                    "confirmed_domain": "SINGLE_CELL",
                    "confirmed_task": "doublet_detection",
                    "state_epoch": 3,
                    "runtime_build_id": "old-build",
                }
            }
        ],
        runtime_build_id="new-build",
    )

    assert state.confirmed_domain == DomainKind.UNCERTAIN
    assert state.confirmed_task == ""
    assert state.state_epoch == 4
    assert state.runtime_build_id == "new-build"


def test_explicit_task_switch_advances_epoch_and_replaces_references() -> None:
    state = next_conversation_task_state(
        ConversationTaskState(
            confirmed_domain=DomainKind.SINGLE_CELL,
            confirmed_task="doublet_detection",
            referenced_tools=["Scrublet"],
            state_epoch=4,
            runtime_build_id="build-a",
        ),
        domain=DomainKind.SINGLE_CELL,
        task="batch_integration",
        referenced_tools=["Harmony", "Scanorama"],
        claim_ids=[],
        plan_id=None,
        action_bundle_ids=["bundle-harmony"],
        task_switched=True,
    )

    assert state.confirmed_task == "batch_integration"
    assert state.referenced_tools == ["Harmony", "Scanorama"]
    assert state.state_epoch == 5
