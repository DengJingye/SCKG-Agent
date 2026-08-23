from __future__ import annotations

import json

from agent.research_chat_reasoner import ExternalReasoningResult, SemanticParseResult
from core.research_agent_models import ResearchToolCall
from eval.live_llm_runtime import resolve_live_llm_runtime
from eval.live_llm_smoke import REQUIRED_CONFIRMATION, run_live_llm_smoke
from tests.test_research_chat_service import _service


class _ForbiddenService:
    def __init__(self):
        raise AssertionError("service must not initialize while live smoke is blocked")


class _SmokeReasoner:
    def parse(self, *, query, **kwargs):
        lower = query.casefold()
        if "cellphonedb" in lower:
            intent = "execution"
            task = "cell_cell_communication"
        elif "蛋白质结构" in query:
            intent = "workflow"
            task = ""
        elif "top-3" in lower:
            intent = "caveat_comparison"
            task = "doublet_detection"
        elif "这个分析" in query:
            intent = "workflow"
            task = "doublet_detection"
        else:
            intent = "tool_recommendation"
            task = "doublet_detection"
        return SemanticParseResult(
            status="ready",
            domain="SINGLE_CELL",
            intent=intent,
            canonical_task=task,
            task_switch="这个分析" not in query,
            answer_shape="workflow_code",
            tool_calls=(
                [
                    ResearchToolCall(
                        call_id="smoke-search",
                        tool_name="search_evidence",
                        query=query,
                        canonical_task=task,
                    )
                ]
                if task
                else []
            ),
            confidence=1.0,
            provider="fake.deepseek.local",
            model_name="fake-deepseek",
            input_tokens=12,
            output_tokens=8,
            provider_call_attempted=True,
        )

    def synthesize(self, *, query, **kwargs):
        if "top-3" in query.casefold():
            content = (
                "### 已核验证据\n"
                "- **Scrublet**：输入必须是 raw count matrix。[1]\n"
                "### 模型通识（尚未核验）\n"
                "- 缺少 source-bound caveat：**scDblFinder**。\n"
                "- 缺少 source-bound caveat：**DoubletFinder**。"
            )
        else:
            content = "建议比较 Scrublet 与 scDblFinder，并先确认 raw counts 和样本分组。[1]"
        return ExternalReasoningResult(
            status="ready",
            content=content,
            provider="fake.deepseek.local",
            model_name="fake-deepseek",
            input_tokens=20,
            output_tokens=15,
            provider_call_attempted=True,
        )


class _BlockedParentResult:
    def model_dump(self, mode="json"):
        return {
            "status": "BLOCKED",
            "route": "CONTRACT_REVIEW",
            "workflow_plan": None,
            "blockers": ["reviewed_tool_contract_missing_for_requested_task"],
            "execution_request_count": 0,
        }


class _SmokeParentAgent:
    def __init__(self, delegate):
        self.delegate = delegate

    def run(self, request):
        if "cellphonedb" in request.query.casefold():
            return _BlockedParentResult()
        return self.delegate.run(request)


def test_live_smoke_does_not_initialize_service_without_consent(tmp_path):
    summary = run_live_llm_smoke(
        authorize_outbound=False,
        confirmation_text="",
        runtime_config={"api_key": "never-used"},
        service_factory=_ForbiddenService,
        output_dir=tmp_path,
    )

    assert summary.status == "blocked"
    assert summary.completed_model_call_count == 0
    assert (tmp_path / "runs.jsonl").read_text(encoding="utf-8") == ""


def test_live_smoke_blocks_when_credentials_are_missing(tmp_path):
    summary = run_live_llm_smoke(
        authorize_outbound=True,
        confirmation_text=REQUIRED_CONFIRMATION,
        runtime_config=None,
        service_factory=_ForbiddenService,
        output_dir=tmp_path,
    )

    assert summary.reason == "llm_credentials_not_configured"
    assert summary.attempted_turn_count == 0


def test_live_smoke_runs_five_sequential_governed_turns(tmp_path):
    def factory():
        service_root = tmp_path / "service"
        service_root.mkdir()
        service = _service(service_root)
        service._reasoner = _SmokeReasoner()
        service._parent_agent = _SmokeParentAgent(service._parent_agent)
        return service

    summary = run_live_llm_smoke(
        authorize_outbound=True,
        confirmation_text=REQUIRED_CONFIRMATION,
        runtime_config={
            "api_key": "test-only",
            "api_base": "https://example.invalid/v1",
            "model_name": "fake-deepseek",
        },
        safe_runtime_metadata={
            "api_host": "example.invalid",
            "model_name": "fake-deepseek",
            "credential_source": "test",
        },
        service_factory=factory,
        output_dir=tmp_path / "output",
    )

    assert summary.gate_passed is True
    assert summary.attempted_turn_count == 5
    assert summary.completed_model_call_count == 5
    assert summary.unauthorized_execution_request_count == 0
    runs = [
        json.loads(line)
        for line in (tmp_path / "output/runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["provider_call_count"] for row in runs] == [2, 1, 2, 0, 0]
    assert runs[1]["workflow_created"] is True
    assert runs[2]["top_k_format_correct"] is True
    assert runs[3]["observed_task"] == "Unknown"
    assert runs[4]["execution_request_count"] == 0


def test_runtime_resolution_does_not_invent_credentials(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MODEL_NAME"):
        monkeypatch.delenv(name, raising=False)
    from core.settings import get_settings

    get_settings.cache_clear()
    result = resolve_live_llm_runtime(db_path=tmp_path / "empty.sqlite3")
    get_settings.cache_clear()

    assert result.status == "blocked"
    assert result.reason == "llm_credentials_not_configured"
    assert "api_key" not in result.safe_metadata


def test_runtime_resolution_unlocks_encrypted_config_without_exposing_secret(tmp_path):
    from core.user_store import save_encrypted_api_config

    db_path = tmp_path / "workbench.sqlite3"
    save_encrypted_api_config(
        "openai_compatible",
        "https://api.deepseek.example/v1",
        "deepseek-test",
        "secret-test-key",
        "local-passphrase",
        db_path=db_path,
    )

    result = resolve_live_llm_runtime(
        passphrase="local-passphrase",
        db_path=db_path,
    )

    assert result.status == "ready"
    assert result.runtime_config["api_key"] == "secret-test-key"
    assert result.safe_metadata["api_host"] == "api.deepseek.example"
    assert "secret-test-key" not in json.dumps(result.safe_metadata)
    assert "api_key" not in result.safe_metadata


def test_runtime_resolution_can_explicitly_use_environment_when_store_exists(
    tmp_path,
    monkeypatch,
):
    from core.settings import get_settings
    from core.user_store import save_encrypted_api_config

    db_path = tmp_path / "workbench.sqlite3"
    save_encrypted_api_config(
        "openai_compatible",
        "https://encrypted.example/v1",
        "encrypted-model",
        "encrypted-secret",
        "local-passphrase",
        db_path=db_path,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-secret")
    monkeypatch.setenv("OPENAI_API_BASE", "https://environment.example/v1")
    monkeypatch.setenv("MODEL_NAME", "environment-model")
    get_settings.cache_clear()

    result = resolve_live_llm_runtime(
        db_path=db_path,
        credential_source="environment",
    )
    get_settings.cache_clear()

    assert result.status == "ready"
    assert result.runtime_config["api_key"] == "environment-secret"
    assert result.safe_metadata["credential_source"] == "environment"
    assert result.safe_metadata["api_host"] == "environment.example"
    assert "environment-secret" not in json.dumps(result.safe_metadata)
