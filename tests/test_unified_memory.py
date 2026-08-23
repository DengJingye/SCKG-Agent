from core.unified_memory import UnifiedMemoryStore


def test_inferred_preference_requires_confirmation_and_has_no_authority(tmp_path):
    store = UnifiedMemoryStore(tmp_path / "workbench.sqlite3")
    store.propose_inferred_preference(
        "user-a", "species", "human", confidence=0.7, source="reflection"
    )

    before = store.context("user-a")
    assert before.confirmed_inferences == {}
    assert before.can_affect_scientific_authority is False
    assert store.confirm_inferred_preference("user-a", "species") is True

    after = store.context("user-a")
    assert after.confirmed_inferences == {"species": "human"}
    assert after.can_affect_scientific_authority is False


def test_memory_is_user_isolated_exportable_and_deletable(tmp_path):
    store = UnifiedMemoryStore(tmp_path / "workbench.sqlite3")
    store.set_explicit_preference("user-a", "strictness", "conservative")
    store.set_explicit_preference("user-b", "strictness", "exploratory")
    store.record_episodic_run("user-a", "run-1", {"status": "blocked"})

    assert store.context("user-a").explicit_preferences == {
        "strictness": "conservative"
    }
    assert store.context("user-b").explicit_preferences == {
        "strictness": "exploratory"
    }
    exported = store.export_user_memory("user-a")
    assert exported["evidence_authority"] is False
    assert len(exported["context"]["episodic_runs"]) == 1

    store.delete_user_memory("user-a")
    assert store.context("user-a").explicit_preferences == {}
    assert store.context("user-b").explicit_preferences


def test_reflection_skill_candidates_are_deduplicated(tmp_path):
    store = UnifiedMemoryStore(tmp_path / "workbench.sqlite3")
    payload = {
        "reflection_id": "reflection-1",
        "trace_id": "trace-1",
        "memory_events": [],
        "skill_candidates": [
            {
                "candidate_id": "skill-1",
                "title": "Recover evidence span",
                "trigger": "missing source span",
                "proposed_steps": ["inspect source", "record span"],
            }
        ],
    }
    store.record_reflection("user-a", payload)
    payload["reflection_id"] = "reflection-2"
    payload["trace_id"] = "trace-2"
    payload["skill_candidates"][0]["candidate_id"] = "skill-2"
    store.record_reflection("user-a", payload)

    context = store.context("user-a")
    assert len(context.skill_candidates) == 1
    assert len(context.reflection_lessons) == 2


def test_conflicting_inference_waits_for_explicit_resolution(tmp_path):
    store = UnifiedMemoryStore(tmp_path / "workbench.sqlite3")
    store.set_explicit_preference("user-a", "species", "human")
    store.propose_inferred_preference(
        "user-a", "species", "mouse", confidence=0.8, source="reflection"
    )

    assert store.context("user-a").explicit_preferences["species"] == "human"
    conflict = store.list_conflicts("user-a")[0]
    assert conflict["status"] == "pending"
    assert store.resolve_conflict("user-a", conflict["conflict_id"], accept=True)
    assert store.context("user-a").confirmed_inferences["species"] == "mouse"
