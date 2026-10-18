"""Real settings-page interactions over synthetic private fixture workspaces."""
import json

import pytest

from sckg_workbench.model_service import ModelService
from sckg_workbench.storage import content_hash
from tests.test_workbench_ui import ui, page, widget


FORMAT = {"type": "json_schema", "json_schema": {"name": "synthetic_ui", "strict": True,
    "schema": {"type": "object", "properties": {}, "additionalProperties": False}}}


def configure(ui):
    app, ledger = ui
    models = ModelService(ledger.workspace, ledger)
    connection = models.create_connection("Synthetic UI provider", "https://fixture.invalid/v1",
        "not-a-real-secret", "synthetic-passphrase")
    page(app, "设置")
    widget(app.text_input, "Profile 名称").set_value("Synthetic declared output")
    widget(app.text_input, "准确模型名称").set_value("synthetic-model")
    return app, ledger, models, connection


def reports(app):
    return [json.loads(item.value) if isinstance(item.value, str) else item.value for item in app.json]


def deny(*args, **kwargs):
    pytest.fail("Settings preflight must not read credentials or request a model")


def test_settings_can_create_declared_profile_and_check_without_credentials(ui, monkeypatch):
    app, ledger, _, _ = configure(ui)
    app.checkbox(key="profile_wire_declared").set_value(True)
    app.multiselect(key="profile_wire_formats").set_value(["json_object"])
    widget(app.button, "保存不可变用途 profile").click().run()
    assert not app.exception and not app.error
    profile = ledger.list_records("model_profile")[0]
    assert profile["wire_capabilities"]["response_formats"] == ["json_object"]
    assert profile["wire_capabilities"]["json_schema_format_hashes"] == []
    before = ledger.events()
    monkeypatch.setattr(ModelService, "_credential", deny)
    app.text_area(key="wire_preflight_format").set_value('{"type":"json_object"}')
    app.button(key="wire_preflight_check").click().run()
    result = next(row for row in reports(app) if row.get("schema_version") == "model-wire-preflight-v1")
    assert result["capabilities_status"] == "declared_within_limits" and result["dispatch_allowed"]
    assert result["remotely_verified"] is False
    app.run()
    assert not app.exception and not ledger.list_records("model_call")
    assert not ledger.list_records("model_request") and ledger.events() == before


def test_settings_rejects_invalid_declaration_without_saving_profile(ui):
    app, ledger, _, _ = configure(ui)
    app.checkbox(key="profile_wire_declared").set_value(True)
    app.multiselect(key="profile_wire_formats").set_value(["json_schema"])
    app.text_area(key="profile_wire_hashes").set_value("invalid-synthetic-hash")
    widget(app.button, "保存不可变用途 profile").click().run()
    assert not app.exception and app.error
    assert ledger.list_records("model_profile") == [] and ledger.list_records("model_call") == []


def test_settings_legacy_strict_check_does_not_migrate_or_send(ui, monkeypatch):
    app, ledger, models, connection = configure(ui)
    old = models.create_profile("Synthetic legacy", "chat", connection["id"], "synthetic-model")
    app.run()
    before = ledger.events()
    monkeypatch.setattr(ModelService, "_credential", deny)
    app.text_area(key="wire_preflight_format").set_value(json.dumps(FORMAT))
    app.button(key="wire_preflight_check").click().run()
    result = next(row for row in reports(app) if row.get("schema_version") == "model-wire-preflight-v1")
    assert result["capabilities_status"] == "legacy_unqualified" and not result["dispatch_allowed"]
    assert result["reason"] == "declaration_required"
    assert ledger.get_record("model_profile", old["id"]) == old
    assert not app.exception and not app.error and ledger.events() == before
    assert not ledger.list_records("model_request") and not ledger.list_records("model_call")


def test_settings_exact_format_hash_is_saved_without_claiming_remote_verification(ui, monkeypatch):
    app, ledger, _, _ = configure(ui)
    app.checkbox(key="profile_wire_declared").set_value(True)
    app.multiselect(key="profile_wire_formats").set_value(["json_schema"])
    app.text_area(key="profile_wire_hashes").set_value(content_hash(FORMAT))
    widget(app.button, "保存不可变用途 profile").click().run()
    assert not app.exception and not app.error
    assert ledger.list_records("model_profile")[0]["wire_capabilities"]["json_schema_format_hashes"] == [content_hash(FORMAT)]
    monkeypatch.setattr(ModelService, "_credential", deny)
    app.text_area(key="wire_preflight_format").set_value(json.dumps(FORMAT))
    app.button(key="wire_preflight_check").click().run()
    result = next(row for row in reports(app) if row.get("schema_version") == "model-wire-preflight-v1")
    assert result["dispatch_allowed"] and not result["remotely_verified"]
    changed = json.loads(json.dumps(FORMAT)); changed["json_schema"]["name"] = "different_synthetic_name"
    app.text_area(key="wire_preflight_format").set_value(json.dumps(changed))
    app.button(key="wire_preflight_check").click().run()
    result = next(row for row in reports(app) if row.get("schema_version") == "model-wire-preflight-v1")
    assert not result["dispatch_allowed"] and result["reason"] == "json_schema_format_hash_not_declared"
    assert not app.exception and not ledger.list_records("model_request") and not ledger.list_records("model_call")
